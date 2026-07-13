"""日志范式化引擎 — Windows EventLog + Linux syslog 统一清洗."""

import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ── Windows Event ID → (event_type, event_label, severity, mitre) ──
WINDOWS_EVENT_MAP: dict[int, tuple[str, str, str, str]] = {
    # 🚨 P0 — 急救必检
    1102: ("audit_log_cleared", "审计日志清除", "critical", "T1070"),
    4698: ("scheduled_task_created", "计划任务创建", "high", "T1053"),
    7045: ("service_installed", "服务安装", "high", "T1543"),
    # 登录事件
    4625: ("failed_logon", "登录失败", "high", "T1110"),
    4624: ("successful_logon", "登录成功", "medium", "T1078"),
    4672: ("admin_logon", "管理员登录", "high", "T1078"),
    4648: ("explicit_logon", "显式登录", "high", "T1078"),
    4634: ("logoff", "注销", "low", ""),
    4647: ("logoff_initiated", "用户注销", "low", ""),
    # 账户管理
    4720: ("user_created", "用户创建", "high", "T1136"),
    4722: ("user_enabled", "用户启用", "medium", ""),
    4723: ("password_change", "密码修改", "medium", ""),
    4724: ("password_reset", "密码重置", "medium", ""),
    4725: ("user_disabled", "用户禁用", "medium", ""),
    4726: ("user_deleted", "用户删除", "high", ""),
    4732: ("user_added_to_group", "用户加组", "high", "T1098"),
    4733: ("user_removed_from_group", "用户移出组", "medium", ""),
    4740: ("account_locked", "账户锁定", "medium", ""),
    4767: ("account_unlocked", "账户解锁", "low", ""),
    # 策略变更
    4719: ("audit_policy_change", "审计策略变更", "high", "T1562"),
    4739: ("domain_policy_change", "域策略变更", "high", ""),
    4907: ("audit_settings_change", "审计设置变更", "high", "T1562"),
    # 进程
    4688: ("process_creation", "进程创建", "medium", "T1059"),
    # 服务
    7036: ("service_state_change", "服务状态变更", "low", ""),
    7040: ("service_start_type_change", "服务启动类型变更", "medium", ""),
    # 计划任务
    4700: ("scheduled_task_enabled", "计划任务启用", "medium", ""),
    4701: ("scheduled_task_disabled", "计划任务禁用", "low", ""),
    4702: ("scheduled_task_updated", "计划任务更新", "medium", ""),
    # 对象访问
    4656: ("object_access", "对象访问", "low", ""),
    4663: ("object_access_attempt", "对象访问尝试", "medium", ""),
    5140: ("share_access", "共享访问", "medium", ""),
    # 防火墙
    5156: ("connection_outbound", "外连放行", "medium", "T1071"),
    5157: ("connection_blocked", "外连阻止", "low", ""),
    5154: ("listen_start", "端口监听", "medium", ""),
    # 系统
    6005: ("eventlog_start", "日志服务启动", "info", ""),
    6006: ("eventlog_stop", "日志服务停止", "info", ""),
    6008: ("unexpected_shutdown", "异常关机", "medium", ""),
    6013: ("uptime", "系统运行时间", "info", ""),
    # 组策略
    5136: ("gpo_modified", "组策略修改", "high", ""),
    5142: ("network_share_created", "网络共享创建", "medium", ""),
    5145: ("network_share_access", "网络共享访问", "low", ""),
    # PowerShell
    200: ("powershell_execution", "PowerShell 执行", "medium", "T1059.001"),
    400: ("powershell_module_load", "PowerShell 模块加载", "low", ""),
    4103: ("powershell_module_log", "PowerShell 模块日志", "high", "T1059.001"),
    4104: ("powershell_scriptblock", "PowerShell 脚本块", "high", "T1059.001"),
    # 凭据
    5379: ("credential_manager_read", "凭据管理器读取", "high", "T1003"),
    5382: ("credential_manager_backup", "凭据管理器备份", "high", "T1003"),
}

