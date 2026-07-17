"""Action 执行器 — 对应 action_map.py 中 7 种操作."""
import logging
import time
from typing import Any
from app.schemas.ai_advanced import ActionResult

logger = logging.getLogger(__name__)

class ActionService:
    """操作执行器 — 每个方法对应一种 Action."""

    @staticmethod
    async def block_ip(target: dict) -> ActionResult:
        """封锁 IP（模拟）."""
        ip = target.get("ip", "")
        logger.info("Blocking IP: %s", ip)
        time.sleep(0.3)
        return ActionResult(
            success=True, action="block_ip", status="completed",
            result={"ip": ip, "rule_id": f"FW-{int(time.time())}"},
            exec_time_ms=300, affected_hosts=["web-01", "web-02"],
        )

    @staticmethod
    async def isolate_host(target: dict) -> ActionResult:
        """隔离主机（模拟）."""
        hostname = target.get("hostname", "")
        logger.info("Isolating host: %s", hostname)
        time.sleep(0.5)
        return ActionResult(
            success=True, action="isolate_host", status="completed",
            result={"hostname": hostname, "task_id": f"ISO-{int(time.time())}"},
            exec_time_ms=500,
        )

    @staticmethod
    async def export_report(target: dict) -> ActionResult:
        """导出报告（模拟）."""
        report_type = target.get("report_type", "summary")
        return ActionResult(
            success=True, action="export_report", status="completed",
            result={"report_type": report_type, "file_url": "/api/reports/latest.pdf"},
            exec_time_ms=200,
        )

    @staticmethod
    async def mark_false_positive(target: dict) -> ActionResult:
        """标记误报（模拟）."""
        alert_id = target.get("alert_id", "")
        return ActionResult(
            success=True, action="mark_false_positive", status="completed",
            result={"alert_id": alert_id},
            exec_time_ms=100,
        )

    @staticmethod
    async def add_whitelist(target: dict) -> ActionResult:
        """加入白名单（模拟）."""
        item = target.get("item", "")
        return ActionResult(
            success=True, action="add_whitelist", status="completed",
            result={"item": item},
            exec_time_ms=100,
        )

    @staticmethod
    async def create_case(target: dict) -> ActionResult:
        """创建案件（模拟）."""
        title = target.get("title", "AI 生成案件")
        return ActionResult(
            success=True, action="create_case", status="completed",
            result={"case_id": f"CASE-{int(time.time())}", "title": title},
            exec_time_ms=300,
        )

    @staticmethod
    async def add_note(target: dict) -> ActionResult:
        """添加调查笔记（模拟）."""
        content = target.get("content", "")
        return ActionResult(
            success=True, action="add_note", status="completed",
            result={"note_id": f"NOTE-{int(time.time())}", "content_preview": content[:50]},
            exec_time_ms=100,
        )

    # 执行器注册表
    EXECUTOR_MAP = {
        "block_ip": block_ip,
        "isolate_host": isolate_host,
        "export_report": export_report,
        "mark_false_positive": mark_false_positive,
        "add_whitelist": add_whitelist,
        "create_case": create_case,
        "add_note": add_note,
    }

    @staticmethod
    async def execute(action: str, target: dict) -> ActionResult:
        """根据 action 名称调用对应的执行器."""
        executor = ActionService.EXECUTOR_MAP.get(action)
        if not executor:
            return ActionResult(
                success=False, action=action, status="failed",
                error=f"Unknown action: {action}", exec_time_ms=0,
            )
        try:
            return await executor(target)
        except Exception as e:
            logger.exception("Action %s failed: %s", action, e)
            return ActionResult(
                success=False, action=action, status="failed",
                error=str(e), exec_time_ms=0,
            )
