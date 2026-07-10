"""规则引擎核心 — 支持 regex/list/threshold/behavior/composite/exists 六种规则类型."""

import json
import logging
import re
from typing import Any, Optional

from app.config import settings
from app.models.rule import Rule

logger = logging.getLogger(__name__)

# ── 严重级别排序（用于威胁情报回灌时取较高者）───────────────────────
_SEVERITY_RANK: dict = {"low": 1, "medium": 2, "high": 3, "critical": 4}


def _max_severity(a: str, b: str) -> str:
    """取两个严重级别中较高的一个."""
    return a if _SEVERITY_RANK.get(a, 0) >= _SEVERITY_RANK.get(b, 0) else b

# ── 已知的 C2 框架命令行特征 ──────────────────────────────────────────
_C2_FRAMEWORK_SIGNATURES: list[str] = [
    "cobaltstrike", "metasploit", "empire", "powersploit",
    "sliver", "havoc", "brute_ratel", "nimplant",
    "mythic", "apollo", "ares", "covenant",
    "merlin", "koadic", "pupy", "quasar",
    "darkcomet", "poison_ivy", "gh0st", "plugx",
    "agenttesla", "formbook", "lokibot", "nanocore",
    "remcos", "njrat", "asyncrat", "warzone",
    "azorult", "vidar", "redline", "smokeloader",
]

# ── 引擎支持的 20 种行为模式（白名单）────────────────────────────────
# 导入/创建 behavior 规则时校验 condition.pattern ∈ 此集合，
# 非法值会在写入前被拒绝，避免"拼错静默 False 永不命中"。
BEHAVIOR_PATTERNS: set[str] = {
    "orphan_process",
    "suspicious_parent",
    "unsigned_process",
    "network_scan",
    "credential_dump",
    "uac_bypass",
    "token_manipulation",
    "antivirus_tamper",
    "defense_evasion",
    "lateral_movement",
    "data_exfil",
    "webshell_activity",
    "ransomware_behavior",
    "persistence_wmi",
    "persistence_com_hijack",
    "discovery_recon",
    "dll_sideload",
    "process_chain",
    "time_cluster",
    "short_lived",
}

# ── 正则编译缓存（T-P2-4 性能优化）────────────────────────────────────
# 同一 pattern+flags 只编译一次，避免热路径重复 re.compile。
_REGEX_CACHE: dict = {}

# ── time_cluster 预排序缓存（T-P2-4 性能优化）─────────────────────────
# key = id(all_items)，value = 按 start_time 排序后的 [(datetime, item), ...]
_TC_SORTED_CACHE: dict = {}

# ── field → ioc_type 映射（动态 IOC 引用）────────────────────────────
# list 类规则 condition.field 若为下列网络/主机标识字段，则额外把 iocs 表中
# 对应 ioc_type 且 enabled=1 的指标并入待匹配集合；映射不到的 field 仅匹配自身 values。
# 说明：remote_address 既可能承载 IP 也可能承载域名（如 suspicious_c2_domain 规则），
# 此处按"最贴近威胁语义"的口径映射为 ip（IP 类 IOC 命中更精确），域名类 IOC 由
# domain/host/url 字段各自的规则覆盖，互不干扰。
FIELD_TO_IOC_TYPE: dict = {
    # IP 类
    "remote_address": "ip",
    "remote_ip": "ip",
    "src_ip": "ip",
    "dst_ip": "ip",
    # 域名 / URL 类（按 field 名分别映射到 domain 或 url）
    "domain": "domain",
    "host": "domain",
    "url": "url",
    # 文件哈希类
    "file_hash": "hash",
    "sha256": "hash",
    "hash": "hash",
    # 证书类
    "cert": "cert",
    "certificate": "cert",
}


def validate_behavior_pattern(pattern: str) -> bool:
    """校验行为模式是否属于引擎支持的 20 种白名单.

    Args:
        pattern: behavior 规则的 condition.pattern.

    Returns:
        合法返回 True，否则 False.
    """
    return pattern in BEHAVIOR_PATTERNS


