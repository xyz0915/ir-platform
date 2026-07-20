"""知识库自进化 API（P2-H 第⑤批 T-H1）.

挂载于前缀 ``/api/kb``（main.py 统一注册，**不在本文件重复前缀**），
所有端点均经 ``Depends(get_current_user)`` 鉴权。

端点：
- ``POST   /api/kb/feedback``  提交反馈（误报 / 真阳性 / 抑制）
- ``GET    /api/kb/feedback``  列出反馈（可按类型 / 是否已沉淀过滤 + 分页）
- ``POST   /api/kb/evolve``    触发自进化（可选 feedback_id；缺省处理全部未沉淀反馈）
- ``GET    /api/kb/stats``     获取自进化统计与沉淀条目

设计说明（相对设计文档 §4.3 H 的合理对齐）：
设计文档原端点为 ``/api/knowledge/ingest-feedback`` 与 ``/api/knowledge/feedback``。
由于 ``knowledge_draft`` 路由已占用 ``/api/knowledge`` 前缀，本模块新建独立路由并以
``/api/kb`` 挂载，避免前缀重复与路径冲突，同时完整覆盖团队指令要求的 4 个端点语义。
"""

import logging
from typing import Optional

from fastapi import APIRouter, Body, Depends, Query, status as http_status

from app.models.kb_feedback import KbFeedback, VALID_FEEDBACK_TYPES
from app.services.auth_service import get_current_user
from app.services.kb_self_evolve import KbSelfEvolve

logger = logging.getLogger(__name__)
router = APIRouter()


def _svc() -> KbSelfEvolve:
    """构造自进化服务实例（轻量，每次请求新建，避免跨请求状态）."""
    return KbSelfEvolve()


@router.post("/feedback")
async def submit_feedback(
    payload: dict = Body(default={}),
    current_user: dict = Depends(get_current_user),
):
    """提交一条知识库反馈（误报 / 真阳性 / 抑制）.

    Body 字段：
        feedback_type: 必填，false_positive | true_positive | suppress
        rule_id / alert_id / event_id: 关联对象（可选）
        rule_name: 关联规则名（误报/抑制用于自动抑制，可选）
        host_id: 关联主机 ID（定向抑制，0 或省略表示全局）
        content: 反馈内容 / 分析师备注
    """
    feedback_type = payload.get("feedback_type")
    if feedback_type not in VALID_FEEDBACK_TYPES:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"feedback_type 必须为 {VALID_FEEDBACK_TYPES} 之一",
        )
    try:
        record = await _svc().ingest_feedback(payload, user=current_user)
    except ValueError as exc:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST, detail=str(exc)
        )
    return {
        "code": 0,
        "data": {
            "feedback_id": record["id"],
            "feedback_type": record["feedback_type"],
            "applied_to_kb": bool(record["applied_to_kb"]),
        },
        "message": "success",
    }


@router.get("/feedback")
def list_feedback(
    feedback_type: str = Query(None, description="按反馈类型过滤"),
    applied: int = Query(None, description="按是否已沉淀过滤：1=已沉淀, 0=未沉淀"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
):
    """列出反馈记录（支持类型 / 沉淀状态过滤与分页）."""
    try:
        result = KbFeedback.list(
            feedback_type=feedback_type,
            applied=applied,
            page=page,
            page_size=page_size,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("列出反馈失败: %s", exc)
        return {"code": -1, "data": {"items": [], "total": 0}, "message": str(exc)}
    return {"code": 0, "data": result, "message": "success"}


@router.post("/evolve")
async def evolve_knowledge(
    payload: dict = Body(default={}),
    current_user: dict = Depends(get_current_user),
):
    """触发知识库自进化：把反馈沉淀为抑制 + 知识草稿.

    Body 字段：
        feedback_id: 可选，指定单条反馈；省略则处理全部未沉淀反馈.

    Returns:
        ``{processed, applied, details}``.
    """
    feedback_id = payload.get("feedback_id")
    svc = _svc()
    try:
        if feedback_id:
            detail = await svc.process_feedback(int(feedback_id), user=current_user)
            applied = 1 if detail.get("applied_to_kb") else 0
            result = {"processed": 1, "applied": applied, "details": [detail]}
        else:
            result = await svc.evolve_all(user=current_user)
    except ValueError as exc:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail=str(exc)
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("自进化失败: %s", exc)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        )
    return {"code": 0, "data": result, "message": "success"}


@router.get("/stats")
def knowledge_stats(
    current_user: dict = Depends(get_current_user),
):
    """获取自进化统计与沉淀条目."""
    try:
        result = KbSelfEvolve().stats()
    except Exception as exc:  # noqa: BLE001
        logger.error("获取自进化统计失败: %s", exc)
        return {"code": -1, "data": {}, "message": str(exc)}
    return {"code": 0, "data": result, "message": "success"}
