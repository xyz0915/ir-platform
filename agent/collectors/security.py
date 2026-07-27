"""10. 安全信息采集器."""

import logging
from typing import Any

from collectors.base_collector import BaseCollector
from collectors.logs import _safe_wevtutil_query
from utils.platform import is_windows, is_linux, run_command, normalize_timestamp

logger = logging.getLogger(__name__)


class SecurityCollector(BaseCollector):
    """安全信息采集器.

    采集杀毒软件、防火墙规则、审计策略、安全事件 ID 统计.
    安全事件查询按 log_days 时间窗口过滤.

    Attributes:
        log_days: 采集最近 N 天的安全事件（默认 7 天）.
    """

    name = "security"
    platform = ["windows", "linux"]

    def collect(self) -> dict:
        """执行安全信息采集."""
        if is_windows():
            return self._collect_windows()
        elif is_linux():
            return self._collect_linux()
        return {"antivirus": [], "firewall_rules": [], "audit_policy": {}, "event_ids_summary": {}}

    def _collect_windows(self) -> dict:
        """Windows 安全信息采集."""
        event_data = self._get_windows_event_summary()
        return {
            "antivirus": self._get_windows_antivirus(),
            "firewall_rules": self._get_windows_firewall(),
            "audit_policy": self._get_windows_audit_policy(),
            "event_ids_summary": event_data.get("event_ids_summary", {}),
            "event_records": event_data.get("event_records", []),
        }

    def _get_windows_antivirus(self) -> list:
        """获取 Windows 杀毒软件信息."""
        result = []
        try:
            # 使用 PowerShell 获取安全产品
            output = run_command(
                'powershell -Command "Get-CimInstance -Namespace root/SecurityCenter2 -ClassName AntivirusProduct | Select-Object displayName,productState | Format-List" 2>nul',
                timeout=15,
            )
            if output:
                current: dict[str, Any] = {}
                for line in output.split("\n"):
                    line = line.strip()
                    if ":" in line:
                        key, _, value = line.partition(":")
                        key = key.strip()
                        value = value.strip()
                        if key == "displayName":
                            if current:
                                result.append(current)
                            current = {"name": value, "status": "unknown"}
                        elif key == "productState":
                            if current:
                                current["product_state"] = value
                if current:
                    result.append(current)
        except Exception:
            pass
        return result

    def _get_windows_firewall(self) -> list:
        """获取 Windows 防火墙规则."""
        rules = []
        output = run_command("netsh advfirewall firewall show rule name=all 2>nul", timeout=30)
        if output:
            current: dict[str, Any] = {}
            for line in output.split("\n"):
                line = line.strip()
                if ":" in line:
                    key, _, value = line.partition(":")
                    key = key.strip().lower().replace(" ", "_")
                    value = value.strip()
                    if key in ("rule_name", "名称"):
                        if current:
                            rules.append(current)
                        current = {"name": value}
                    elif current:
                        current[key] = value
            if current:
                rules.append(current)
        return rules[:200]

    def _get_windows_audit_policy(self) -> dict:
        """获取 Windows 审计策略."""
        policy: dict[str, Any] = {}
        output = run_command("auditpol /get /category:* 2>nul", timeout=15)
        if output:
            current_cat = ""
            for line in output.split("\n"):
                line = line.strip()
                if not line or "系统找不到" in line:
                    continue
                if ":" in line:
                    parts = line.split(":", 1)
                    if len(parts) == 2:
                        policy[parts[0].strip()] = parts[1].strip()
        return policy

    def _get_windows_event_summary(self) -> dict:
        """获取安全事件 ID 统计及前 N 条事件记录（按 log_days 时间窗口过滤）.

        Returns:
            {"event_ids_summary": {"4625": 3, ...}, "event_records": [...]}.
            event_records 最多 100 条，每条含 event_id / time / description 字段.
        """
        summary: dict[str, int] = {}
        records: list[dict[str, str]] = []

        # 计算 timediff 阈值（毫秒）
        timediff_ms = self.log_days * 86400 * 1000
        query = f'*[System[TimeCreated[timediff(@SystemTime) <= {timediff_ms}]]]'

        # 使用安全查询（timediff 带 60s 超时 + 无时间过滤 fallback）
        output = _safe_wevtutil_query("Security", query, 1000, timeout=60)
        if output:
            current_record: dict[str, str] = {}
            for line in output.split("\n"):
                if "Event ID" in line or "事件 ID" in line:
                    parts = line.split(":")
                    if len(parts) >= 2:
                        event_id = parts[-1].strip()
                        summary[event_id] = summary.get(event_id, 0) + 1

                        # 如果还在收 records 且未满 100 条，收完当前条再 flush
                        if len(records) < 100:
                            if current_record and current_record.get("event_id"):
                                records.append(current_record)
                            current_record = {"event_id": event_id, "time": "", "description": ""}
                elif ":" in line:
                    key, _, value = line.partition(":")
                    key = key.strip()
                    value = value.strip()
                    if key == "Time" and current_record:
                        current_record["time"] = normalize_timestamp(value)
                    elif key == "Description" and current_record:
                        current_record["description"] = value

            # flush last record
            if current_record and current_record.get("event_id") and len(records) < 100:
                records.append(current_record)

        return {
            "event_ids_summary": summary,
            "event_records": records[:100],
        }

    def _collect_linux(self) -> dict:
        """Linux 安全信息采集."""
        return {
            "antivirus": self._get_linux_antivirus(),
            "firewall_rules": self._get_linux_firewall(),
            "audit_policy": self._get_linux_audit(),
            "event_ids_summary": {},
        }

    def _get_linux_antivirus(self) -> list:
        """获取 Linux 杀毒软件."""
        result = []
        checks = ["clamav", "freshclam", "clamd"]
        for check in checks:
            output = run_command(f"which {check} 2>/dev/null")
            if output:
                result.append({"name": "ClamAV", "status": "installed", "path": output})
                break
        return result

    def _get_linux_firewall(self) -> list:
        """获取 Linux 防火墙规则."""
        rules = []
        # iptables
        output = run_command("iptables -L -n 2>/dev/null", timeout=10)
        if output:
            for line in output.split("\n"):
                line = line.strip()
                if line and not line.startswith("Chain") and not line.startswith("target"):
                    parts = line.split()
                    if len(parts) >= 3:
                        rules.append({
                            "target": parts[0],
                            "protocol": parts[1] if len(parts) > 1 else "",
                            "source": parts[4] if len(parts) > 4 else "",
                            "destination": parts[5] if len(parts) > 5 else "",
                        })

        # ufw
        ufw_output = run_command("ufw status verbose 2>/dev/null", timeout=5)
        if ufw_output:
            for line in ufw_output.split("\n"):
                rules.append({"ufw_rule": line.strip()})

        return rules[:200]

    def _get_linux_audit(self) -> dict:
        """获取 Linux 审计策略."""
        policy: dict[str, Any] = {}
        output = run_command("auditctl -l 2>/dev/null", timeout=10)
        if output:
            policy["audit_rules"] = output.split("\n")
        return policy