# ── Linux 正则 → (event_type, event_label, severity, mitre) ──
LINUX_PATTERNS: list[tuple[str, str, str, str, str]] = [
    # SSH
    (r"sshd.*Accepted \w+ for (\w+) from (\S+)", "ssh_logon", "SSH 登录成功", "high", "T1078"),
    (r"sshd.*Failed password for (\w+) from (\S+)", "ssh_failed", "SSH 登录失败", "high", "T1110"),
    (r"sshd.*Failed password for invalid user (\w+) from (\S+)", "ssh_failed", "SSH 登录失败(未知用户)", "high", "T1110"),
    (r"sshd.*Did not receive identification", "ssh_scan", "SSH 扫描", "medium", "T1110"),
    (r"sshd.*Connection closed by authenticating user (\w+)", "ssh_disconnect", "SSH 断开", "low", ""),
    # Sudo
    (r"sudo: .*COMMAND=(.+)", "sudo_execution", "Sudo 执行", "high", "T1548"),
    (r"sudo: .*session opened for user (\w+)", "sudo_session", "Sudo 会话", "medium", "T1548"),
    (r"sudo: .*session closed", "sudo_session_end", "Sudo 结束", "low", ""),
    # Cron
    (r"CRON\[\d+\]: \((\w+)\) CMD (.+)", "cron_execution", "Cron 执行", "medium", "T1053"),
    (r"anacron\[\d+\]:.*job (.+)", "anacron_job", "Anacron 任务", "low", ""),
    # 用户管理
    (r"useradd\[\d+\]: new user", "user_created", "用户创建", "high", "T1136"),
    (r"userdel\[\d+\]: delete user", "user_deleted", "用户删除", "high", ""),
    (r"usermod\[\d+\]: change user", "user_modified", "用户修改", "high", ""),
    (r"groupadd\[\d+\]: new group", "group_created", "组创建", "medium", ""),
    # Systemd 服务
    (r"systemd\[\d+\]: Started (.+)", "service_start", "服务启动", "low", ""),
    (r"systemd\[\d+\]: Stopped (.+)", "service_stop", "服务停止", "low", ""),
    (r"systemd\[\d+\]: Failed to start (.+)", "service_failed", "服务启动失败", "medium", ""),
    # Su
    (r"su.*FAILED.*for (\w+)", "su_failed", "Su 失败", "medium", ""),
    (r"su.*session opened for user (\w+)", "su_success", "Su 成功", "medium", "T1548"),
    # 其他
    (r"pkexec\[\d+\]:.*user (\w+)", "pkexec_execution", "Pkexec 执行", "high", "T1548"),
    (r"pam_unix.*authentication failure.*user=(\w+)", "auth_failed", "认证失败", "medium", ""),
]

# ── 安全标签（命令行关键词 → 标签名）──
TAG_RULES: list[tuple[str, str]] = [
    # 编码执行
    (r"(?i)powershell.*-(enc|encodedcommand)", "powershell_encoded"),
    (r"(?i)powershell.*IEX\s*\(.*\)", "powershell_iex"),
    (r"(?i)powershell.*(Invoke-Expression|Invoke-WebRequest)", "powershell_livingoff"),
    # 下载执行
    (r"(?i)certutil.*(-urlcache|-split)", "certutil_download"),
    (r"(?i)bitsadmin.*(transfer|download)", "bitsadmin_download"),
    (r"(?i)curl.*(-o|-O)|wget.*(-O|-o)", "curl_wget_download"),
    # 凭据窃取
    (r"(?i)mimikatz", "mimikatz"),
    (r"(?i)procdump.*(-ma|-64)", "procdump_lsass"),
    (r"(?i)comsvcs.*MiniDump", "comsvcs_minidump"),
    (r"(?i)sekurlsa", "sekurlsa"),
    # 横向移动
    (r"(?i)psexec", "psexec"),
    (r"(?i)wmic.*/node:", "wmic_remote"),
    (r"(?i)winrm", "winrm"),
    # 持久化
    (r"(?i)schtasks.*/create", "schtasks_create"),
    (r"(?i)sc\.exe\s+create", "sc_create"),
    (r"(?i)reg\s+add.*\\Run", "registry_run_key"),
    # LOLBIN
    (r"(?i)mshta", "mshta_lolbin"),
    (r"(?i)regsvr32", "regsvr32_lolbin"),
    (r"(?i)rundll32", "rundll32_lolbin"),
    (r"(?i)cscript|wscript", "cscript_lolbin"),
    (r"(?i)msbuild", "msbuild_lolbin"),
    # 防御绕过
    (r"(?i)wevtutil\s+(cl|clear-log)", "wevtutil_clear"),
    (r"(?i)bcdedit.*(debug|testsigning)", "bcdedit_tamper"),
    (r"(?i)recover.*password|password.*recover", "password_recovery"),
]


