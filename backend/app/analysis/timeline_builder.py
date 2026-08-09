"""时间线构建器 — 从采集数据提取时间线事件."""

import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


class TimelineBuilder:
    """时间线构建器."""

    # 最小有效年份：早于该年份的时间戳视为脏数据（如 1601/1970 默认值）
    MIN_VALID_YEAR = 2000

    @staticmethod
    def build(raw_data: dict, ioc_hits: Optional[list] = None) -> list:
        """从采集数据构建时间线.

        Args:
            raw_data: Agent JSON 数据.
            ioc_hits: IOC 命中列表（可选），用于关联 ioc_hit_id.

        Returns:
            时间线事件列表（已排序，含 MITRE 战术注入和 IOC 关联）.
        """
        events: list[dict] = []

        # 从进程提取
        events.extend(TimelineBuilder._extract_from_processes(raw_data))

        # 从网络提取
        events.extend(TimelineBuilder._extract_from_network(raw_data))

        # 从日志提取
        events.extend(TimelineBuilder._extract_from_logs(raw_data))

        # 从文件提取
        events.extend(TimelineBuilder._extract_from_files(raw_data))

        # 从浏览器提取
        events.extend(TimelineBuilder._extract_from_browser(raw_data))

        # 从安全事件提取
        events.extend(TimelineBuilder._extract_from_security(raw_data))

        # 从 Agent 原始时间线提取
        agent_timeline = raw_data.get("timeline", [])
        if isinstance(agent_timeline, list):
            for event in agent_timeline:
                if isinstance(event, dict):
                    raw_ts = event.get("timestamp", "")
                    normalized_ts = TimelineBuilder._normalize_timestamp(raw_ts)
                    if normalized_ts:
                        events.append({
                            "timestamp": normalized_ts,
                            "event_type": event.get("event_type", "other"),
                            "source": event.get("source", "agent"),
                            "description": event.get("description", ""),
                            "severity": event.get("severity", "info"),
                            "details": event.get("details", {}),
                        })

        # 排序
        events = TimelineBuilder.sort_events(events)

        # ── V2-5: MITRE 战术自动注入 ──
        for event in events:
            mitre_result = MitreTacticMapper.map(event)
            if mitre_result:
                event["kill_chain_stage"] = mitre_result.get("kill_chain_stage")
                event["mitre_technique_id"] = mitre_result.get("mitre_technique_id")

        # ── V1-6: IOC 关联 ──
        if ioc_hits:
            for event in events:
                for ioc in ioc_hits:
                    if not isinstance(ioc, dict):
                        continue
                    ioc_ctx = ioc.get("context", "") or ""
                    ioc_matched = ioc.get("matched_in", "") or ""
                    evt_desc = event.get("description", "") or ""
                    evt_source = event.get("source", "") or ""
                    # 按 context/matched_in/description 做模糊匹配
                    if (
                        ioc_ctx and evt_desc and (
                            ioc_ctx[:50] in evt_desc
                            or evt_desc[:50] in ioc_ctx
                        )
                    ) or (
                        ioc_matched and evt_source and ioc_matched in evt_source
                    ):
                        event["ioc_hit_id"] = ioc.get("id")
                        break

        return events

    @staticmethod
    def _normalize_timestamp(ts: str) -> str:
        """将各种时间戳格式统一为 ISO 8601 格式 (YYYY-MM-DDTHH:mm:ss).

        支持的输入格式:
          - ISO with T: 2026-07-03T19:25:46.550278
          - ISO with space: 2026-07-06 08:04:50
          - Slash format: 2026/07/06 08:04:50
          - Slash format with T: 2026/07/06T08:04:50

        Args:
            ts: 原始时间戳字符串.

        Returns:
            标准化后的 ISO 8601 时间戳 (YYYY-MM-DDTHH:mm:ss),
            如果无法解析或年份早于 MIN_VALID_YEAR 则返回空字符串.
        """
        if not ts or not isinstance(ts, str):
            return ""

        ts = ts.strip()

        # 尝试多种已知格式解析
        formats = [
            "%Y-%m-%dT%H:%M:%S.%f",    # 2026-07-03T19:25:46.550278
            "%Y-%m-%dT%H:%M:%S",        # 2026-07-03T19:25:46
            "%Y-%m-%d %H:%M:%S.%f",     # 2026-07-06 08:04:50.123456
            "%Y-%m-%d %H:%M:%S",         # 2026-07-06 08:04:50
            "%Y/%m/%dT%H:%M:%S.%f",     # 2026/07/06T08:04:50.123456
            "%Y/%m/%dT%H:%M:%S",         # 2026/07/06T08:04:50
            "%Y/%m/%d %H:%M:%S.%f",     # 2026/07/06 08:04:50.123456
            "%Y/%m/%d %H:%M:%S",         # 2026/07/06 08:04:50
            # 带时区格式（agent 统一时间方案 Phase1-2 输出的新格式）
            "%Y-%m-%dT%H:%M:%S.%f%z",  # 2026-07-27T10:21:47.129+08:00
            "%Y-%m-%dT%H:%M:%S%z",     # 2026-07-27T10:21:47+08:00
            "%Y-%m-%d %H:%M:%S.%f%z",  # 2026-07-27 10:21:47.129+08:00
            "%Y-%m-%d %H:%M:%S%z",     # 2026-07-27 10:21:47+08:00
        ]

        for fmt in formats:
            try:
                dt = datetime.strptime(ts, fmt)
                if dt.year < TimelineBuilder.MIN_VALID_YEAR:
                    logger.warning(
                        "丢弃早于 %d 年的异常时间戳: %s",
                        TimelineBuilder.MIN_VALID_YEAR, ts,
                    )
                    return ""
                return dt.strftime("%Y-%m-%dT%H:%M:%S")
            except ValueError:
                continue

        # 格式均无法匹配，记录警告并返回空字符串
        logger.warning("无法解析时间戳: %s", ts)
        return ""

    @staticmethod
    def sort_events(events: list) -> list:
        """按时间戳排序事件.

        使用标准化后的时间戳进行排序，确保时间顺序正确.

        Args:
            events: 事件列表.

        Returns:
            排序后的事件列表.
        """
        def _parse_sort_key(event: dict) -> datetime:
            """将时间戳解析为 datetime 用于排序比较."""
            ts = event.get("timestamp", "")
            if not ts:
                return datetime.min
            try:
                return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S")
            except ValueError:
                return datetime.min

        return sorted(events, key=_parse_sort_key)

    @staticmethod
    def _extract_from_processes(raw_data: dict) -> list:
        """从进程信息提取时间线事件.

        过滤掉 start_time 为空的事件（如 System Idle Process）,
        并对时间戳进行标准化.
        """
        events = []
        processes = raw_data.get("processes", [])
        if not isinstance(processes, list):
            return events

        for proc in processes:
            if not isinstance(proc, dict):
                continue
            start_time = proc.get("start_time", "")
            normalized_ts = TimelineBuilder._normalize_timestamp(start_time)
            if normalized_ts:
                events.append({
                    "timestamp": normalized_ts,
                    "event_type": "process",
                    "source": "processes",
                    "description": f"进程启动: {proc.get('name', 'unknown')} (PID: {proc.get('pid')})",
                    "severity": "info",
                    "details": {
                        "pid": proc.get("pid"),
                        "ppid": proc.get("ppid"),
                        "path": proc.get("path", ""),
                        "command_line": proc.get("command_line", "")[:200],
                    },
                })
        return events

    @staticmethod
    def _extract_from_network(raw_data: dict) -> list:
        """从网络信息提取时间线事件.

        DNS 缓存没有真实时间戳,不再使用 datetime.now() 伪造时间.
        仅提取有真实时间戳的网络连接事件.
        """
        events = []
        network = raw_data.get("network", {})
        if not isinstance(network, dict):
            return events

        # DNS 缓存 — 无真实时间戳,跳过不提取
        # DNS 缓存条目没有时间信息,无法放入时间线

        # 提取有真实时间戳的网络连接（如有）
        connections = network.get("connections", [])
        if isinstance(connections, list):
            for entry in connections:
                if isinstance(entry, dict):
                    ts_raw = entry.get("timestamp", entry.get("time", ""))
                    normalized_ts = TimelineBuilder._normalize_timestamp(ts_raw)
                    if normalized_ts:
                        events.append({
                            "timestamp": normalized_ts,
                            "event_type": "network",
                            "source": "network.connections",
                            "description": f"网络连接: {entry.get('local_addr', '')} -> {entry.get('remote_addr', '')}",
                            "severity": "info",
                            "details": entry,
                        })
        return events

    @staticmethod
    def _extract_from_logs(raw_data: dict) -> list:
        """从日志提取时间线事件.

        time 为 None/空时不使用 datetime.now() 作为替代,而是跳过该条目.
        对所有时间戳进行标准化.
        """
        events = []
        logs = raw_data.get("logs", {})
        if not isinstance(logs, dict):
            return events

        for log_type in ["system", "security", "application", "syslog"]:
            log_entries = logs.get(log_type, [])
            if not isinstance(log_entries, list):
                continue
            for entry in log_entries:
                if isinstance(entry, dict):
                    time_str = entry.get("time", "")
                    # 不再使用 datetime.now() 替代空时间戳
                    # 空时间戳的日志条目无法放入时间线,跳过
                    normalized_ts = TimelineBuilder._normalize_timestamp(time_str)
                    if normalized_ts:
                        events.append({
                            "timestamp": normalized_ts,
                            "event_type": "log",
                            "source": f"logs.{log_type}",
                            "description": entry.get("description", entry.get("raw", ""))[:200],
                            "severity": "medium" if log_type == "security" else "info",
                            "details": entry,
                        })
        return events

    @staticmethod
    def _extract_from_files(raw_data: dict) -> list:
        """从文件信息提取时间线事件.

        对所有时间戳进行标准化.
        """
        events = []
        files = raw_data.get("files", {})
        if not isinstance(files, dict):
            return events

        recent_files = files.get("recent_files", [])
        if isinstance(recent_files, list):
            for file_info in recent_files:
                if isinstance(file_info, dict):
                    modified = file_info.get("modified", "")
                    normalized_ts = TimelineBuilder._normalize_timestamp(modified)
                    if normalized_ts:
                        events.append({
                            "timestamp": normalized_ts,
                            "event_type": "file",
                            "source": "files.recent",
                            "description": f"文件修改: {file_info.get('path', '')}",
                            "severity": "info",
                            "details": file_info,
                        })

        suspicious = files.get("suspicious_files", [])
        if isinstance(suspicious, list):
            for file_info in suspicious:
                if isinstance(file_info, dict):
                    modified = file_info.get("modified", "")
                    normalized_ts = TimelineBuilder._normalize_timestamp(modified)
                    if normalized_ts:
                        events.append({
                            "timestamp": normalized_ts,
                            "event_type": "file",
                            "source": "files.suspicious",
                            "description": f"可疑文件: {file_info.get('path', '')} — {file_info.get('reason', '')}",
                            "severity": "medium",
                            "details": file_info,
                        })
        return events

    @staticmethod
    def _extract_from_browser(raw_data: dict) -> list:
        """从浏览器痕迹提取时间线事件.

        对所有时间戳进行标准化,将空格分隔的格式转换为 ISO T 格式.
        """
        events = []
        browser = raw_data.get("browser", {})
        if not isinstance(browser, dict):
            return events

        for browser_name in ["chrome", "firefox", "edge", "ie"]:
            browser_data = browser.get(browser_name, {})
            if not isinstance(browser_data, dict):
                continue
            history = browser_data.get("history", [])
            if isinstance(history, list):
                for entry in history:
                    if isinstance(entry, dict):
                        visit_time = entry.get("visit_time", "")
                        normalized_ts = TimelineBuilder._normalize_timestamp(visit_time)
                        if normalized_ts:
                            events.append({
                                "timestamp": normalized_ts,
                                "event_type": "network",
                                "source": f"browser.{browser_name}",
                                "description": f"访问网站: {entry.get('title', entry.get('url', ''))[:100]}",
                                "severity": "info",
                                "details": entry,
                            })
        return events

    @staticmethod
    def _extract_from_security(raw_data: dict) -> list:
        """从安全信息提取时间线事件.

        安全事件摘要(event_ids_summary)没有具体时间戳,
        不再使用 datetime.now() 伪造时间.
        改为从安全日志条目中提取有真实时间的具体事件.
        """
        events = []
        security = raw_data.get("security", {})
        if not isinstance(security, dict):
            return events

        # 从安全日志中提取有真实时间戳的条目（而非摘要统计）
        # 安全日志条目位于 logs.security 中,已在 _extract_from_logs 中处理

        # event_ids_summary 是统计汇总,没有具体时间戳,不提取到时间线

        # 如果 security 中有具体的 event_records（带时间戳的条目）,提取它们
        event_records = security.get("event_records", [])
        if isinstance(event_records, list):
            important_ids = {
                "4624": "登录成功",
                "4625": "登录失败",
                "4648": "使用显式凭据登录",
                "4672": "管理员权限分配",
                "4688": "进程创建",
                "4720": "用户账户创建",
                "4722": "用户账户启用",
                "4724": "密码重置",
                "4732": "成员添加到本地组",
                "4738": "用户账户更改",
            }
            for record in event_records:
                if isinstance(record, dict):
                    ts_raw = record.get("time", record.get("timestamp", ""))
                    normalized_ts = TimelineBuilder._normalize_timestamp(ts_raw)
                    event_id = str(record.get("event_id", ""))
                    if normalized_ts and event_id in important_ids:
                        events.append({
                            "timestamp": normalized_ts,
                            "event_type": "log",
                            "source": "security.events",
                            "description": f"安全事件 {event_id}: {important_ids[event_id]}",
                            "severity": "high" if event_id in ["4625", "4720"] else "medium",
                            "details": {
                                "event_id": event_id,
                                "description": record.get("description", ""),
                            },
                        })
        return events


