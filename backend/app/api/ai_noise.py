"""AI 降噪 API（v2 方案）.

端点:
  POST /api/ai/noise-reduce     — 触发 AI 降噪研判
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends

from app.services.ai_noise_reduce import noise_reduce
from app.services.auth_service import get_current_user

router = APIRouter(tags=["AI降噪"])


@router.post("/noise-reduce")
async def api_noise_reduce(
    case_id: int,
    host_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user),
):
    """触发 AI 降噪研判：将案件已匹配事件送 LLM 分析，生成 AI 优先推荐事件。"""
    result = await noise_reduce(case_id, host_id)
    return {"code": 0, "data": result, "message": "success"}
