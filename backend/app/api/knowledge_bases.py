"""知识库聚合端点 — GET /api/knowledge/bases.

L2 F3 方案 b：从已批准的知识草稿聚合知识库列表。
与 knowledge_draft.py 共享 /api/knowledge 前缀（子路径 `/drafts` vs `/bases` 不冲突）。

响应格式：统一信封 {"code": 0, "data": [...], "message": "success"}
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends

from app.models.knowledge_draft import KnowledgeDraft
from app.services.auth_service import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/bases")
def list_knowledge_bases(
    current_user: dict = Depends(get_current_user),
) -> dict:
    """获取所有知识库列表（聚合自已批准的知识草稿）.

    从 KnowledgeDraft.list_approved() 获取所有已批准草稿，
    每一条映射为 KnowledgeBase 格式：
      - kb_id: f"draft_{draft['id']}"（与 get_as_seed_entries() 保持一致）
      - name: draft['title']
      - embedding_model: "text-embedding-3-small"（系统默认）
      - vector_store: "Chroma"（系统默认）
      - doc_count: 1（每条草稿计为 1 篇文档）
      - updated_at: draft.get('reviewed_at') or draft.get('created_at')

    Returns:
        统一信封响应，data 为知识库列表.
    """
    drafts = KnowledgeDraft.list_approved()
    bases: list[dict[str, Any]] = []
    for draft in drafts:
        bases.append({
            "kb_id": f"draft_{draft['id']}",
            "name": draft.get("title", ""),
            "embedding_model": "text-embedding-3-small",
            "vector_store": "Chroma",
            "doc_count": 1,
            "updated_at": draft.get("reviewed_at") or draft.get("created_at"),
        })
    logger.info("List knowledge bases: %d bases from approved drafts", len(bases))
    return {"code": 0, "data": bases, "message": "success"}