class MitreTacticMapper:
    """MITRE ATT&CK 战术自动映射器.

    基于事件类型、来源关键字和描述关键字进行三重匹配，
    将事件映射到对应的 Kill Chain 阶段和 MITRE 技术 ID.
    """

    # 规则列表：每条含 event_type / source_kw / description_kw / tactic / technique_id
    # 匹配优先级：规则列表中越靠前越优先
    RULES: list[dict] = [
        # ── 执行 (Execution) ──
        {"event_type": "process", "source_kw": "powershell", "description_kw": "",
         "tactic": "execution", "technique_id": "T1059.001"},
        {"event_type": "process", "source_kw": "cmd", "description_kw": "",
         "tactic": "execution", "technique_id": "T1059.003"},
        {"event_type": "process", "source_kw": "wmic", "description_kw": "",
         "tactic": "execution", "technique_id": "T1047"},
        {"event_type": "process", "source_kw": "wscript", "description_kw": "",
         "tactic": "execution", "technique_id": "T1059.005"},
        {"event_type": "process", "source_kw": "cscript", "description_kw": "",
         "tactic": "execution", "technique_id": "T1059.005"},
        {"event_type": "process", "source_kw": "mshta", "description_kw": "",
         "tactic": "execution", "technique_id": "T1218.005"},

        # ── 持久化 (Persistence) ──
        {"event_type": "file", "source_kw": "startup", "description_kw": "",
         "tactic": "persistence", "technique_id": "T1547.001"},
        {"event_type": "persistence", "source_kw": "", "description_kw": "",
         "tactic": "persistence", "technique_id": "T1547"},
        {"event_type": "log", "source_kw": "", "description_kw": "4732",
         "tactic": "persistence", "technique_id": "T1098"},
        {"event_type": "log", "source_kw": "", "description_kw": "4720",
         "tactic": "persistence", "technique_id": "T1136.001"},

        # ── 凭据访问 (Credential Access) ──
        {"event_type": "log", "source_kw": "", "description_kw": "4625",
         "tactic": "credential_access", "technique_id": "T1110"},
        {"event_type": "log", "source_kw": "", "description_kw": "4648",
         "tactic": "credential_access", "technique_id": "T1078"},
        {"event_type": "log", "source_kw": "", "description_kw": "4672",
         "tactic": "privilege_escalation", "technique_id": "T1068"},
        {"event_type": "process", "source_kw": "mimikatz", "description_kw": "",
         "tactic": "credential_access", "technique_id": "T1003.001"},
        {"event_type": "process", "source_kw": "lsass", "description_kw": "",
         "tactic": "credential_access", "technique_id": "T1003.001"},

        # ── 发现 (Discovery) ──
        {"event_type": "network", "source_kw": "", "description_kw": "port scan",
         "tactic": "discovery", "technique_id": "T1046"},
        {"event_type": "process", "source_kw": "netstat", "description_kw": "",
         "tactic": "discovery", "technique_id": "T1049"},
        {"event_type": "process", "source_kw": "whoami", "description_kw": "",
         "tactic": "discovery", "technique_id": "T1033"},
        {"event_type": "process", "source_kw": "query", "description_kw": "",
         "tactic": "discovery", "technique_id": "T1018"},

        # ── C2 (Command and Control) ──
        {"event_type": "network", "source_kw": "", "description_kw": "C2",
         "tactic": "command_and_control", "technique_id": "T1071"},
        {"event_type": "network", "source_kw": "dns", "description_kw": "",
         "tactic": "command_and_control", "technique_id": "T1071.004"},
        {"event_type": "network", "source_kw": "", "description_kw": "dns",
         "tactic": "command_and_control", "technique_id": "T1071.004"},
        {"event_type": "network", "source_kw": "beacon", "description_kw": "",
         "tactic": "command_and_control", "technique_id": "T1071"},

        # ── 影响 (Impact) ──
        {"event_type": "file", "source_kw": "encrypt", "description_kw": "",
         "tactic": "impact", "technique_id": "T1486"},
        {"event_type": "process", "source_kw": "shutdown", "description_kw": "",
         "tactic": "impact", "technique_id": "T1529"},

        # ── 防御规避 (Defense Evasion) ──
        {"event_type": "process", "source_kw": "taskkill", "description_kw": "",
         "tactic": "defense_evasion", "technique_id": "T1562.001"},
    ]

    @staticmethod
    def map(event: dict) -> Optional[dict]:
        """将事件映射到 MITRE 战术阶段.

        三重匹配策略（按优先级）:
          1. event_type + source_kw 精确匹配
          2. event_type + description_kw 模糊匹配
          3. event_type 仅匹配（兜底）

        Args:
            event: 时间线事件字典，含 event_type / source / description / details.

        Returns:
            含 kill_chain_stage 和 mitre_technique_id 的字典，
            无匹配时返回 None.
        """
        evt_type = (event.get("event_type") or "").lower()
        evt_source = (event.get("source") or "").lower()
        evt_desc = (event.get("description") or "").lower()
        details = event.get("details") or {}
        evt_path = (details.get("path") or "") if isinstance(details, dict) else ""
        evt_cmdline = (details.get("command_line") or "") if isinstance(details, dict) else ""

        # 合并语料：source / description / details.path / details.command_line
        # 进程类事件的 source 恒为 "processes"，关键字只可能出现在描述或命令行中，
        # 因此关键字匹配必须在合并语料上进行，否则 process 类规则永不命中.
        haystack = " ".join([
            evt_source, evt_desc, str(evt_path), str(evt_cmdline),
        ]).lower()

        # 规则按优先级匹配
        for rule in MitreTacticMapper.RULES:
            rule_type = rule.get("event_type", "").lower()
            if rule_type and rule_type != evt_type:
                continue

            source_kw = (rule.get("source_kw") or "").lower()
            desc_kw = (rule.get("description_kw") or "").lower()

            # 三重匹配
            source_match = (not source_kw) or (source_kw in haystack)
            desc_match = (not desc_kw) or (desc_kw in haystack)

            if source_match and desc_match:
                return {
                    "kill_chain_stage": rule["tactic"],
                    "mitre_technique_id": rule["technique_id"],
                }

        return None
