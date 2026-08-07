"""进程事件流入口（T-P2-3 PoC）.

薄封装：将 Agent 推送的进程实时事件（进程生/灭、远线程注入、ETW/AMSI 旁路等）
落库到 process_events 表，复用已有的 ``ProcessEventConsumer.ingest``。
落库后调用实时告警引擎评估事件，新告警通过 WebSocket 广播。
本模块不引入任何新逻辑，仅作 HTTP 入口，保障 ingest / normalize / evaluate 行为不变。
"""

import asyncio
from typing import Any, List, Optional

from fastapi import APIRouter, Depends

from pydantic import BaseModel, ConfigDict

from app.analysis.process_event_consumer import ProcessEventConsumer
from app.services.alert_engine import AlertEngine
from app.services.alert_ws import alert_ws_manager
from app.services.agent_auth import assert_host_binding, get_current_agent

logger = __import__("logging").getLogger(__name__)

router = APIRouter()

engine = AlertEngine(ws_manager=alert_ws_manager)


class ProcessEventItem(BaseModel):
    """进程事件条目（字段对齐 ProcessEvent.create，额外字段透传）.

    请求体为事件列表（list[dict]），此处用 Pydantic 模型做基础校验与字段提示；
    extra="allow" 保证 Agent 端新增字段（如 memory_sections/etw_events 原始壳）
    不会因校验严格而被拒。
    """

    model_config = ConfigDict(extra="allow")

    event_type: str
    pid: Optional[int] = None
    ppid: Optional[int] = None
    process_name: Optional[str] = None
    process_path: Optional[str] = None
    command_line: Optional[str] = None
    parent_name: Optional[str] = None
    session: Optional[int] = None
    start_time: Optional[str] = None
    event_time: Optional[str] = None
    detail: Optional[Any] = None


@router.post("/hosts/{host_id}/process-events")
def ingest_process_events(host_id: int, events: List[ProcessEventItem],
                          agent: dict = Depends(get_current_agent)) -> dict:
    """摄取并落库主机推送的进程事件列表，同时触发实时告警评估.

    Args:
        host_id: 主机 ID（路径参数）.
        events: 进程事件列表（list[dict]，字段对齐 ProcessEvent.create）.
        agent: ``get_current_agent`` 依赖解析出的 agent token 认证信息.

    Returns:
        ``{"written": int, "alerts": int}`` —— 写入条数和新告警数.
    """
    assert_host_binding(agent, host_id)
    payload = [ev.model_dump(exclude_none=True) for ev in events]
    written = ProcessEventConsumer.ingest(host_id, payload)

    new_alerts_count = 0
    try:
        new_alerts = engine.evaluate_events(host_id, payload)
        new_alerts_count = len(new_alerts)
        for alert in new_alerts:
            asyncio.create_task(alert_ws_manager.broadcast({
                "type": "new_alert",
                "alert": alert,
            }))
    except Exception as e:
        logger.warning("Alert engine evaluation failed: %s", e)

    return {"written": written, "alerts": new_alerts_count}
