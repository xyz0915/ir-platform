"""通知服务 — 支持 WebSocket 广播通知。

复用 alert_ws_manager 的 broadcast 能力。
"""
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


async def notify_hitl_pending(run_id: str, action: str, approval_id: int) -> None:
    """广播 HITL 待审批通知."""
    try:
        from app.services.alert_ws import alert_ws_manager

        payload = json.dumps({
            "type": "hitl_pending",
            "run_id": run_id,
            "action": action,
            "approval_id": approval_id,
        })
        await alert_ws_manager.broadcast(payload)
        logger.info("HITL notification sent: run_id=%s, action=%s", run_id, action)
    except Exception as exc:
        logger.warning("HITL notify broadcast failed: %s", exc)


async def notify_run_update(
    run_id: str,
    status: str,
    stage: str,
    **kwargs: Any,
) -> None:
    """广播 run 状态变更通知."""
    try:
        from app.services.alert_ws import alert_ws_manager

        payload = json.dumps({
            "type": "run_update",
            "run_id": run_id,
            "status": status,
            "stage": stage,
            **kwargs,
        })
        await alert_ws_manager.broadcast(payload)
    except Exception as exc:
        logger.warning("Run update notify broadcast failed: %s", exc)