class RuleEngine:
    """规则引擎.

    支持六种规则类型：regex、list、threshold、behavior、composite、exists.
    """

    @staticmethod
    def load_rules(category: Optional[str] = None) -> list:
        """从数据库加载启用的规则.

        Args:
            category: 规则类别过滤（可选）.

        Returns:
            规则列表.
        """
        if category:
            return Rule.list(category=category, enabled=True)
        return Rule.list_enabled()

    @staticmethod
    def _compile_regex(pattern: str, flags: int) -> "re.Pattern":
        """编译并缓存正则表达式（T-P2-4 性能优化）.

        Args:
            pattern: 正则字符串.
            flags: re 标志位.

        Returns:
            已编译的 regex 对象.
        """
        cache_key = (pattern, flags)
        compiled = _REGEX_CACHE.get(cache_key)
        if compiled is None:
            compiled = re.compile(pattern, flags)
            _REGEX_CACHE[cache_key] = compiled
        return compiled

    @staticmethod
    def _build_sorted_items(all_items: list) -> list:
        """将 all_items 按 start_time 排序，供 time_cluster 二分计数（T-P2-4）.

        Args:
            all_items: 所有进程数据项列表.

        Returns:
            [(datetime, item), ...] 已排序列表；无法解析时间的项排在最前（datetime.min）.
        """
        from datetime import datetime

        cache_key = id(all_items)
        cached = _TC_SORTED_CACHE.get(cache_key)
        if cached is not None:
            return cached

        time_formats = [
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y/%m/%d %H:%M:%S",
        ]

        def _parse(ts: str):
            if not ts:
                return None
            s = str(ts).split("+")[0].split("Z")[0]
            for fmt in time_formats:
                try:
                    return datetime.strptime(s, fmt)
                except ValueError:
                    continue
            return None

        parsed = []
        for item in all_items:
            if not isinstance(item, dict):
                continue
            parsed.append((_parse(item.get("start_time", "")), item))
        parsed.sort(key=lambda x: (x[0] is None, x[0] or datetime.min))
        _TC_SORTED_CACHE[cache_key] = parsed
        return parsed

    @staticmethod
    def _load_iocs_by_type() -> dict:
        """从 DB 一次性加载全部 enabled=1 的 IOC，按 ioc_type 分组为集合.

        返回结构: {"ip": {"1.2.3.4", ...}, "domain": {...}, ...}

        - 仅在 evaluate 入口调用一次，避免逐条数据查 DB（性能）。
        - 不引入持久内存缓存，每次评估实时读取，保证 iocs 表变更立即可生效。
        - 任何 DB/导入异常都被吞掉并返回空字典，保证引擎在缺表/缺库环境下仍可降级运行。

        Returns:
            按类型分组的 IOC 指标值集合字典；出错时返回空字典。
        """
        try:
            from app.models.ioc import Ioc
        except Exception as exc:  # noqa: BLE001
            logger.debug("跳过 IOC 动态加载（Ioc 模型不可用）: %s", exc)
            return {}

        try:
            rows = Ioc.list()
        except Exception as exc:  # noqa: BLE001
            # DB 未初始化 / 缺表 / 连接异常等情况均降级为空集合
            logger.debug("跳过 IOC 动态加载（读取 iocs 失败）: %s", exc)
            return {}

        by_type: dict = {}
        for r in rows:
            if not r.get("enabled"):
                continue
            ioc_type = r.get("ioc_type")
            value = r.get("ioc_value")
            if not ioc_type or value is None:
                continue
            by_type.setdefault(ioc_type, set()).add(value)
        return by_type

    @staticmethod
    def _load_threat_level_by_value() -> dict:
        """加载威胁情报平台回灌所需的 {value_lower: {level, provider}} 映射.

        仅取每个 indicator 最新一条记录（按 queried_at 倒序去重保留首条），
        且该记录的 judgments 必须包含 malicious/suspicious：
          - malicious → level=high
          - suspicious → level=medium

        任何 DB/导入异常都被吞掉并返回空字典，保证引擎在缺表/缺库环境下仍可降级运行。

        Returns:
            按指标值（小写）分组的威胁等级字典；出错时返回空字典。
        """
        try:
            from app.database import get_connection
        except Exception as exc:  # noqa: BLE001
            logger.debug("跳过威胁情报回灌加载（database 不可用）: %s", exc)
            return {}

        try:
            with get_connection() as conn:
                rows = conn.execute(
                    """
                    SELECT ioc_value, provider, judgments, queried_at
                    FROM threat_intel
                    ORDER BY ioc_value, queried_at DESC, id DESC
                    """
                ).fetchall()
        except Exception as exc:  # noqa: BLE001
            logger.debug("跳过威胁情报回灌加载（读取 threat_intel 失败）: %s", exc)
            return {}

        result: dict = {}
        seen: set = set()
        for row in rows:
            key = (row["ioc_value"] or "").lower()
            if not key or key in seen:
                continue
            seen.add(key)
            raw_j = row["judgments"]
            if isinstance(raw_j, str) and raw_j:
                try:
                    judgments = json.loads(raw_j)
                except (json.JSONDecodeError, TypeError):
                    judgments = []
            else:
                judgments = []
            if not isinstance(judgments, list):
                judgments = []
            jset = {str(j).lower() for j in judgments}
            level = None
            if "malicious" in jset:
                level = "high"
            elif "suspicious" in jset:
                level = "medium"
            if level:
                result[key] = {"level": level, "provider": row["provider"]}
        return result

    @staticmethod
    def _record_ti_hit(global_context: Optional[dict], value_lower: str, item: dict) -> None:
        """在 list 类规则命中时，记录该命中值与威胁情报等级的关联（供 evaluate 回灌）.

        Args:
            global_context: 全局上下文（含 threat_level_by_value）。
            value_lower: 命中的指标值（已小写）。
            item: 被检测的数据项（用于按 id 归集命中）。
        """
        if not global_context:
            return
        tl = global_context.get("threat_level_by_value") or {}
        info = tl.get(value_lower)
        if not info:
            return
        ti_hits = global_context.setdefault("_ti_hits", {})
        ti_hits.setdefault(id(item), []).append({
            "value": value_lower,
            "level": info["level"],
            "provider": info.get("provider"),
        })

    @staticmethod
    def evaluate(data_items: list, rules: list, global_context: Optional[dict] = None) -> list:
        """对数据项列表执行规则匹配.

        Args:
            data_items: 待检测的数据项列表.
            rules: 规则列表.
            global_context: 全局上下文（可选），包含 process_map 和 all_items 等信息，
                            用于 behavior 模式中需要跨进程数据的检测（如 process_chain/time_cluster）.
                            本方法会在入口一次性加载 enabled=1 的 IOC，按类型分组写入
                            global_context["iocs_by_type"]，供 list 类规则动态引用。

        Returns:
            匹配结果列表 [{item, rule, reason}].
        """
        # 归一并确保为可变字典（便于注入动态 IOC 上下文）
        if global_context is None:
            global_context = {}

        # ── 动态 IOC 引用：入口一次性加载（非逐条数据）──────────────
        # 不持久缓存，每次评估实时读取，保证增删/启用开关立即可生效。
        global_context["iocs_by_type"] = RuleEngine._load_iocs_by_type()

        # ── 威胁情报平台回灌（外部 Enrichment）：仅在总开关开启时加载 ──
        # 关闭时不加载，保证零影响。结构: {value_lower: {level, provider}}
        # 仅取该 indicator 最新一条且 judgments 含 malicious/suspicious。
        if settings.ENABLE_THREAT_INTEL_ENRICHMENT:
            global_context["threat_level_by_value"] = RuleEngine._load_threat_level_by_value()
        else:
            global_context["threat_level_by_value"] = {}
        # 记录 list 类规则命中的威胁情报（供下方构造 match 时回灌升级）
        global_context["_ti_hits"] = {}

        # T-P2-4: 预排序 all_items 供 time_cluster 二分计数，降 O(n²) 为 O(n log n)
        if global_context and isinstance(global_context.get("all_items"), list):
            from datetime import datetime

            sorted_items = RuleEngine._build_sorted_items(global_context["all_items"])
            global_context["_tc_sorted"] = sorted_items
            # 并行的时间戳列表（None → datetime.min），供 bisect 二分计数
            global_context["_tc_dts"] = [
                d if d is not None else datetime.min for d, _ in sorted_items
            ]

        matches = []
        # 攻击链是主机级关联规则，需在 evaluate 末尾按 host_id 下钻统一评估，
        # 不进入「逐条数据项」匹配循环。
        per_item_rules = [r for r in rules if r.get("rule_type") != "attack_chain"]
        attack_chain_rules = [r for r in rules if r.get("rule_type") == "attack_chain"]
        for item in data_items:
            if not isinstance(item, dict):
                continue
            for rule in per_item_rules:
                if RuleEngine.match_rule(item, rule, global_context=global_context):
                    severity = rule.get("severity", "medium")
                    reason = RuleEngine._build_reason(item, rule)
                    # ── 威胁情报平台回灌：仅作用于 list 类规则命中 ──
                    # malicious → severity 升到 high 且 reason 加【威胁情报平台判黑】
                    # suspicious → reason 加【威胁情报平台可疑】，severity 不变
                    ti_hits = global_context.get("_ti_hits", {}).get(id(item), [])
                    for hit in ti_hits:
                        if hit.get("level") == "high":
                            severity = _max_severity(severity, "high")
                            reason += "【威胁情报平台判黑】"
                        elif hit.get("level") == "medium":
                            reason += "【威胁情报平台可疑】"
                    matches.append({
                        "item": item,
                        "rule": rule,
                        "rule_name": rule.get("name", ""),
                        "severity": severity,
                        "reason": reason,
                    })

        # ── 攻击链关联检测（主机级）──────────────────────────────────
        # 跨 dimension 顺序匹配，命中时强制 severity=critical，reason 含步骤明细。
        if attack_chain_rules:
            host_id = global_context.get("host_id") if global_context else None
            if host_id is not None:
                host_events = RuleEngine._build_host_events(global_context)
                for ac_rule in attack_chain_rules:
                    result = RuleEngine._match_attack_chain(ac_rule, global_context, host_events)
                    if result:
                        matches.append({
                            "item": {
                                "host_id": host_id,
                                "_attack_chain": True,
                                "attack_chain_steps": result["steps"],
                            },
                            "rule": ac_rule,
                            "rule_name": ac_rule.get("name", ""),
                            "severity": "critical",
                            "reason": result["reason"],
                        })
            else:
                logger.debug(
                    "存在 attack_chain 规则但 global_context 缺少 host_id，跳过攻击链评估"
                )
        return matches

    @staticmethod
    def match_rule(data_item: dict, rule: dict, global_context: Optional[dict] = None) -> bool:
        """检查单个数据项是否匹配规则.

        Args:
            data_item: 数据项字典.
            rule: 规则字典.
            global_context: 全局上下文（可选），用于 behavior 模式检测.

        Returns:
            是否匹配.
        """
        rule_type = rule.get("rule_type", "")
        condition = rule.get("condition", {})
        if isinstance(condition, str):
            try:
                condition = json.loads(condition)
            except json.JSONDecodeError:
                return False

        if rule_type == "regex":
            return RuleEngine._match_regex(data_item, condition)
        elif rule_type == "list":
            return RuleEngine._match_list(data_item, condition, global_context=global_context)
        elif rule_type == "threshold":
            return RuleEngine._match_threshold(data_item, condition)
        elif rule_type == "behavior":
            return RuleEngine._match_behavior(data_item, condition, global_context=global_context)
        elif rule_type == "composite":
            return RuleEngine._match_composite(data_item, condition, global_context=global_context)
        elif rule_type == "exists":
            return RuleEngine._match_exists(data_item, condition)
        elif rule_type == "attack_chain":
            # 攻击链是「主机级」关联规则，不针对单条数据项匹配；
            # 真正的匹配在 evaluate() 末尾统一按 host_id 下钻执行。
            return False
        return False

    # ── 正则匹配 ────────────────────────────────────────────────────────

    @staticmethod
    def _match_regex(data_item: dict, condition: dict) -> bool:
        """正则匹配.

        Condition 格式: {"field": "command_line", "pattern": "powershell.*-enc", "flags": "ignorecase"}
        """
        field = condition.get("field", "")
        pattern = condition.get("pattern", "")
        flags_str = condition.get("flags", "")

        value = str(data_item.get(field, ""))
        if not value or not pattern:
            return False

        flags = 0
        if "ignorecase" in flags_str:
            flags |= re.IGNORECASE
        if "multiline" in flags_str:
            flags |= re.MULTILINE

        try:
            return bool(RuleEngine._compile_regex(pattern, flags).search(value))
        except re.error:
            return False

    # ── 列表匹配 ────────────────────────────────────────────────────────

    @staticmethod
    def _match_list(data_item: dict, condition: dict, global_context: Optional[dict] = None) -> bool:
        """黑名单匹配.

        Condition 格式: {"field": "remote_address", "values": ["1.2.3.4", "5.6.7.8"], "match_mode": "exact"}

        动态 IOC 引用：若 condition.field 命中 FIELD_TO_IOC_TYPE 映射，则额外把
        global_context["iocs_by_type"][对应类型] 中 enabled=1 的指标并入待匹配集合
        （与 rule.condition.values 取并集）。iocs 表为空或该类型无数据时仅匹配 values，
        完全向后兼容。不修改原始 condition.values。
        """
        field = condition.get("field", "")
        base_values = condition.get("values") or []
        if not isinstance(base_values, list):
            base_values = [base_values]
        match_mode = condition.get("match_mode", "exact")

        # ── 合并 iocs 表动态指标（与 values 取并集）─────────────────
        merged_values: list = list(base_values)
        if global_context:
            iocs_by_type = global_context.get("iocs_by_type") or {}
            if iocs_by_type:
                ioc_type = FIELD_TO_IOC_TYPE.get(field)
                if ioc_type and ioc_type in iocs_by_type:
                    dyn = iocs_by_type[ioc_type]
                    if dyn:
                        merged_values = merged_values + list(dyn)

        value = data_item.get(field, "")
        if not value or not merged_values:
            return False

        value_str = str(value).lower()
        for v in merged_values:
            v_str = str(v).lower()
            if match_mode == "exact":
                if value_str == v_str:
                    RuleEngine._record_ti_hit(global_context, v_str, data_item)
                    return True
            elif match_mode == "contains":
                if v_str in value_str:
                    RuleEngine._record_ti_hit(global_context, v_str, data_item)
                    return True
            elif match_mode == "startswith":
                if value_str.startswith(v_str):
                    RuleEngine._record_ti_hit(global_context, v_str, data_item)
                    return True
        return False

    # ── 阈值匹配 ────────────────────────────────────────────────────────

    @staticmethod
    def _match_threshold(data_item: dict, condition: dict) -> bool:
        """阈值检测.

        Condition 格式: {"field": "connection_count", "operator": ">", "value": 50}
        """
        field = condition.get("field", "")
        operator = condition.get("operator", ">")
        threshold_value = condition.get("value", 0)

        value = data_item.get(field, 0)
        try:
            value = float(value)
        except (ValueError, TypeError):
            return False

        if operator == ">":
            return value > threshold_value
        elif operator == ">=":
            return value >= threshold_value
        elif operator == "<":
            return value < threshold_value
        elif operator == "<=":
            return value <= threshold_value
        elif operator == "==":
            return value == threshold_value
        elif operator == "!=":
            return value != threshold_value
        return False

    # ── 存在性检查 ──────────────────────────────────────────────────────

    @staticmethod
    def _match_exists(data_item: dict, condition: dict) -> bool:
        """检查字段是否存在且非空.

        Condition 格式: {"field": "remote_address"}

        Args:
            data_item: 数据项字典.
            condition: 条件字典，必须包含 field 字段.

        Returns:
            字段存在且非空返回 True.
        """
        field = condition.get("field", "")
        if not field:
            return False
        value = data_item.get(field)
        if value is None:
            return False
        if isinstance(value, str) and value.strip() == "":
            return False
        if isinstance(value, (list, dict)) and len(value) == 0:
            return False
        return True

    # ── 组合条件匹配 ──────────────────────────────────────────────────────

    @staticmethod
    def _match_composite(data_item: dict, condition: dict, global_context: Optional[dict] = None) -> bool:
        """组合条件匹配 — 支持 AND/OR 逻辑递归求值.

        Condition 格式::

            {
                "logic": "AND",
                "sub_rules": [
                    {"type": "regex", "field": "command_line", "pattern": "mimikatz"},
                    {"type": "exists", "field": "remote_address"}
                ]
            }

        子规则支持任意嵌套深度，type 可以是:
        regex, list, threshold, behavior, composite, exists

        Args:
            data_item: 数据项字典.
            condition: 组合条件字典.

        Returns:
            组合匹配结果.
        """
        logic = condition.get("logic", "AND").upper()
        sub_rules = condition.get("sub_rules", [])

        if not sub_rules:
            return False

        results: list[bool] = []
        for sub in sub_rules:
            sub_type = sub.get("type", "")
            try:
                if sub_type == "regex":
                    results.append(RuleEngine._match_regex(data_item, sub))
                elif sub_type == "list":
                    results.append(RuleEngine._match_list(data_item, sub, global_context=global_context))
                elif sub_type == "threshold":
                    results.append(RuleEngine._match_threshold(data_item, sub))
                elif sub_type == "behavior":
                    results.append(RuleEngine._match_behavior(data_item, sub, global_context=global_context))
                elif sub_type == "composite":
                    results.append(RuleEngine._match_composite(data_item, sub, global_context=global_context))
                elif sub_type == "exists":
                    results.append(RuleEngine._match_exists(data_item, sub))
                else:
                    logger.warning("Unknown sub_rule type: %s", sub_type)
                    results.append(False)
            except Exception as exc:
                logger.warning(
                    "Error evaluating sub_rule type=%s: %s", sub_type, exc
                )
                results.append(False)

        if logic == "AND":
            return all(results)
        elif logic == "OR":
            return any(results)
        else:
            logger.warning("Unknown composite logic: %s", logic)
            return False

    # ── 行为模式检测 ──────────────────────────────────────────────────────

    @staticmethod
    def _match_behavior(data_item: dict, condition: dict, global_context: Optional[dict] = None) -> bool:
        """行为模式检测.

        Condition 格式: {"pattern": "orphan_process", "description": "..."}

        支持 20 种行为模式:

        ======================= ==========================================
        模式名                   说明
        ======================= ==========================================
        orphan_process          无父进程或父进程已退出
        suspicious_parent       可疑父进程启动脚本解释器
        unsigned_process        非系统目录进程
        network_scan            网络扫描行为
        credential_dump         凭据导出 (LSASS/SAM)
        uac_bypass              UAC 绕过
        token_manipulation      Token 操作
        antivirus_tamper        杀软干扰/禁用
        defense_evasion         日志清除/时间戳篡改
        lateral_movement        横向移动
        data_exfil              数据外传
        webshell_activity       WebShell 特征
        ransomware_behavior     勒索软件行为
        persistence_wmi         WMI 持久化
        persistence_com_hijack  COM 劫持持久化
        discovery_recon         系统信息探测
        dll_sideload            DLL 侧加载
        process_chain           进程链攻击路径
        time_cluster            时间聚类异常
        short_lived             短存活 Shell 进程
        ======================= ==========================================
        """
        pattern: str = condition.get("pattern", "")

        # ── 原有 4 个模式 ──────────────────────────────────────────
        if pattern == "orphan_process":
            ppid = data_item.get("ppid", 0)
            return ppid == 0 or ppid is None

        elif pattern == "suspicious_parent":
            parent_name = str(data_item.get("parent_name", "")).lower()
            child_name = str(data_item.get("name", "")).lower()
            suspicious_parents = [
                "winword.exe", "excel.exe", "powerpnt.exe", "outlook.exe",
            ]
            suspicious_children = [
                "powershell.exe", "cmd.exe", "wscript.exe", "cscript.exe",
            ]
            return (
                parent_name in suspicious_parents
                and child_name in suspicious_children
            )

        elif pattern == "unsigned_process":
            path = str(data_item.get("path", "")).lower()
            system_dirs = [
                "c:\\windows\\system32",
                "c:\\windows\\syswow64",
                "/usr/bin",
                "/usr/sbin",
            ]
            return path and not any(d in path for d in system_dirs)

        elif pattern == "network_scan":
            connections = data_item.get("connections", [])
            if isinstance(connections, list):
                unique_ips: set[str] = set()
                for conn in connections:
                    remote = conn.get("remote_address", "")
                    if remote:
                        unique_ips.add(remote)
                return len(unique_ips) > 20
            return False

        # ── 凭据导出: LSASS/SAM dump ─────────────────────────────
        elif pattern == "credential_dump":
            name = str(data_item.get("name", "")).lower()
            cmd = str(data_item.get("command_line", "")).lower()
            # LSASS dump tools
            lsass_tools = [
                "procdump", "mimikatz", "lsass", "sqldumper",
                "comsvcs.dll", "rundll32.exe",
            ]
            for tool in lsass_tools:
                if tool in name or tool in cmd:
                    return True
            # SAM / SYSTEM hive access
            sam_keywords = [
                "sam", "system", "security",
                "hklm\\sam", "hklm\\security",
                "reg save", "ntds.dit",
            ]
            if any(kw in cmd for kw in sam_keywords):
                return True
            return False

        # ── UAC 绕过 ──────────────────────────────────────────────
        elif pattern == "uac_bypass":
            cmd = str(data_item.get("command_line", "")).lower()
            path = str(data_item.get("path", "")).lower()
            uac_indicators = [
                "fodhelper.exe", "computerdefaults.exe",
                "eventvwr.exe", "sdclt.exe",
                "slui.exe", "winsat.exe",
                "wsreset.exe", "cmstp.exe",
                "hkcu\\software\\classes\\ms-settings",
                "shell\\open\\command",
            ]
            for indicator in uac_indicators:
                if indicator in cmd or indicator in path:
                    return True
            return False

        # ── Token 操作 ────────────────────────────────────────────
        elif pattern == "token_manipulation":
            name = str(data_item.get("name", "")).lower()
            cmd = str(data_item.get("command_line", "")).lower()
            token_indicators = [
                "runas", "seclogon", "token",
                "duplicate", "impersonate",
                "adjusttokenprivileges",
                "openprocesstoken",
            ]
            for indicator in token_indicators:
                if indicator in name or indicator in cmd:
                    return True
            return False

        # ── 杀软干扰/禁用 ─────────────────────────────────────────
        elif pattern == "antivirus_tamper":
            cmd = str(data_item.get("command_line", "")).lower()
            name = str(data_item.get("name", "")).lower()
            av_tamper_indicators = [
                "sc stop", "sc config", "net stop",
                "taskkill", "stop-service",
                "set-service", "disable",
                "windefend", "mssense", "msmpeng",
                "securityhealthservice",
                "sophos", "mcafee", "symantec",
                "trend", "kaspersky", "eset",
                "avast", "avg", "bitdefender",
                "carbonblack", "crowdstrike",
                "sentinelone", "cylance",
            ]
            cmd_and_name = cmd + " " + name
            for indicator in av_tamper_indicators:
                if indicator in cmd_and_name:
                    return True
            return False

        # ── 防御规避: 日志清除 / 时间戳篡改 ───────────────────────
        elif pattern == "defense_evasion":
            cmd = str(data_item.get("command_line", "")).lower()
            evasion_indicators = [
                "wevtutil cl", "wevtutil clear-log",
                "clearlog", "clear-eventlog",
                "remove-item", "del /f",
                "fsutil behavior set disablelastaccess",
                "fsutil usn deletejournal",
                "auditpol /clear",
                "vssadmin delete shadows",
                "wbadmin delete catalog",
                "bcdedit /set safeboot",
                "bcdedit /set {default} recoveryenabled",
                "timestomp",
                "setfiletime",
            ]
            for indicator in evasion_indicators:
                if indicator in cmd:
                    return True
            # 检查是否在操作 EventLog 或安全日志文件
            log_targets = [
                "security.evtx", "system.evtx",
                "application.evtx", "winevt",
            ]
            for target in log_targets:
                if target in cmd:
                    return True
            return False

        # ── 横向移动 ──────────────────────────────────────────────
        elif pattern == "lateral_movement":
            cmd = str(data_item.get("command_line", "")).lower()
            name = str(data_item.get("name", "")).lower()
            lateral_indicators = [
                "psexec", "psexesvc",
                "wmic /node:", "wmic /user:",
                "schtasks /create /s",
                "schtasks /run /s",
                "winrm", "invoke-command",
                "enter-pssession",
                "new-pssession",
                "copy-item -tosession",
                "net use \\\\", "net use * \\\\",
                "xcopy \\\\", "robocopy \\\\",
                "mapping \\\\",
                "at \\\\",
            ]
            for indicator in lateral_indicators:
                if indicator in cmd:
                    return True
            # WMI 远程执行特征
            wmi_remote = [
                ("wmic.exe" in name or "wmiprvse.exe" in name),
                ("/node:" in cmd),
            ]
            if all(wmi_remote):
                return True
            return False

        # ── 数据外传 ──────────────────────────────────────────────
        elif pattern == "data_exfil":
            cmd = str(data_item.get("command_line", "")).lower()
            exfil_indicators = [
                # 压缩工具
                "7z", "winrar", "rar.exe",
                "makecab", "compact",
                "compress-archive",
                "zip", "gzip", "tar",
                # 上传工具
                "curl", "wget", "ftp",
                "nc ", "netcat",
                "invoke-webrequest",
                "invoke-restmethod",
                "bitsadmin",
                "scp", "rsync",
                "megacmd", "rclone",
            ]
            has_compress = False
            has_upload = False
            compress_keywords = [
                "7z", "winrar", "rar.exe", "makecab", "compact",
                "compress-archive", "zip", "gzip", "tar",
            ]
            upload_keywords = [
                "curl", "wget", "ftp", "nc ", "netcat",
                "invoke-webrequest", "invoke-restmethod",
                "bitsadmin", "scp", "rsync", "megacmd", "rclone",
            ]
            for kw in compress_keywords:
                if kw in cmd:
                    has_compress = True
                    break
            for kw in upload_keywords:
                if kw in cmd:
                    has_upload = True
                    break
            # 同时包含压缩和上传 → 外传
            return has_compress and has_upload

        # ── WebShell 特征 ─────────────────────────────────────────
        elif pattern == "webshell_activity":
            cmd = str(data_item.get("command_line", "")).lower()
            name = str(data_item.get("name", "")).lower()
            webshell_indicators = [
                "eval(", "system(", "exec(",
                "shell_exec", "passthru",
                "proc_open", "popen",
                "base64_decode",
                "assert(",
                "create_function",
                "preg_replace",
                "cmd.exe", "powershell.exe",
                "whoami", "ipconfig",
                "net user", "net localgroup",
            ]
            # 只有在 Web 服务器进程上下文中才报警
            web_servers = [
                "w3wp.exe", "httpd.exe", "apache",
                "nginx", "node.exe", "java",
                "tomcat", "php-cgi", "php",
            ]
            is_web_process = any(ws in name for ws in web_servers)
            if not is_web_process:
                return False
            match_count = 0
            for indicator in webshell_indicators:
                if indicator in cmd:
                    match_count += 1
            return match_count >= 2

        # ── 勒索软件行为 ──────────────────────────────────────────
        elif pattern == "ransomware_behavior":
            cmd = str(data_item.get("command_line", "")).lower()
            name = str(data_item.get("name", "")).lower()
            # 删除卷影副本
            shadow_del = any(k in cmd for k in [
                "vssadmin delete shadows",
                "wmic shadowcopy delete",
                "vssadmin resize shadowstorage",
            ])
            # 批量加密 / 重命名
            encrypt_indicators = [
                "cipher /e", "gpg", "openssl enc",
                "rename-item", "ren *",
                ".encrypted", ".lock", ".crypt",
                ".crab", ".zepto", ".cerber",
                ".locky", ".wannacry",
            ]
            has_encrypt = any(k in cmd for k in encrypt_indicators)
            # 禁用恢复选项
            recovery_disable = any(k in cmd for k in [
                "bcdedit /set {default} recoveryenabled no",
                "bcdedit /set {default} bootstatuspolicy ignoreallfailures",
                "wbadmin delete systemstatebackup",
            ])
            return shadow_del or (has_encrypt and recovery_disable) or has_encrypt

        # ── WMI 持久化 ────────────────────────────────────────────
        elif pattern == "persistence_wmi":
            cmd = str(data_item.get("command_line", "")).lower()
            name = str(data_item.get("name", "")).lower()
            wmi_persist_indicators = [
                "__eventfilter", "__filtertoconsumerbinding",
                "__eventconsumer", "commandlineeventconsumer",
                "activeScriptEventconsumer",
                "set-wmiinstance",
                "register-wmievent",
                "wmi-event", "wmi permanent",
                "root\\subscription",
            ]
            for indicator in wmi_persist_indicators:
                if indicator in cmd or indicator in name:
                    return True
            return False

        # ── COM 劫持持久化 ────────────────────────────────────────
        elif pattern == "persistence_com_hijack":
            cmd = str(data_item.get("command_line", "")).lower()
            com_hijack_indicators = [
                "hkey_classes_root\\clsid",
                "hkey_current_user\\software\\classes\\clsid",
                "inprocserver32",
                "localserver32",
                "treatas",
                "com hijack", "comhijack",
                "oleview",
                "dcomcnfg",
            ]
            for indicator in com_hijack_indicators:
                if indicator in cmd:
                    return True
            return False

        # ── 系统信息探测 ──────────────────────────────────────────
        elif pattern == "discovery_recon":
            cmd = str(data_item.get("command_line", "")).lower()
            recon_commands: list[str] = [
                "systeminfo", "hostname",
                "whoami", "whoami /priv",
                "whoami /groups", "net user",
                "net localgroup", "net group",
                "net share", "net view",
                "net session", "netstat",
                "ipconfig", "ipconfig /all",
                "arp -a", "route print",
                "nslookup", "tracert",
                "tasklist", "tasklist /v",
                "quser", "qwinsta",
                "query user", "query session",
                "dsquery", "net accounts",
                "net domain", "nltest",
                "gpresult", "set",
                "dir /s", "tree /f",
                "wmic product get",
                "wmic qfe", "wmic os get",
                "wmic service get",
                "wmic share get",
                "get-wmiobject",
                "get-process",
                "get-service",
                "get-hotfix",
            ]
            # 如果命令行匹配到 ≥3 个侦察命令 → 高度可疑
            match_count = sum(1 for rc in recon_commands if rc in cmd)
            return match_count >= 3

        # ── DLL 侧加载 ────────────────────────────────────────────
        elif pattern == "dll_sideload":
            path = str(data_item.get("path", "")).lower()
            name = str(data_item.get("name", "")).lower()
            cmd = str(data_item.get("command_line", "")).lower()
            # DLL 侧加载特征: 应用程序从非标准目录加载 DLL
            dll_sideload_indicators: list[str] = [
                "version.dll", "dwrite.dll", "vcruntime140.dll",
                "propsys.dll", "userenv.dll", "duser.dll",
                "mpr.dll", "cscapi.dll", "dbghelp.dll",
                "winshlext", "dwmapi.dll",
            ]
            # 应用在非系统目录运行且加载了常见侧加载 DLL
            system_dirs = [
                "c:\\windows\\system32",
                "c:\\windows\\syswow64",
            ]
            is_non_system = path and not any(d in path for d in system_dirs)
            if not is_non_system:
                return False
            for dll in dll_sideload_indicators:
                if dll in cmd or dll in path:
                    return True
            return False

        # ── 新增模式: process_chain 进程链攻击路径 ────────────────
        elif pattern == "process_chain":
            return RuleEngine._match_process_chain(data_item, condition, global_context)

        # ── 新增模式: time_cluster 时间聚类异常 ──────────────────
        elif pattern == "time_cluster":
            return RuleEngine._match_time_cluster(data_item, condition, global_context)

        # ── 新增模式: short_lived 短存活 Shell ────────────────────
        elif pattern == "short_lived":
            return RuleEngine._match_short_lived(data_item, condition)

        # ── 未知模式 ──────────────────────────────────────────────
        logger.warning("Unknown behavior pattern: %s", pattern)
        return False

    # ── 进程链攻击路径检测 ──────────────────────────────────────────────

    @staticmethod
    def _match_process_chain(data_item: dict, condition: dict, global_context: Optional[dict] = None) -> bool:
        """检测 ≥min_chain_length 级可疑进程链路（攻击路径）.

        从 global_context 获取 process_map（pid→process dict），从当前进程回溯父链，
        检测链路中 ≥min_chain_length 个进程属于 suspicious_patterns。
        需要同时在链路起点有 suspicious_parent 和链路中间有 suspicious_child。

        Args:
            data_item: 当前进程数据项.
            condition: 规则条件，包含 min_chain_length, suspicious_parent_patterns, suspicious_child_patterns.
            global_context: 全局上下文，需包含 process_map（pid→process dict）.

        Returns:
            是否检测到进程链攻击.
        """
        if not global_context:
            return False

        process_map: dict = global_context.get("process_map", {})
        if not process_map:
            return False

        min_chain_length: int = condition.get("min_chain_length", 3)
        suspicious_parent_patterns: list = condition.get("suspicious_parent_patterns", [])
        suspicious_child_patterns: list = condition.get("suspicious_child_patterns", [])

        # 从当前进程回溯父链
        chain: list[dict] = []
        current_pid = data_item.get("pid")

        # 向上回溯父进程链（最多 10 层防止无限循环）
        max_depth = 10
        visited_pids: set = set()
        pid = current_pid
        while pid is not None and pid not in visited_pids and max_depth > 0:
            proc = process_map.get(pid)
            if proc is None:
                break
            visited_pids.add(pid)
            chain.append(proc)
            pid = proc.get("ppid")
            max_depth -= 1

        # 链路长度不足
        if len(chain) < min_chain_length:
            return False

        # 检查链路中可疑进程数量
        suspicious_count = 0
        has_suspicious_parent = False
        has_suspicious_child = False

        for proc in chain:
            proc_name = str(proc.get("name", "")).lower()
            if any(p.lower() in proc_name for p in suspicious_parent_patterns):
                has_suspicious_parent = True
                suspicious_count += 1
            if any(p.lower() in proc_name for p in suspicious_child_patterns):
                has_suspicious_child = True
                suspicious_count += 1

        # 需要同时有可疑父进程和可疑子进程
        if not has_suspicious_parent or not has_suspicious_child:
            return False

        if suspicious_count >= min_chain_length:
            # 记录攻击路径到 data_item 中，用于后续 _apply_accumulated_scoring
            attack_path_names = [str(p.get("name", "")) for p in chain]
            data_item["_attack_path"] = " → ".join(attack_path_names)
            return True

        return False

    # ── 时间聚类异常检测 ──────────────────────────────────────────────

    @staticmethod
    def _match_time_cluster(data_item: dict, condition: dict, global_context: Optional[dict] = None) -> bool:
        """同一时间窗口内 ≥min_count 个进程启动触发告警.

        从 global_context 获取 all_items（所有进程列表），对 data_item 的 start_time，
        检查同一时间窗口（window_minutes）内有 ≥min_count 个进程启动。

        Args:
            data_item: 当前进程数据项.
            condition: 规则条件，包含 window_minutes, min_count.
            global_context: 全局上下文，需包含 all_items（所有进程列表）.

        Returns:
            是否检测到时间聚类异常.
        """
        if not global_context:
            return False

        all_items: list = global_context.get("all_items", [])
        if not all_items:
            return False

        window_minutes: int = condition.get("window_minutes", 5)
        min_count: int = condition.get("min_count", 5)

        current_start_time = data_item.get("start_time", "")
        if not current_start_time:
            return False

        # 解析当前进程的 start_time
        try:
            from datetime import datetime, timedelta
            # 支持多种常见时间格式
            time_formats = [
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M:%S.%f",
                "%Y-%m-%dT%H:%M:%S.%f",
                "%Y/%m/%d %H:%M:%S",
            ]
            current_time = None
            for fmt in time_formats:
                try:
                    current_time = datetime.strptime(str(current_start_time).split("+")[0].split("Z")[0], fmt)
                    break
                except ValueError:
                    continue
            if current_time is None:
                return False

            window_start = current_time - timedelta(minutes=window_minutes)
            window_end = current_time + timedelta(minutes=window_minutes)

            # T-P2-4: 优先使用预排序列表 + 二分计数，将 O(n²) 降至 O(n log n)
            dts = global_context.get("_tc_dts")
            if dts:
                import bisect

                lo = bisect.bisect_left(dts, window_start)
                hi = bisect.bisect_right(dts, window_end)
                return (hi - lo) >= min_count

            # 回退：未预排序时线性扫描（保持旧逻辑兼容）
            count_in_window = 0
            for item in all_items:
                if not isinstance(item, dict):
                    continue
                item_start_time = item.get("start_time", "")
                if not item_start_time:
                    continue
                item_time = None
                for fmt in time_formats:
                    try:
                        item_time = datetime.strptime(str(item_start_time).split("+")[0].split("Z")[0], fmt)
                        break
                    except ValueError:
                        continue
                if item_time and window_start <= item_time <= window_end:
                    count_in_window += 1

            return count_in_window >= min_count
        except Exception as exc:
            logger.warning("Error in time_cluster detection: %s", exc)
            return False

    # ── 短存活 Shell 进程检测 ──────────────────────────────────────────

    @staticmethod
    def _match_short_lived(data_item: dict, condition: dict) -> bool:
        """powershell/cmd 进程存活时间 < max_alive_seconds 触发告警.

        检查 data_item.name 是否在 target_processes 中，
        如果 threads=0 或进程存活时间 < max_alive_seconds，判断为短存活进程。

        Args:
            data_item: 当前进程数据项.
            condition: 规则条件，包含 target_processes, max_alive_seconds.

        Returns:
            是否检测到短存活 Shell.
        """
        target_processes: list = condition.get("target_processes", [])
        max_alive_seconds: int = condition.get("max_alive_seconds", 30)

        proc_name = str(data_item.get("name", "")).lower()
        # 检查是否为目标进程
        is_target = any(t.lower() == proc_name for t in target_processes)
        if not is_target:
            return False

        # 检查 threads=0（进程已退出）
        threads = data_item.get("threads", 0)
        if threads == 0:
            return True

        # 检查存活时间 < max_alive_seconds
        start_time_str = data_item.get("start_time", "")
        if start_time_str:
            try:
                from datetime import datetime
                time_formats = [
                    "%Y-%m-%d %H:%M:%S",
                    "%Y-%m-%dT%H:%M:%S",
                    "%Y-%m-%d %H:%M:%S.%f",
                    "%Y-%m-%dT%H:%M:%S.%f",
                    "%Y/%m/%d %H:%M:%S",
                ]
                start_time = None
                for fmt in time_formats:
                    try:
                        start_time = datetime.strptime(str(start_time_str).split("+")[0].split("Z")[0], fmt)
                        break
                    except ValueError:
                        continue
                if start_time:
                    elapsed = (datetime.now() - start_time).total_seconds()
                    if elapsed < max_alive_seconds and threads <= 1:
                        return True
            except Exception:
                pass

        return False

    # ── 攻击链关联检测（主机级）─────────────────────────────────────────

    @staticmethod
    def _build_host_events(global_context: Optional[dict]) -> list:
        """按 host_id 聚合各维度取证数据为统一时间线事件列表.

        每个事件结构::

            {"dimension": "process"|"connection"|"registry"|"persistence"|"timeline"|"ioc",
             "timestamp": Optional[datetime],   # 无可信时间戳的维度为 None（退化为「仅顺序」）
             "data": dict}                       # 原始记录字段，供 step.match 直接命中

        时间戳来源（最高优先级优先）：
          - timeline    → timestamp
          - registry    → last_write_time（退化到 collected_at）
          - process/connection/persistence/ioc → 无可靠时间戳，置 None（仅顺序匹配）

        返回前按 timestamp 升序排序；无时间戳事件统一置于末尾，保证跨维度顺序贪心可用。

        Args:
            global_context: 全局上下文，须含 host_id。

        Returns:
            统一事件列表（已排序）。任何 DB 异常均降级为空列表。
        """
        if not global_context:
            return []
        host_id = global_context.get("host_id")
        if host_id is None:
            return []

        from datetime import datetime  # 供 _sort_key 兜底排序（datetime.min）使用

        def _parse_ts(value) -> Optional["__import__('datetime').datetime"]:
            from datetime import datetime
            if not value:
                return None
            s = str(value).split("+")[0].split("Z")[0]
            for fmt in (
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M:%S.%f",
                "%Y-%m-%dT%H:%M:%S.%f",
                "%Y/%m/%d %H:%M:%S",
            ):
                try:
                    return datetime.strptime(s, fmt)
                except ValueError:
                    continue
            return None

        events: list = []
        try:
            from app.models.analysis import (
                AbnormalProcess, SuspiciousConnection, PersistenceItem,
                TimelineEvent, IocHit, RegistryKey,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("跳过攻击链事件聚合（analysis 模型不可用）: %s", exc)
            return []

        try:
            # 进程（无可靠时间戳）
            for r in AbnormalProcess.list_by_host(host_id):
                events.append({"dimension": "process", "timestamp": None, "data": dict(r)})
            # 可疑外连（无可靠时间戳；兼容 network_connections 的 remote_addr 别名）
            for r in SuspiciousConnection.list_by_host(host_id):
                d = dict(r)
                if "remote_address" not in d and d.get("remote_addr") is not None:
                    d["remote_address"] = d["remote_addr"]
                events.append({"dimension": "connection", "timestamp": None, "data": d})
            # 持久化痕迹（无可靠时间戳）
            for r in PersistenceItem.list_by_host(host_id):
                events.append({"dimension": "persistence", "timestamp": None, "data": dict(r)})
            # IOC 命中（无可靠时间戳）
            for r in IocHit.list_by_host(host_id):
                events.append({"dimension": "ioc", "timestamp": None, "data": dict(r)})
            # 注册表（last_write_time 退化到 collected_at）
            for r in RegistryKey.list_by_host(host_id):
                d = dict(r)
                ts = _parse_ts(d.get("last_write_time")) or _parse_ts(d.get("collected_at"))
                events.append({"dimension": "registry", "timestamp": ts, "data": d})
            # 时间线（timestamp 可信）
            for r in TimelineEvent.list_by_host(host_id):
                events.append({
                    "dimension": "timeline",
                    "timestamp": _parse_ts(r.get("timestamp")),
                    "data": dict(r),
                })
        except Exception as exc:  # noqa: BLE001
            logger.debug("攻击链事件聚合部分失败，降级为空: %s", exc)
            return []

        # 排序：有时间戳在前（升序），无时间戳（None）置于末尾
        def _sort_key(e):
            ts = e.get("timestamp")
            return (ts is None, ts if ts is not None else datetime.min)

        events.sort(key=_sort_key)
        return events

    @staticmethod
    def _match_attack_chain_step(step: dict, event_data: dict,
                                 global_context: Optional[dict] = None) -> bool:
        """对单条统一事件应用攻击链某步的 match 条件.

        step.match.type ∈ {regex, list, threshold, behavior, exists, composite}，
        直接复用引擎既有 _match_* 实现，保证语义一致。

        Args:
            step: ordered_steps 中的单步（含 dimension + match）。
            event_data: 统一事件的 data 字典。
            global_context: 全局上下文（透传给 composite/behavior/threshold）。

        Returns:
            该步是否命中此事件。
        """
        match = step.get("match", {})
        if not isinstance(match, dict):
            return False
        mtype = match.get("type", "")
        if mtype == "regex":
            return RuleEngine._match_regex(event_data, match)
        elif mtype == "list":
            return RuleEngine._match_list(event_data, match, global_context=global_context)
        elif mtype == "threshold":
            return RuleEngine._match_threshold(event_data, match)
        elif mtype == "exists":
            return RuleEngine._match_exists(event_data, match)
        elif mtype == "composite":
            return RuleEngine._match_composite(event_data, match, global_context=global_context)
        elif mtype == "behavior":
            return RuleEngine._match_behavior(event_data, match, global_context=global_context)
        logger.warning("Unknown attack_chain step match.type: %s", mtype)
        return False

    @staticmethod
    def _match_attack_chain(rule: dict, global_context: Optional[dict] = None,
                            host_events: Optional[list] = None) -> Optional[dict]:
        """主机级攻击链贪心顺序匹配 + 时间窗判定.

        算法：
          1. 按 ordered_steps 顺序，在「按时间升序」的统一事件列表中贪心选取：
             每步须找到 dimension 匹配且 _match_attack_chain_step 命中、且位于上一步
             索引之后（保证顺序）的首个事件。
          2. 所有步骤命中后，对「具有时间戳的步骤事件」计算首末跨度 span；
             若 span > window_minutes，则视为超窗不命中（无时间戳步骤不参与时间约束）。

        Args:
            rule: attack_chain 规则字典（condition 含 ordered_steps / window_minutes）。
            global_context: 全局上下文（用于下钻构建事件、透传 IOC 等）。
            host_events: 可选预构建事件列表（单元测试可直接注入，跳过 DB 下钻）。

        Returns:
            命中返回 {"steps": [...明细...], "reason": str}；否则返回 None。
        """
        if not global_context:
            global_context = {}
        condition = rule.get("condition", {})
        if isinstance(condition, str):
            try:
                condition = json.loads(condition)
            except json.JSONDecodeError:
                return None
        steps = condition.get("ordered_steps") or []
        if not steps:
            return None
        window_minutes = int(condition.get("window_minutes", 60) or 60)
        # 防御：window_minutes 上限 1440（与设计校验一致）
        window_minutes = max(1, min(window_minutes, 1440))

        if host_events is None:
            host_events = RuleEngine._build_host_events(global_context)
        if not host_events:
            return None

        matched_times: list = []
        matched_steps: list = []
        pointer = 0
        for idx, step in enumerate(steps):
            dim = step.get("dimension")
            found = False
            for j in range(pointer, len(host_events)):
                ev = host_events[j]
                if ev.get("dimension") != dim:
                    continue
                if not RuleEngine._match_attack_chain_step(step, ev.get("data", {}), global_context):
                    continue
                # 命中：记录
                ts = ev.get("timestamp")
                if ts is not None:
                    matched_times.append(ts)
                matched_steps.append({
                    "step": idx + 1,
                    "dimension": dim,
                    "match": step.get("match"),
                    "summary": RuleEngine._summarize_event(ev),
                })
                pointer = j + 1
                found = True
                break
            if not found:
                return None

        # 时间窗判定：仅在「有 ≥1 个带时间戳步骤」时生效
        if len(matched_times) >= 2:
            from datetime import timedelta
            span = (max(matched_times) - min(matched_times)).total_seconds() / 60.0
            if span > window_minutes:
                return None

        reason = (
            f"规则 '{rule.get('name', '')}' 命中攻击链关联："
            + " → ".join(
                f"[步骤{s['step']}:{s['dimension']}] {s['summary']}" for s in matched_steps
            )
        )
        return {"steps": matched_steps, "reason": reason}

    @staticmethod
    def _summarize_event(ev: dict) -> str:
        """为攻击链命中步骤生成简短摘要（用于 reason 展示）."""
        dim = ev.get("dimension")
        data = ev.get("data", {}) or {}
        if dim == "process":
            return f"进程 {data.get('process_name', '?')} cmd={str(data.get('command_line', ''))[:60]}"
        if dim == "connection":
            return f"外连 {data.get('remote_address', '?')}:{data.get('remote_port', '?')}"
        if dim == "registry":
            return f"注册表 {data.get('key_path', '?')}"
        if dim == "persistence":
            return f"持久化 {data.get('type', '?')}/{data.get('name', '?')}"
        if dim == "ioc":
            return f"IOC {data.get('ioc_type', '?')}={data.get('ioc_value', '?')}"
        if dim == "timeline":
            return f"时间线 {data.get('event_type', '?')}:{str(data.get('description', ''))[:60]}"
        return dim or "?"

    # ── 原因构建 ────────────────────────────────────────────────────────

    @staticmethod
    def _build_reason(data_item: dict, rule: dict) -> str:
        """构建规则命中原因说明."""
        rule_name = rule.get("name", "")
        description = rule.get("description", "")
        rule_type = rule.get("rule_type", "")
        condition = rule.get("condition", {})
        if isinstance(condition, str):
            try:
                condition = json.loads(condition)
            except json.JSONDecodeError:
                condition = {}

        if rule_type == "composite":
            return f"规则 '{rule_name}' 命中 (组合条件) — {description}"

        field = condition.get("field", "")
        value = data_item.get(field, "")
        if value:
            return (
                f"规则 '{rule_name}' 命中: "
                f"字段 '{field}' 值 '{str(value)[:100]}' — {description}"
            )
        return f"规则 '{rule_name}' 命中 — {description}"
