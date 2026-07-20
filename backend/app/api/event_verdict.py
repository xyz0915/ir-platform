"""AI 事件研判打标端点（生产者）— T-V2.

POST /api/security-events/ai-verdict

路由挂载（main.py）：``app.include_router(event_verdict.router, prefix="/api/security-events")``
本模块 router 自身**不带前缀**，装饰器只写相对路径 ``/ai-verdict``，避免重复前缀
（规避 Batch③ ``/api/api/analysis/...`` 404 教训）。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.schemas.event_verdict import VerdictRequest
from app.services.auth_service import get_current_user
from app.services.event_verdict_service import EventVerdictService

router = APIRouter(tags=["AI研判"])


@router.post("/ai-verdict")
async def analyze_event_verdict(
    body: VerdictRequest,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """批量 AI 研判打标.

    请求体: ``{"event_ids": [...], "force": false, "confidence_threshold": 0.6}``
    鉴权: Depends(get_current_user)
    上限: 去重后 > 200 返回 400（客户端错误，非 500）
    """
    event_ids: list[Any] = list(body.event_ids)
    if not event_ids:
        raise HTTPException(status_code=400, detail="event_ids 不能为空")

    # 去重（保留首次出现顺序）
    seen: set[str] = set()
    deduped: list[Any] = []
    for e in event_ids:
        key = str(e)
        if key not in seen:
            seen.add(key)
            deduped.append(e)

    if len(deduped) > EventVerdictService.MAX_BATCH:
        raise HTTPException(
            status_code=400,
            detail=(
                f"批量研判上限为 {EventVerdictService.MAX_BATCH} 条，"
                f"当前去重后 {len(deduped)} 条"
            ),
        )

    svc = EventVerdictService()
    result = await svc.analyze_events(
        deduped,
        user=current_user,
        force=body.force,
        confidence_threshold=body.confidence_threshold,
    )
    return {"code": 0, "data": result, "message": "success"}
