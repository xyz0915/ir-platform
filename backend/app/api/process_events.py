"""进程事件流入口（T-P2-3 PoC）.

薄封装：将 Agent 推送的进程实时事件（进程生/灭、远线程注入、ETW/AMSI 旁路等）
落库到 process_events 表，复用已有的 ``ProcessEventConsumer.ingest``。
本模块不引入任何新逻辑，仅作 HTTP 入口，保障 ingest / normalize / evaluate 行为不变。
"""

from typing import Any, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from app.analysis.process_event_consumer import ProcessEventConsumer

logger = __import__("logging").getLogger(__name__)

router = APIRouter()


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
def ingest_process_events(host_id: int, events: List[ProcessEventItem]) -> dict:
    """摄取并落库主机推送的进程事件列表.

    Args:
        host_id: 主机 ID（路径参数）.
        events: 进程事件列表（list[dict]，字段对齐 ProcessEvent.create）.

    Returns:
        ``{"written": int}`` —— 实际写入库中的事件条数.
    """
    payload = [ev.model_dump(exclude_none=True) for ev in events]
    written = ProcessEventConsumer.ingest(host_id, payload)
    return {"written": written}
