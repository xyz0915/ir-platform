"""异常检测器 — 检测异常进程、可疑外连、可疑启动项（增强版含白名单过滤+累加评分+进程链检测）."""

import json
import logging
from typing import Any, Optional

from app.rules.rule_engine import RuleEngine

logger = logging.getLogger(__name__)

# 累加评分权重映射（与 risk_assessor.SEVERITY_WEIGHTS 统一，决策4/§4.1）
SEVERITY_SCORES: dict[str, int] = {
    "critical": 35,
    "high": 20,
    "medium": 10,
    "low": 5,
    "info": 1,
}

# 严重程度优先级排序
SEVERITY_ORDER: dict[str, int] = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
    "info": 4,
}

# 白名单抑制阈值：whitelisted 进程仅命中低/信息级规则时视为纯白名单噪音，不误报
_WHITELIST_SUPPRESS_SEVERITIES = ("info", "low")


def _build_chain_attack_path(pid: int, ancestor_map: dict, process_map: dict) -> str:
    """由 ancestor_map 构建进程链路 attack_path（root → ... → self）.

    兼容 ``"A → B → C"``（主）、``"A -> B"``、``"A => B"`` 多种分隔；
    链路节点不足 2 个时返回空串（交由调用方兜底为父-子简写）。
    """
    anc_pids = list(ancestor_map.get(pid, []) or [])
    names: list = []
    for ap in reversed(anc_pids):
        aproc = process_map.get(ap)
        if isinstance(aproc, dict):
            names.append(str(aproc.get("name", "")))
    self_proc = process_map.get(pid)
    if isinstance(self_proc, dict):
        names.append(str(self_proc.get("name", "")))
    names = [n for n in names if n]
    if len(names) >= 2:
        return " → ".join(names)
    return ""


