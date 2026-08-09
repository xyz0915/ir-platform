"""实时告警引擎 — 事件→告警评估 + 聚合降噪."""
import logging
from datetime import datetime, timedelta
from typing import Optional

from app.models.alert import Alert
from app.services.alert_ws import alert_ws_manager

logger = logging.getLogger(__name__)

# 事件类型到告警规则的映射
_EVENT_RULES = {
    "process_create": {"severity": "medium", "rule_name": "EVENT-PROCESS-CREATE", "label": "进程创建事件"},
    "process_term": {"severity": "low", "rule_name": "EVENT-PROCESS-TERM", "label": "进程终止事件"},
    "network_connect": {"severity": "medium", "rule_name": "EVENT-NET-CONNECT", "label": "新建网络连接"},
    "network_disconnect": {"severity": "low", "rule_name": "EVENT-NET-DISCONNECT", "label": "网络连接断开"},
    "file_create": {"severity": "medium", "rule_name": "EVENT-FILE-CREATE", "label": "文件创建事件"},
    "file_modify": {"severity": "medium", "rule_name": "EVENT-FILE-MODIFY", "label": "文件修改事件"},
    "file_delete": {"severity": "high", "rule_name": "EVENT-FILE-DELETE", "label": "文件删除事件"},
}

# 关键进程匹配（包含这些关键字的路径/进程名 → 提升严重度）
_CRITICAL_PATHS = [
    "lsass.exe", "winlogon.exe", "svchost.exe", "system", "services.exe",
    "/etc/passwd", "/etc/shadow", "/etc/sudoers", "/bin/",
    "certutil", "powershell", "wscript", "cscript", "mshta",
]


class AlertEngine:
    """实时告警引擎."""

    def __init__(self, ws_manager=None):
        self.ws_manager = ws_manager or alert_ws_manager

    def process_event(self, host_id: int, event: dict) -> Optional[dict]:
        """处理单条事件，返回新创建的告警或 None."""
        event_type = event.get("event_type", "")
        rule = _EVENT_RULES.get(event_type)
        if not rule:
            return None

        # 构建告警标题
        process_name = event.get("process_name", "") or event.get("name", "")
        path = event.get("process_path", "") or event.get("path", "")
        detail_str = event.get("command_line") or event.get("detail", "")

        # 检查是否涉及关键进程 → 提升严重度
        severity = rule["severity"]
        for cp in _CRITICAL_PATHS:
            if cp.lower() in process_name.lower() or cp.lower() in path.lower():
                severity = "high"
                if "certutil" in process_name.lower() or "powershell" in process_name.lower():
                    severity = "critical"
                break

        title = f"[{rule['label']}] {process_name}" if process_name else rule["label"]
        rule_name = rule["rule_name"]
        source_pid = event.get("pid")
        source_ip = event.get("remote_address") or event.get("ip")

        # 聚合或新建（5 分钟内同规则不重复创建）
        alert_id, is_new = Alert.create_or_aggregate(
            host_id=host_id, rule_name=rule_name, severity=severity,
            title=title, detail=detail_str,
            source_pid=source_pid, source_process=process_name,
            source_path=path, source_ip=source_ip,
            rule_label=rule["label"]
        )

        if is_new and alert_id is not None:
            alert = Alert.get_by_id(alert_id)
            if alert:
                import asyncio
                try:
                    asyncio.create_task(self.ws_manager.broadcast({
                        "type": "new_alert",
                        "alert": {
                            "id": alert["id"],
                            "host_id": alert["host_id"],
                            "severity": alert["severity"],
                            "title": alert["title"],
                            "rule_name": alert["rule_name"],
                            "source_process": alert.get("source_process", ""),
                            "source_ip": alert.get("source_ip", ""),
                            "count": alert["count"],
                            "first_seen_at": alert["first_seen_at"],
                            "status": alert["status"],
                        }
                    }))
                except Exception as e:
                    logger.warning("WebSocket broadcast failed: %s", e)
                return alert
        return None

    def evaluate_events(self, host_id: int, events: list) -> list:
        """批量评估事件列表，返回新产生的告警列表.

        进程类事件（含 daemon 的 ``process_start``）统一走进程专用评估
        ``evaluate_process_event``（命令级检测 certutil/powershell/ recon/凭据窃取），
        其余事件走通用 ``process_event``。两类最终都经 ``Alert.create_or_aggregate``
        做 5 分钟窗口内按 (host, rule) 聚合，确保 daemon 高频进程流不会触发告警风暴。
        """
        _PROCESS_TYPES = {"process_start", "process_create", "process_term"}
        new_alerts = []
        for event in (events or []):
            if not isinstance(event, dict):
                continue
            try:
                et = event.get("event_type", "")
                if et in _PROCESS_TYPES:
                    result = self.evaluate_process_event(host_id, event)
                else:
                    result = self.process_event(host_id, event)
                if result:
                    new_alerts.append(result)
            except Exception as e:
                logger.warning("Event evaluation error: %s", e)
        return new_alerts

    def evaluate_process_event(self, host_id: int, event: dict) -> Optional[dict]:
        """处理 process_events 端点推送的进程事件."""
        cmd = event.get("command_line", "") or event.get("detail", "") or ""
        name = event.get("process_name", "") or event.get("name", "")
        pid = event.get("pid")

        # 检测敏感命令
        severity = "low"
        rule_name = "EVENT-PROCESS-ROUTINE"
        label = "进程运行"

        if "certutil" in cmd.lower() and ("-urlcache" in cmd.lower() or "-split" in cmd.lower()):
            severity = "critical"
            rule_name = "EVENT-CERTUTIL-DOWNLOAD"
            label = "certutil 下载执行"
        elif "powershell" in cmd.lower() and "-enc" in cmd.lower():
            severity = "critical"
            rule_name = "EVENT-PS-ENCODED"
            label = "PowerShell 编码执行"
        elif any(x in cmd.lower() for x in ["whoami", "net user", "ipconfig", "systeminfo"]):
            severity = "medium"
            rule_name = "EVENT-RECON"
            label = "信息收集命令"
        elif "procdump" in name.lower() or "mimikatz" in name.lower():
            severity = "critical"
            rule_name = "EVENT-CRED-DUMP"
            label = "凭据窃取工具"

        title = f"[{label}] {name}" if name else label
        alert_id, is_new = Alert.create_or_aggregate(
            host_id=host_id, rule_name=rule_name, severity=severity,
            title=title, detail=cmd, source_pid=pid,
            source_process=name, rule_label=label
        )

        if is_new and alert_id is not None:
            alert = Alert.get_by_id(alert_id)
            if alert:
                import asyncio
                try:
                    asyncio.create_task(self.ws_manager.broadcast({
                        "type": "new_alert", "alert": alert
                    }))
                except Exception:
                    pass
                return alert
        return None

    def evaluate_batch_process_events(self, host_id: int, events: list) -> list:
        """批量评估进程事件."""
        results = []
        for e in (events or []):
            if isinstance(e, dict):
                try:
                    r = self.evaluate_process_event(host_id, e)
                    if r:
                        results.append(r)
                except Exception:
                    pass
        return results
