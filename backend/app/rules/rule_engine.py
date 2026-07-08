"""规则引擎核心 — 支持 regex/list/threshold/behavior/composite/exists 六种规则类型."""

import json
import logging
import re
from typing import Any, Optional

from app.models.rule import Rule

logger = logging.getLogger(__name__)

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
    def evaluate(data_items: list, rules: list, global_context: Optional[dict] = None) -> list:
        """对数据项列表执行规则匹配.

        Args:
            data_items: 待检测的数据项列表.
            rules: 规则列表.
            global_context: 全局上下文（可选），包含 process_map 和 all_items 等信息，
                            用于 behavior 模式中需要跨进程数据的检测（如 process_chain/time_cluster）.

        Returns:
            匹配结果列表 [{item, rule, reason}].
        """
        matches = []
        for item in data_items:
            if not isinstance(item, dict):
                continue
            for rule in rules:
                if RuleEngine.match_rule(item, rule, global_context=global_context):
                    matches.append({
                        "item": item,
                        "rule": rule,
                        "rule_name": rule.get("name", ""),
                        "severity": rule.get("severity", "medium"),
                        "reason": RuleEngine._build_reason(item, rule),
                    })
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
            return RuleEngine._match_list(data_item, condition)
        elif rule_type == "threshold":
            return RuleEngine._match_threshold(data_item, condition)
        elif rule_type == "behavior":
            return RuleEngine._match_behavior(data_item, condition, global_context=global_context)
        elif rule_type == "composite":
            return RuleEngine._match_composite(data_item, condition)
        elif rule_type == "exists":
            return RuleEngine._match_exists(data_item, condition)
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
            return bool(re.search(pattern, value, flags))
        except re.error:
            return False

    # ── 列表匹配 ────────────────────────────────────────────────────────

    @staticmethod
    def _match_list(data_item: dict, condition: dict) -> bool:
        """黑名单匹配.

        Condition 格式: {"field": "remote_address", "values": ["1.2.3.4", "5.6.7.8"], "match_mode": "exact"}
        """
        field = condition.get("field", "")
        values = condition.get("values", [])
        match_mode = condition.get("match_mode", "exact")

        value = data_item.get(field, "")
        if not value or not values:
            return False

        value_str = str(value).lower()
        for v in values:
            v_str = str(v).lower()
            if match_mode == "exact":
                if value_str == v_str:
                    return True
            elif match_mode == "contains":
                if v_str in value_str:
                    return True
            elif match_mode == "startswith":
                if value_str.startswith(v_str):
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
    def _match_composite(data_item: dict, condition: dict) -> bool:
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
                    results.append(RuleEngine._match_list(data_item, sub))
                elif sub_type == "threshold":
                    results.append(RuleEngine._match_threshold(data_item, sub))
                elif sub_type == "behavior":
                    results.append(RuleEngine._match_behavior(data_item, sub))
                elif sub_type == "composite":
                    results.append(RuleEngine._match_composite(data_item, sub))
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

            # 计算时间窗口内的进程启动数量
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
