"""知识库聚合端点 — GET /api/knowledge/bases.

P0 改造（记忆/RAG 页面真实数据化）：从「写死假元数据」改为聚合真实向量库统计
+ 已批准草稿信息。

数据来源：
- 真实向量库：`KnowledgeRetriever`（chromadb PersistentClient，collection=ir_rules，
  持久化 backend/data/chroma/）。`_get_collection()` / `_get_embedding_model()` 均
  fail-safe：chroma 或 embedding 模型不可用时返回 None，端点不抛异常。
- 草稿信息：`KnowledgeDraft.list_approved()`（knowledge_drafts 表 status='approved'）。

响应格式：统一信封 {"code": 0, "data": {...}, "message": "success"}
  data = {
    "bases":  [ ... ],   // 真实向量库条目（collection 可用时 1 条 ir_rules，否则 []）
    "stats":  { ... },   // 向量库统计（doc_count / embedding_model / collection_ready ...）
    "drafts": [ ... ],   // 已批准草稿精简列表（id/title/category/severity/reviewed_at）
  }
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends

from app.models.knowledge_draft import KnowledgeDraft
from app.services.auth_service import get_current_user
from app.services.knowledge_retriever import (
    COLLECTION_NAME,
    EMBEDDING_MODEL_NAME,
    _get_collection,
    _get_embedding_model,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _read_index_updated_at(collection: Any) -> str:
    """从 chroma collection metadata 读取最近一次索引/重建时间（fail-safe）.

    服务层（knowledge_retriever）目前没有独立的 rebuild 时间戳记录机制，
    因此优先尝试 collection.metadata 中的 `index_updated_at` / `updated_at`
    （若未来 rebuild_seed_index 写入该字段即可自动生效）；读不到返回空串。

    Args:
        collection: chromadb collection 对象，可能为 None。

    Returns:
        ISO 时间字符串，或空串 ''。
    """
    if collection is None:
        return ""
    try:
        metadata = collection.metadata or {}
        if not isinstance(metadata, dict):
            return ""
        ts = metadata.get("index_updated_at") or metadata.get("updated_at") or ""
        return str(ts) if ts else ""
    except Exception as exc:
        logger.warning("Failed to read collection metadata index_updated_at: %s", exc)
        return ""


@router.get("/bases")
def list_knowledge_bases(
    current_user: dict = Depends(get_current_user),
) -> dict:
    """获取知识库聚合信息（真实向量库统计 + 已批准草稿）.

    P0 语义修正：
    - 不再把「每条已批准草稿」映射为「一个假知识库」；
    - `doc_count` 读取真实 Chroma collection（ir_rules）文档数；
    - `embedding_model` 读取真实加载的模型名（knowledge_retriever.EMBEDDING_MODEL_NAME）；
    - chroma 不可用时保持 fail-safe：doc_count=0、collection_ready=false，不抛异常。

    Returns:
        统一信封响应，data 为 {bases, stats, drafts}.
    """
    # ── 1) 已批准草稿（fail-safe：草稿表异常不影响端点） ──
    approved_drafts: list[dict[str, Any]] = []
    try:
        approved_drafts = KnowledgeDraft.list_approved() or []
    except Exception as exc:
        logger.warning("Failed to load approved drafts: %s", exc)

    # ── 2) 真实向量库统计（fail-safe：chroma 不可用不抛异常） ──
    collection = None
    doc_count = 0
    embedding_model = "n/a"
    index_updated_at = ""
    try:
        collection = _get_collection()
        if collection is not None:
            doc_count = int(collection.count() or 0)
        model = _get_embedding_model()
        if model is not None:
            embedding_model = EMBEDDING_MODEL_NAME
        index_updated_at = _read_index_updated_at(collection)
    except Exception as exc:
        logger.warning("Failed to read vector store stats: %s", exc)
        collection = None
        doc_count = 0
        embedding_model = "n/a"
        index_updated_at = ""

    collection_ready = collection is not None

    # ── 3) 真实向量库条目（仅当 collection 可用；否则返回 []，不编造假数据） ──
    bases: list[dict[str, Any]] = []
    if collection_ready:
        bases.append({
            "kb_id": COLLECTION_NAME,
            "name": "应急知识库(ir_rules)",
            "doc_count": doc_count,
            "embedding_model": embedding_model,
            "vector_store": "Chroma",
            "updated_at": index_updated_at,
            "index_updated_at": index_updated_at,
        })

    # ── 4) 聚合统计 ──
    stats: dict[str, Any] = {
        "collection": COLLECTION_NAME,
        "doc_count": doc_count,
        "embedding_model": embedding_model,
        "vector_store": "Chroma",
        "index_updated_at": index_updated_at,
        "approved_drafts": len(approved_drafts),
        "collection_ready": collection_ready,
    }

    # ── 5) 已批准草稿精简列表 ──
    drafts: list[dict[str, Any]] = [
        {
            "id": draft["id"],
            "title": draft.get("title", ""),
            "category": draft.get("category", ""),
            "severity": draft.get("severity", "medium"),
            "reviewed_at": draft.get("reviewed_at") or draft.get("created_at"),
        }
        for draft in approved_drafts
    ]

    logger.info(
        "List knowledge bases: collection_ready=%s, doc_count=%d, approved_drafts=%d",
        collection_ready,
        doc_count,
        len(drafts),
    )
    return {
        "code": 0,
        "data": {
            "bases": bases,
            "stats": stats,
            "drafts": drafts,
        },
        "message": "success",
    }
