"""知识草稿 API — 管理员审核 AI 自动生成的知识条目.

提供草稿列表查询、批准（自动入库 ChromaDB）、拒绝接口。
批准时触发 ChromaDB 种子索引的重建，将已批准条目纳入向量检索。
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.models.knowledge_draft import KnowledgeDraft

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/drafts")
def list_drafts(status: Optional[str] = Query(None, description="按状态过滤：pending/approved/rejected")):
    """获取所有知识草稿列表，支持按状态过滤.

    - 不传 status 返回全部
    - status=pending 返回待审核
    - status=approved 返回已批准
    - status=rejected 返回已拒绝
    """
    if status and status not in ("pending", "approved", "rejected"):
        raise HTTPException(
            status_code=400,
            detail=f"无效的 status 值 '{status}'，有效值：pending / approved / rejected",
        )

    drafts = KnowledgeDraft.get_all(status=status)
    return {"code": 0, "data": drafts, "message": "success"}


@router.post("/drafts/{draft_id}/approve")
def approve_draft(draft_id: int):
    """批准知识草稿.

    批准后：
    1. 将草稿 status 更新为 'approved'
    2. 已批准的草稿在下次 ChromaDB 种子索引重建时自动纳入向量检索
    """
    try:
        draft = KnowledgeDraft.approve(draft_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # 批准后触发种子索引重建，将已批准条目纳入 ChromaDB 向量检索
    try:
        from app.services.knowledge_retriever import KnowledgeRetriever

        KnowledgeRetriever.rebuild_seed_index()
    except Exception as exc:
        logger.warning("批准后重建种子索引失败（不影响批准操作）: %s", exc)

    return {"code": 0, "data": draft, "message": "草稿已批准并入库"}


@router.post("/drafts/{draft_id}/reject")
def reject_draft(draft_id: int):
    """拒绝知识草稿.

    将草稿 status 更新为 'rejected'，该条目不会进入知识库.
    """
    try:
        draft = KnowledgeDraft.reject(draft_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"code": 0, "data": draft, "message": "草稿已拒绝"}