class LogNormalizer:
    """日志范式化引擎."""

    @classmethod
    def normalize_host_logs(cls, logs: dict, host_id: int, hostname: str) -> list[dict]:
        """范式化指定主机的全部日志.

        Args:
            logs: Agent JSON 中的 logs 字段 {system, security, application, syslog}
            host_id: 主机 ID
            hostname: 主机名

        Returns:
            范式化后的日志条目列表
        """
        result = []
        for log_source in ("system", "security", "application", "syslog"):
            entries = logs.get(log_source, [])
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    # Linux 原始日志字符串
                    item = cls._normalize_linux_line(entry, host_id, hostname, log_source)
                    if item:
                        result.append(item)
                elif entry.get("event_id") or entry.get("EventID"):
                    # Windows 事件日志（含 event_id 字段）
                    item = cls._normalize_windows_event(entry, host_id, hostname, log_source)
                    if item:
                        result.append(item)
                elif entry.get("log_name") or entry.get("source"):
                    # Windows 事件日志但缺 event_id 字段（description 为空的情况）
                    item = cls._normalize_windows_event_generic(entry, host_id, hostname, log_source)
                    if item:
                        result.append(item)
                else:
                    # 未知格式的 dict
                    item = cls._normalize_linux_line(entry, host_id, hostname, log_source)
                    if item:
                        result.append(item)
        return result

    @classmethod
    def _normalize_windows_event(cls, raw: dict, host_id: int, hostname: str, log_source: str) -> Optional[dict]:
        """范式化单条 Windows 事件日志."""
        try:
            event_id = int(raw.get("event_id") or raw.get("EventID") or 0)
            severity = "info"
            # 从映射表查事件类型
            mapping = WINDOWS_EVENT_MAP.get(event_id)
            event_type = mapping[0] if mapping else f"unknown_{event_id}"
            event_label = mapping[1] if mapping else f"事件 {event_id}"
            severity = mapping[2] if mapping else "info"
            mitre = mapping[3] if mapping else ""

            # 改进严重度：特定进程名提升严重度
            raw_desc = (raw.get("description") or raw.get("Description") or "").lower()
            raw_cmd = raw_desc  # description 里也包含了 command_line

            cli = raw.get("description") or raw.get("Description") or ""
            process_name = raw.get("source") or raw.get("Source") or ""
            raw_text_for_tag = (process_name + " " + cli).lower()

            # 提升严重度：PS编码、certutil 下载、凭据窃取
            if re.search(r"(?i)powershell.*-enc|mimikatz|certutil.*-urlcache", raw_text_for_tag):
                severity = "critical"
                event_type = "process_creation_alert"
            elif re.search(r"(?i)procdump.*lsass|comsvcs.*MiniDump|sekurlsa", raw_text_for_tag):
                severity = "critical"
                event_type = "credential_dump"

            # 提取用户
            user = ""
            for line in raw_desc.split("\n"):
                if "帐户名" in line or "Account Name" in line:
                    user = line.split(":")[-1].strip()
                    break
                m = re.search(r"帐户名[：:]\s*(\S+)", line)
                if m:
                    user = m.group(1)
                    break

            # 提取来源 IP
            src_ip = ""
            for line in raw_desc.split("\n"):
                if "源网络地址" in line or "Source Network Address" in line or "IP Address" in line:
                    ip = line.split(":")[-1].strip()
                    if ip and ip != "-":
                        src_ip = ip
                        break

            # 提取进程 PID
            pid = None
            raw_str = raw.get("description") or raw.get("Description") or raw.get("raw", "")
            for line in raw_str.split("\n"):
                m = re.search(r"(?:进程 ID|Process ID|PID)[：:]\s*(\d+)", line)
                if m:
                    pid = int(m.group(1))
                    break

            # 提取命令行
            cmd_line = ""
            for line in raw_str.split("\n"):
                if "命令行" in line or "Command Line" in line:
                    cmd_line = line.split(":", 1)[-1].strip()
                    break

            # 自动打标签
            tags = cls._apply_tags(raw_text_for_tag)

            return {
                "host_id": host_id,
                "hostname": hostname,
                "log_source": log_source,
                "event_id": event_id,
                "event_type": event_type,
                "event_label": event_label,
                "mitre_attack": mitre,
                "severity": severity,
                "timestamp": raw.get("time") or raw.get("Time") or raw.get("timestamp", ""),
                "source_ip": src_ip,
                "user_name": user,
                "process_name": process_name,
                "process_pid": pid,
                "command_line": cmd_line[:500],
                "object_name": raw.get("source") or "",
                "tags": ",".join(tags) if tags else "",
                "description": (raw.get("description") or raw.get("Description") or "")[:1000],
                "raw_data": (raw.get("description") or raw.get("Description") or "")[:1000],
            }
        except Exception as e:
            logger.debug("Normalize windows event failed: %s", e)
            return None

    @classmethod
    def _normalize_windows_event_generic(cls, raw: dict, host_id: int, hostname: str, log_source: str) -> Optional[dict]:
        """范式化缺 event_id 字段的 Windows 事件日志.

        Agent 采集的部分日志仅含 {log_name, source, computer, description}，
        无 event_id 字段，description 也可能为空。
        """
        try:
            log_name = raw.get("log_name", "")
            source = raw.get("source", "")
            computer = raw.get("computer", "") or ""
            desc = raw.get("description", "") or ""

            # 从 description 中尝试提取 Event ID
            event_id = 0
            m = re.search(r"EventID[：:]\s*(\d+)", desc)
            if m:
                event_id = int(m.group(1))

            # 从 source 推断事件类型 + 严重度
            event_source = source or log_name or "unknown"
            severity = "info"
            mitre = ""
            event_type = f"windows_{log_source}_{event_source.replace(' ','_').lower()[:30]}"
            event_label = f"{log_name} - {event_source}"

            # Source 关键词 → 严重度升级 + MITRE 标签
            source_lower = source.lower()
            if "security-auditing" in source_lower or "fail" in source_lower:
                severity = "medium"
            if any(kw in source_lower for kw in ("defender", "firewall", "malware", "attack", "threat")):
                severity = "high"
            if any(kw in source_lower for kw in ("clear", "disable", "tamper", "delete", "removed")):
                severity = "critical"

            # 从 source 推断类别的事件 ID
            if event_id == 0:
                source_to_event = {
                    "microsoft-windows-distributedcom": 10016,
                    "service control manager": 7036,
                    "microsoft-windows-security-auditing": 4624,
                    "microsoft-windows-security-spp": 16384,
                    "microsoft-windows-kernel-generic": 12,
                    "microsoft-windows-windowsupdateclient": 19,
                    "microsoft-windows-time-service": 35,
                    "msiinstaller": 10005,
                    "vmauthd": 100,
                    "microsoft-windows-hyper-v-vmsw": 12500,
                    "edgeupdate": 0,
                    "securitycenter": 1116,
                    "windows_error_reporting": 1001,
                    "browser": 1018,
                    "mssqlserver": 18401,
                }
                for key, eid in source_to_event.items():
                    if key in source_lower:
                        event_id = eid
                        mapping = WINDOWS_EVENT_MAP.get(event_id)
                        if mapping:
                            event_type = mapping[0]
                            event_label = mapping[1]
                            severity = mapping[2]
                            mitre = mapping[3]
                            break

            # 提取时间戳
            timestamp = ""
            m = re.search(r"Time[：:]\s*(\S+)", desc)
            if m:
                timestamp = m.group(1)

            tags = cls._apply_tags(source + " " + desc)

            return {
                "host_id": host_id,
                "hostname": hostname or computer,
                "log_source": log_source,
                "event_id": event_id,
                "event_type": event_type[:50],
                "event_label": event_label[:80],
                "mitre_attack": mitre,
                "severity": severity,
                "timestamp": timestamp,
                "source_ip": "",
                "user_name": "",
                "process_name": source,
                "process_pid": None,
                "command_line": desc[:500] if desc else "",
                "object_name": source,
                "tags": ",".join(tags) if tags else "",
                "description": f"{source}@{computer}" if not desc else desc[:500],
                "raw_data": desc[:500],
            }
        except Exception as e:
            logger.debug("Normalize windows event generic failed: %s", e)
            return None

    @classmethod
    def _normalize_linux_line(cls, raw_line: dict | str, host_id: int, hostname: str, log_source: str) -> Optional[dict]:
        """范式化单条 Linux 日志行."""
        try:
            if isinstance(raw_line, dict):
                text = raw_line.get("raw", raw_line.get("description", str(raw_line)))
                src = raw_line.get("source", "")
            else:
                text = raw_line
                src = log_source

            if not text:
                return None

            # 匹配 Linux 正则
            for pattern, etype, elabel, sev, mitre in LINUX_PATTERNS:
                m = re.search(pattern, text)
                if m:
                    groups = m.groups()
                    user_name = groups[0] if len(groups) >= 1 else ""
                    source_ip = groups[1] if len(groups) >= 2 else ""

                    tags = cls._apply_tags(text)

                    return {
                        "host_id": host_id,
                        "hostname": hostname,
                        "log_source": log_source,
                        "event_id": 0,
                        "event_type": etype,
                        "event_label": elabel,
                        "mitre_attack": mitre,
                        "severity": sev,
                        "timestamp": "",
                        "source_ip": source_ip,
                        "user_name": user_name,
                        "process_name": "",
                        "process_pid": None,
                        "command_line": "",
                        "object_name": src,
                        "tags": ",".join(tags) if tags else "",
                        "description": text[:500],
                        "raw_data": text[:500],
                    }

            # 未匹配的行：标记为通用日志
            return {
                "host_id": host_id,
                "hostname": hostname,
                "log_source": log_source,
                "event_id": 0,
                "event_type": "syslog_generic",
                "event_label": "Syslog 通用",
                "mitre_attack": "",
                "severity": "info",
                "timestamp": "",
                "source_ip": "",
                "user_name": "",
                "process_name": "",
                "process_pid": None,
                "command_line": "",
                "object_name": src,
                "tags": "",
                "description": text[:500],
                "raw_data": text[:500],
            }
        except Exception as e:
            logger.debug("Normalize linux line failed: %s", e)
            return None

    @classmethod
    def _apply_tags(cls, text: str) -> list[str]:
        """自动打标签."""
        tags = []
        for pattern, tag_name in TAG_RULES:
            if re.search(pattern, text):
                if tag_name not in tags:
                    tags.append(tag_name)
        return tags

    @classmethod
    def detect_patterns(cls, logs: list[dict]) -> dict:
        """攻击模式识别."""
        patterns = {"brute_force": [], "download_exec": [], "alert_clear": []}

        # 暴破检测：同一来源 IP，4625 × ≥ 10 次，5 分钟内
        failed_logons = [l for l in logs if l.get("event_id") == 4625]
        ip_groups = {}
        for l in failed_logons:
            ip = l.get("source_ip", "") or "unknown"
            ip_groups.setdefault(ip, []).append(l)

        for ip, entries in ip_groups.items():
            if len(entries) >= 10:
                times = [e.get("timestamp", "") for e in entries if e.get("timestamp")]
                patterns["brute_force"].append({
                    "source_ip": ip,
                    "attempts": len(entries),
                    "first_seen": times[0] if times else "",
                    "last_seen": times[-1] if times else "",
                    "target_users": list(set(e.get("user_name", "") for e in entries)),
                })

        # 审计清除
        for l in logs:
            if l.get("event_id") == 1102:
                patterns["alert_clear"].append(l)

        return patterns
