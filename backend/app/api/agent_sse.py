"""SSE 流端点 — 智能体编排实时推送."""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.models.agent_run import AgentRun
from app.services.auth_service import get_current_user
from app.services.sse_manager import sse_manager

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/agents/runs/{run_id}/stream")
async def stream_agent_run(
    run_id: str,
    current_user: Optional[dict] = Depends(get_current_user),
):
    """SSE 流 — 实时推送 Agent 执行步骤。"""
    # 验证 run 是否存在
    run = AgentRun.get_by_run_id(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run 不存在")

    return StreamingResponse(
        sse_manager.subscribe(run_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