class AnomalyDetector:
    """异常检测器（增强版）.

    通过规则引擎检测进程、网络连接、启动项中的异常。
    增强功能：
    - 白名单过滤：传入 whitelist_service 对象，过滤掉白名单进程
    - 全局上下文：构建 process_map 和 all_items，用于 process_chain/time_cluster 检测
    - 累加评分：同一 PID 合并所有命中规则，累加 risk_score，提取 attack_path
    """

    @staticmethod
    def detect_processes(raw_data: dict, rules: list, whitelist_service=None) -> list:
        """检测异常进程（增强版）.

        Args:
            raw_data: Agent JSON 数据.
            rules: 规则列表.
            whitelist_service: 白名单服务对象（可选），用于过滤白名单进程.

        Returns:
            异常进程列表（含 risk_score/matched_rules/attack_path 字段）.
        """
        processes = raw_data.get("processes", [])
        if not isinstance(processes, list):
            return []

        # ── 1. 白名单标注（T04 根因修复）──────────────────────────────
        # 不再整体剔除白名单进程（旧逻辑 filter_whitelisted 整体剔除会导致白名单进程
        # 衍生的恶意子链漏检）。改为对进程标 proc["whitelisted"]=True 仍保留建树，
        # 其派生的 script/LOLBin 子链由 whitelist_derived_chain 行为模式评估；
        # 纯白名单进程本身在累加评分阶段被抑制（不误报）。
        if whitelist_service:
            for proc in processes:
                if isinstance(proc, dict):
                    proc["whitelisted"] = bool(whitelist_service.is_whitelisted(proc))
            logger.info("Whitelist marked for %d processes", len(processes))

        # ── 2. 补充 parent_name 和 connection_count，构建 process_map ─
        pid_to_proc: dict[int, dict] = {}
        for proc in processes:
            if isinstance(proc, dict):
                pid = proc.get("pid")
                if pid is not None:
                    pid_to_proc[pid] = proc

        # T07：构建 ancestor_map（多级祖先回溯，遇 0/1/4 或环停止）
        ancestor_map: dict[int, list] = {}
        for proc in processes:
            if not isinstance(proc, dict):
                continue
            pid = proc.get("pid")
            if pid is None:
                continue
            chain: list = []
            cur = proc.get("ppid")
            seen: set = set()
            depth = 0
            while (
                cur is not None
                and cur not in (0, 1, 4)
                and cur not in seen
                and depth < 10
            ):
                seen.add(cur)
                chain.append(cur)
                parent = pid_to_proc.get(cur)
                if not parent:
                    break
                cur = parent.get("ppid")
                depth += 1
            ancestor_map[pid] = chain

        for proc in processes:
            if isinstance(proc, dict):
                ppid = proc.get("ppid", 0)
                parent_proc = pid_to_proc.get(ppid)
                proc["parent_name"] = parent_proc.get("name", "") if parent_proc else ""
                connections = proc.get("connections", [])
                proc["connection_count"] = len(connections) if isinstance(connections, list) else 0

        # ── 3. 规则匹配（含全局上下文）──────────────────────────────
        process_rules = [r for r in rules if r.get("category") in ("process", "behavior", "execution")]
        global_context = {
            "process_map": pid_to_proc,
            "all_items": processes,
            # T07：多级祖先链（供 ancestry_chain / 链路级评分使用）
            "ancestor_map": ancestor_map,
            # T3: 补充 connections（来自 Agent 原始 raw_data.network.connections），
            # 供 anomalous_net_process 行为模式按 pid 关联外连使用。
            "connections": raw_data.get("network", {}).get("connections", []) or [],
            # T3：主机 hash IOC 分组（RuleEngine.evaluate 入口会按 host_id 实时重载；
            # 此处预置保证 detect_processes 调用方传入 iocs_by_type 时一致）。
            "iocs_by_type": RuleEngine._load_iocs_by_type(),
        }

        matches = RuleEngine.evaluate(
            processes, process_rules, global_context=global_context
        )

        # 构建 name -> 中文 label 映射，用于 matched_rules 增量携带中文描述
        # （向后兼容：name 作为稳定 ID 不变，label 仅作展示兜底）
        rule_label_map = {
            r.get("name"): r.get("label")
            for r in rules
            if r.get("name")
        }

        # ── 4. 累加评分合并 ──────────────────────────────────────────
        abnormal_processes = AnomalyDetector._apply_accumulated_scoring(
            matches, rule_label_map, global_context=global_context
        )

        return abnormal_processes

    @staticmethod
    def _apply_accumulated_scoring(
        matches: list,
        rule_label_map: Optional[dict] = None,
        global_context: Optional[dict] = None,
    ) -> list:
        """累加评分合并 — 同一 PID 合并所有命中规则，累加 risk_score.

        对每个 PID：
        - 合并所有 matched_rules（[{name, label, severity, reason}]）
        - 累加 risk_score：critical=40, high=25, medium=10, low=5, info=2
        - risk_score = min(sum, 100)
        - severity 取所有命中规则中最高的
        - attack_path 从 process_chain 命中中提取

        Args:
            matches: 规则匹配结果列表.

        Returns:
            增强版异常进程列表（含 risk_score/matched_rules/attack_path）.
        """
        # 按 PID 聚合所有命中规则
        pid_groups: dict[int, list] = {}
        for match in matches:
            item = match.get("item", {}) or {}
            pid = item.get("pid", 0)
            pid_groups.setdefault(pid, []).append(match)

        # 1) 逐 PID 初步聚合（与旧逻辑完全一致，保证无 global_context 时输出不变）
        prelim: dict[int, dict] = {}
        for pid, group_matches in pid_groups.items():
            base_item = group_matches[0].get("item", {}) or {}

            matched_rules_list = []
            total_score = 0
            highest_severity = "info"
            highest_severity_order = SEVERITY_ORDER.get("info", 4)
            attack_path = None

            for m in group_matches:
                rule_name = m.get("rule_name", "")
                severity = m.get("severity", "medium")
                reason = m.get("reason", "")

                # 增量携带中文 label（兼容历史统计依赖的 name 稳定 ID）
                rule_label = (
                    (m.get("rule") or {}).get("label")
                    or (rule_label_map or {}).get(rule_name)
                    or rule_name
                )

                matched_rules_list.append({
                    "name": rule_name,
                    "label": rule_label,
                    "severity": severity,
                    "reason": reason,
                })

                total_score += SEVERITY_SCORES.get(severity, 2)

                sev_order = SEVERITY_ORDER.get(severity, 4)
                if sev_order < highest_severity_order:
                    highest_severity = severity
                    highest_severity_order = sev_order

                item_data = m.get("item", {}) or {}
                if item_data.get("_attack_path"):
                    attack_path = item_data["_attack_path"]

            risk_score = min(total_score, 100)

            if attack_path is None and base_item.get("parent_name"):
                attack_path = f"{base_item.get('parent_name', '')} → {base_item.get('name', '')}"

            prelim[pid] = {
                "pid": base_item.get("pid"),
                "process_name": base_item.get("name", ""),
                "process_path": base_item.get("path", ""),
                "command_line": base_item.get("command_line", ""),
                "parent_pid": base_item.get("ppid"),
                "parent_name": base_item.get("parent_name", ""),
                "reason": group_matches[0].get("reason", ""),
                "rule_name": group_matches[0].get("rule_name", ""),
                "severity": highest_severity,
                "details": {
                    "user": base_item.get("user", ""),
                    "start_time": base_item.get("start_time", ""),
                    "threads": base_item.get("threads", 0),
                },
                "risk_score": risk_score,
                "matched_rules": matched_rules_list,
                "attack_path": attack_path,
                # 内部字段（最终返回前剔除）
                "_pid": pid,
                "_item": base_item,
                "_whitelisted": bool(base_item.get("whitelisted")),
                "_highest_sev": highest_severity,
            }

        # 无 global_context：保持旧行为，直接返回
        if not global_context:
            return [
                {k: v for k, v in res.items() if not k.startswith("_")}
                for res in prelim.values()
            ]

        # 2) T08 链路级聚合：构建祖先+后代关系，累加同链节点 risk_score
        process_map = global_context.get("process_map", {}) or {}
        ancestor_map = global_context.get("ancestor_map", {}) or {}
        children_map: dict[int, list] = {}
        for apid, aproc in process_map.items():
            if not isinstance(aproc, dict):
                continue
            appid = aproc.get("ppid")
            if appid is not None:
                children_map.setdefault(appid, []).append(apid)

        def _chain_pids(root_pid: int) -> set:
            """返回 root_pid 所在完整 ancestry 链的 pid 集合（祖先 + 自身 + 后代）."""
            chain: set = {root_pid}
            for anc in ancestor_map.get(root_pid, []) or []:
                chain.add(anc)
            stack = [root_pid]
            while stack:
                node = stack.pop()
                for child in children_map.get(node, []) or []:
                    if child not in chain:
                        chain.add(child)
                        stack.append(child)
            return chain

        chain_score: dict[int, int] = {}
        for pid in prelim:
            total = 0
            for cp in _chain_pids(pid):
                if cp in prelim:
                    total += prelim[cp]["risk_score"]
            chain_score[pid] = min(total, 100)

        # 3) T04 白名单抑制 + 链路级 risk_score / attack_path 覆盖
        abnormal_processes = []
        for pid, res in prelim.items():
            # 纯白名单噪音（whitelisted 且仅低/信息级命中）不误报
            if res["_whitelisted"] and res["_highest_sev"] in _WHITELIST_SUPPRESS_SEVERITIES:
                continue
            res["risk_score"] = chain_score[pid]
            chain_path = _build_chain_attack_path(pid, ancestor_map, process_map)
            if chain_path:
                res["attack_path"] = chain_path
            abnormal_processes.append(
                {k: v for k, v in res.items() if not k.startswith("_")}
            )

        return abnormal_processes

    @staticmethod
    def detect_connections(raw_data: dict, rules: list) -> list:
        """检测可疑外连.

        Args:
            raw_data: Agent JSON 数据.
            rules: 规则列表.

        Returns:
            可疑外连列表.
        """
        network = raw_data.get("network", {})
        if not isinstance(network, dict):
            return []

        connections = network.get("connections", [])
        if not isinstance(connections, list):
            return []

        # 筛选网络和 IOC 相关规则
        network_rules = [r for r in rules if r.get("category") in ("network", "ioc")]

        matches = RuleEngine.evaluate(connections, network_rules)

        suspicious_connections = []
        for match in matches:
            item = match["item"]
            suspicious_connections.append({
                "protocol": item.get("protocol", ""),
                "local_address": item.get("local_address", ""),
                "local_port": item.get("local_port", 0),
                "remote_address": item.get("remote_address", ""),
                "remote_port": item.get("remote_port", 0),
                "state": item.get("state", ""),
                "process_name": item.get("process_name", ""),
                "pid": item.get("pid", 0),
                "reason": match["reason"],
                "rule_name": match["rule_name"],
                "severity": match["severity"],
            })

        return suspicious_connections

    @staticmethod
    def detect_startup_items(raw_data: dict, rules: list) -> list:
        """检测可疑启动项.

        Args:
            raw_data: Agent JSON 数据.
            rules: 规则列表.

        Returns:
            可疑启动项列表.
        """
        startup_items = raw_data.get("startup_items", [])
        if not isinstance(startup_items, list):
            return []

        # 筛选启动项和持久化相关规则
        startup_rules = [r for r in rules if r.get("category") in ("startup", "persistence")]

        matches = RuleEngine.evaluate(startup_items, startup_rules)

        suspicious_items = []
        for match in matches:
            item = match["item"]
            suspicious_items.append({
                "name": item.get("name", ""),
                "command": item.get("command", ""),
                "location": item.get("location", ""),
                "type": item.get("type", ""),
                "user": item.get("user", ""),
                "reason": match["reason"],
                "rule_name": match["rule_name"],
                "severity": match["severity"],
            })

        return suspicious_items

    # ─────────────────────────────────────────────────────────────
    # 融合扩充：WebShell / 内存码检测 + 统一关联引擎（A §二/§三/§五）
    # 与 detect_processes 同构，复用 RuleEngine.evaluate；
    # 不修改任何既有 detect_* 调用链（只增不改）。
    # ─────────────────────────────────────────────────────────────

    # 关联引擎：信号类别 → ATT&CK 技术映射（§5.3）
    ATTACK_TECH_MAP: dict = {
        "webshell": ["T1505.003"],
        "memory_shell": ["T1609"],
        "process_injection": ["T1055"],
        "suspicious_connection": ["T1059"],
        "suspicious_process": ["T1547", "T1564"],
    }

    # 朴素贝叶斯下限：严重度 → 基线概率 p_i（§5.1）
    _SEVERITY_PROB: dict = {
        "critical": 0.95,
        "high": 0.80,
        "medium": 0.50,
        "low": 0.20,
        "info": 0.10,
    }

    # 组合 incident 关联增益（命中「WebShell 落盘 + 同主机内存马」攻击链时提权）
    _COMBO_BOOST = 25

    # 已知安全进程白名单（P0 噪音过滤）
    _SAFE_PROCESS_NAMES: set[str] = {
        "sqlservr", "vmtoolsd", "vgauthservice", "fdlauncher", "fdhost",
        "msdtssrvr", "msmdsrv", "reportingservicesservice", "sqlwriter",
        "conhost", "svchost", "csrss", "wininit", "services", "lsass",
        "smss", "winlogon", "runtimebroker", "taskhostw", "spoolsv",
        "dllhost", "sihost", "ctfmon", "searchindexer", "wlms",
    }

    # 内存注入相关规则名（用于把 abnormal_processes/event_hits 归类为 process_injection）
    _INJECTION_RULE_NAMES = (
        "memory_injection",
        "fileless_reflective_injection",
        "interpreter_mem_pe",
        "script_interpreter_memory_pe",
    )

    @staticmethod
    def detect_webshells(raw_data: dict, rules: list) -> list:
        """检测 WebShell 文件型证据（融合 A §2.2）.

        与 ``detect_processes`` 同构：筛选 ``category=webshell`` 规则，对
        ``raw_data["webshells"]`` 逐项评估并累加评分聚合。

        Args:
            raw_data: Agent JSON 数据.
            rules: 全量规则列表.

        Returns:
            WebShell 命中列表（含 severity/risk_score/matched_rules 字段）.
            老 Agent 无 ``webshells`` 键时返回空列表（向后兼容）。
        """
        webshells = raw_data.get("webshells")
        if not isinstance(webshells, list):
            return []
        ws_rules = [r for r in (rules or []) if r.get("category") == "webshell"]
        if not ws_rules:
            return []
        matches = RuleEngine.evaluate(webshells, ws_rules)
        return AnomalyDetector._apply_category_scoring(matches, group_key="path")

    @staticmethod
    def detect_memory_shells(raw_data: dict, rules: list) -> list:
        """检测内存码（Java 内存马 / PHP 扩展，融合 A §2.2）.

        与 ``detect_processes`` 同构：筛选 ``category=memory_shell`` 规则，对
        ``raw_data["memory_shells"]`` 逐项评估并累加评分聚合。
        ``pid`` 为与进程富化的关联锚点。

        Args:
            raw_data: Agent JSON 数据.
            rules: 全量规则列表.

        Returns:
            内存码命中列表（含 severity/risk_score/matched_rules 字段）.
            老 Agent 无 ``memory_shells`` 键时返回空列表（向后兼容）。
        """
        memory_shells = raw_data.get("memory_shells")
        if not isinstance(memory_shells, list):
            return []
        ms_rules = [r for r in (rules or []) if r.get("category") == "memory_shell"]
        if not ms_rules:
            return []
        matches = RuleEngine.evaluate(memory_shells, ms_rules)
        return AnomalyDetector._apply_category_scoring(matches, group_key="pid")

    @staticmethod
    def _apply_category_scoring(matches: list, group_key: str = "path") -> list:
        """累加评分聚合（WebShell / 内存码通用）.

        按 ``group_key``（WebShell 用 ``path``，内存码用 ``pid``）聚合同一证据对象的
        全部命中规则，累加 ``risk_score``（上限 100），取最高严重度，并透传原始字段。

        Args:
            matches: RuleEngine.evaluate 的匹配结果列表.
            group_key: 聚合键（缺省回退 name/pid/id）.

        Returns:
            聚合后的命中列表.
        """
        groups: dict = {}
        for m in matches:
            item = m.get("item", {}) or {}
            gk = item.get(group_key)
            if gk is None:
                gk = item.get("name") or item.get("pid") or id(item)
            groups.setdefault(gk, []).append(m)

        results: list = []
        for _gk, group in groups.items():
            base = group[0].get("item", {}) or {}
            matched_rules_list = []
            total_score = 0
            highest_severity = "info"
            highest_severity_order = SEVERITY_ORDER.get("info", 4)
            for m in group:
                rule_name = m.get("rule_name", "")
                severity = m.get("severity", "medium")
                rule_label = (m.get("rule") or {}).get("label") or rule_name
                matched_rules_list.append({
                    "name": rule_name,
                    "label": rule_label,
                    "severity": severity,
                    "reason": m.get("reason", ""),
                })
                total_score += SEVERITY_SCORES.get(severity, 2)
                order = SEVERITY_ORDER.get(severity, 4)
                if order < highest_severity_order:
                    highest_severity = severity
                    highest_severity_order = order

            results.append({
                "path": base.get("path"),
                "name": base.get("name"),
                "sha256": base.get("sha256"),
                "pid": base.get("pid"),
                "process_name": base.get("process_name"),
                "type": base.get("type"),
                "evidence": base.get("evidence"),
                "suspicious_funcs": base.get("suspicious_funcs"),
                "obfuscation_score": base.get("obfuscation_score"),
                "behinder_godzilla_signal": base.get("behinder_godzilla_signal"),
                "severity": highest_severity,
                "risk_score": min(total_score, 100),
                "matched_rules": matched_rules_list,
            })
        return results

    @staticmethod
    def correlate_incident(
        raw_data: dict,
        webshell_hits: list,
        memory_shell_hits: list,
        abnormal_processes: list,
        event_hits: list,
        suspicious_connections: Optional[list] = None,
    ) -> list:
        """统一关联引擎（合并 A correlate_webshell_memory + B 链路评分，§5.1）.

        跨 WebShell 文件 + 内存马 + 进程注入 + 可疑外连 + 异常进程 的加权关联，
        输出 incident 级置信度与 ``attack_path``，明确区分「单点告警」与「组合 incident」。

        Args:
            raw_data: Agent JSON 数据（用于回退提取可疑外连 / 主机上下文）.
            webshell_hits: detect_webshells 结果.
            memory_shell_hits: detect_memory_shells 结果.
            abnormal_processes: detect_processes 结果（含 P2 #1/#2/#4/#7）.
            event_hits: ProcessEventConsumer.evaluate 结果.
            suspicious_connections: 可选；省略时从 raw_data.network.connections 回退提取.

        Returns:
            incident / single_alert 结构列表，每项含::
                incident_id, type, confidence(0-100), severity, needs_review,
                attack_path, related_findings, attck_techniques, signals
        """
        signals = AnomalyDetector._build_signals(
            raw_data, webshell_hits, memory_shell_hits,
            abnormal_processes, event_hits, suspicious_connections,
        )
        if not signals:
            return []

        # 信号类别集合（用于区分 单点告警 vs 组合 incident）
        categories = {s["category"] for s in signals}
        is_incident = len(categories) >= 2

        # 加权组合 + 朴素贝叶斯下限：C = (1 - Π(1 - p_i)) * 100
        prob_product = 1.0
        for s in signals:
            p = AnomalyDetector._SEVERITY_PROB.get(s["severity"], 0.5)
            prob_product *= (1.0 - p)
        confidence = (1.0 - prob_product) * 100.0

        # 单信号告警：低置信度不产出（P0 噪音过滤）
        if not is_incident and confidence < 60:
            logger.info(
                "Single-alert suppressed: confidence=%.1f < threshold(60), categories=%s",
                confidence, categories,
            )
            return []

        # 关联增益：WebShell 落盘 + 同主机内存马 构成核心攻击链 → 提权
        has_ws = "webshell" in categories
        has_ms = "memory_shell" in categories
        if is_incident and has_ws and has_ms:
            confidence = min(100.0, confidence + AnomalyDetector._COMBO_BOOST)

        # 严重度（取信号中最高的；incident 高置信度提权）
        max_sev = "info"
        max_sev_order = SEVERITY_ORDER.get("info", 4)
        for s in signals:
            order = SEVERITY_ORDER.get(s["severity"], 4)
            if order < max_sev_order:
                max_sev = s["severity"]
                max_sev_order = order
        severity = max_sev
        if is_incident:
            if confidence >= 90:
                severity = "critical"
            elif confidence >= 70 and SEVERITY_ORDER[severity] > SEVERITY_ORDER["high"]:
                severity = "high"

        # 人工复核关卡：单点告警必经；组合 incident 低置信度（<90）也必经
        needs_review = (not is_incident) or confidence < 90

        # attack_path：按类别优先级排序证据链
        ordered = sorted(
            signals,
            key=lambda s: AnomalyDetector._SIGNAL_ORDER.get(s["category"], 99),
        )
        attack_path = [s["evidence"] for s in ordered if s.get("evidence")]

        related_findings = [s["finding_id"] for s in signals]

        # ATT&CK 技术：去重并集 + 映射
        attck_techniques: list = []
        attck_map: dict = {}
        for s in signals:
            for tech in s.get("attck", []):
                if tech not in attck_techniques:
                    attck_techniques.append(tech)
                attck_map.setdefault(tech, []).append(s["finding_id"])

        incident_type = "+".join(sorted(categories)) if is_incident else (max(categories, key=lambda c: AnomalyDetector._SIGNAL_ORDER.get(c, 99)))

        if is_incident:
            incident_id = "INC-" + str(abs(hash(tuple(sorted(related_findings)))))
            return [{
                "incident_id": incident_id,
                "type": incident_type,
                "kind": "incident",
                "confidence": round(confidence, 2),
                "severity": severity,
                "needs_review": needs_review,
                "attack_path": attack_path,
                "related_findings": related_findings,
                "attck_techniques": attck_techniques,
                "attck_technique_map": attck_map,
                "signals": signals,
            }]

        # 单点告警：每个信号独立成 alert
        alerts = []
        for idx, s in enumerate(signals):
            alert_id = "ALERT-" + str(abs(hash((s["finding_id"], idx))))
            alerts.append({
                "incident_id": alert_id,
                "type": s["category"],
                "kind": "single_alert",
                "confidence": round(confidence, 2),
                "severity": s["severity"],
                "needs_review": True,
                "attack_path": [s["evidence"]] if s.get("evidence") else [],
                "related_findings": [s["finding_id"]],
                "attck_techniques": s.get("attck", []),
                "attck_technique_map": {
                    t: [s["finding_id"]] for t in s.get("attck", [])
                },
                "signals": [s],
            })
        return alerts

    # 信号类别在 attack_path 中的展示优先级
    _SIGNAL_ORDER: dict = {
        "webshell": 0,
        "memory_shell": 1,
        "suspicious_connection": 2,
        "process_injection": 3,
        "suspicious_process": 4,
    }

    @staticmethod
    def _build_signals(
        raw_data: dict,
        webshell_hits: list,
        memory_shell_hits: list,
        abnormal_processes: list,
        event_hits: list,
        suspicious_connections: Optional[list],
    ) -> list:
        """将各维度命中转换为统一信号结构（供 correlate_incident 加权）."""
        signals: list = []

        for hit in (webshell_hits or []):
            if not isinstance(hit, dict):
                continue
            signals.append({
                "category": "webshell",
                "severity": hit.get("severity", "medium"),
                "evidence": f"webshell:{hit.get('path') or hit.get('name')}",
                "finding_id": f"WS-{hit.get('sha256') or hit.get('path') or hit.get('name')}",
                "attck": AnomalyDetector.ATTACK_TECH_MAP["webshell"],
                "host_context": {"path": hit.get("path"), "sha256": hit.get("sha256")},
            })

        for hit in (memory_shell_hits or []):
            if not isinstance(hit, dict):
                continue
            signals.append({
                "category": "memory_shell",
                "severity": hit.get("severity", "medium"),
                "evidence": f"memory_shell:pid={hit.get('pid')} type={hit.get('type')}",
                "finding_id": f"MS-{hit.get('pid')}",
                "attck": AnomalyDetector.ATTACK_TECH_MAP["memory_shell"],
                "host_context": {"pid": hit.get("pid"), "type": hit.get("type")},
            })

        for proc in (abnormal_processes or []):
            if not isinstance(proc, dict):
                continue
            rules = proc.get("matched_rules") or []
            rule_names = {r.get("name") for r in rules if isinstance(r, dict)}
            # 白名单跳过：已知安全进程不产出告警
            pname = (proc.get("process_name") or "").lower().removesuffix(".exe")
            if pname in AnomalyDetector._SAFE_PROCESS_NAMES:
                continue
            if rule_names & set(AnomalyDetector._INJECTION_RULE_NAMES):
                category = "process_injection"
            else:
                category = "suspicious_process"
            signals.append({
                "category": category,
                "severity": proc.get("severity", "medium"),
                "evidence": f"process:{proc.get('process_name')} pid={proc.get('pid')}",
                "finding_id": f"PROC-{proc.get('pid')}",
                "attck": AnomalyDetector.ATTACK_TECH_MAP[category],
                "host_context": {"pid": proc.get("pid")},
            })

        for proc in (event_hits or []):
            if not isinstance(proc, dict):
                continue
            rules = proc.get("matched_rules") or []
            rule_names = {r.get("name") for r in rules if isinstance(r, dict)}
            if rule_names & set(AnomalyDetector._INJECTION_RULE_NAMES):
                category = "process_injection"
            else:
                category = "suspicious_process"
            signals.append({
                "category": category,
                "severity": proc.get("severity", "medium"),
                "evidence": f"event_process:{proc.get('process_name')} pid={proc.get('pid')}",
                "finding_id": f"EVT-{proc.get('pid')}",
                "attck": AnomalyDetector.ATTACK_TECH_MAP[category],
                "host_context": {"pid": proc.get("pid")},
            })

        # 可疑外连（显式传入或回退从 raw_data 提取）
        conns = suspicious_connections
        if conns is None:
            conns = AnomalyDetector._extract_suspicious_connections(raw_data)
        for conn in (conns or []):
            if not isinstance(conn, dict):
                continue
            raddr = conn.get("remote_address") or conn.get("remote_addr") or ""
            rport = conn.get("remote_port") or 0
            signals.append({
                "category": "suspicious_connection",
                "severity": conn.get("severity", "high"),
                "evidence": f"c2:{raddr}:{rport}",
                "finding_id": f"CONN-{raddr}:{rport}",
                "attck": AnomalyDetector.ATTACK_TECH_MAP["suspicious_connection"],
                "host_context": {"remote_address": raddr, "remote_port": rport},
            })

        return signals

    # 常见 C2 / 反弹 shell 端口（回退提取可疑外连用）
    _C2_PORTS = {4444, 1337, 4445, 8443, 6667, 6666, 31337, 1080, 9050, 5900, 23}

    @staticmethod
    def _extract_suspicious_connections(raw_data: dict) -> list:
        """回退提取可疑外连（raw_data.network.connections 中 C2 端口或解释器进程外连）."""
        if not isinstance(raw_data, dict):
            return []
        conns = (raw_data.get("network", {}) or {}).get("connections", []) or []
        if not isinstance(conns, list):
            return []
        out = []
        for c in conns:
            if not isinstance(c, dict):
                continue
            try:
                port = int(c.get("remote_port") or 0)
            except (ValueError, TypeError):
                port = 0
            if port in AnomalyDetector._C2_PORTS:
                out.append({
                    "remote_address": c.get("remote_address") or c.get("remote_addr"),
                    "remote_port": port,
                    "severity": "high",
                })
        return out
