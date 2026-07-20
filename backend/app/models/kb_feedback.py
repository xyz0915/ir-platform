"""知识库自进化反馈模型 — kb_feedback 表 CRUD（P2-H 第⑤批）.

分析师对告警/规则给出的反馈（误报 / 真阳性 / 抑制），是知识库自进化闭环的入口。
每条反馈记录后续可由 :class:`app.services.kb_self_evolve.KbSelfEvolve` 消费，沉淀为：
- ``rule_suppression``（针对误报/抑制，自动抑制规则）
- ``knowledge_drafts``（approved，写入向量知识库）

设计说明（相对设计文档 §4.1⑦ 的合理扩展）：
设计文档原始 ``kb_feedback`` 仅含 ``is_false_positive`` / ``ingested`` 布尔位。本实现采用更丰富的
``feedback_type`` 枚举（false_positive / true_positive / suppress）作为单一事实来源，并保留
``is_false_positive`` / ``applied_to_kb``（即设计文档的 ``ingested``）两个派生兼容列，
同时补齐 ``rule_id`` / ``alert_id`` / ``source_user`` / ``kb_entry_id`` 等团队指令要求的字段。
"""

import logging
from typing import Any, Dict, List, Optional

from app.database import get_connection

logger = logging.getLogger(__name__)

# 反馈类型常量
FEEDBACK_TYPE_FALSE_POSITIVE = "false_positive"
FEEDBACK_TYPE_TRUE_POSITIVE = "true_positive"
FEEDBACK_TYPE_SUPPRESS = "suppress"
VALID_FEEDBACK_TYPES = (
    FEEDBACK_TYPE_FALSE_POSITIVE,
    FEEDBACK_TYPE_TRUE_POSITIVE,
    FEEDBACK_TYPE_SUPPRESS,
)


class KbFeedback:
    """知识库自进化反馈数据访问层."""

    # ── 创建 ────────────────────────────────────────────────────────────
    @staticmethod
    def create(
        feedback_type: str,
        rule_id: Optional[int] = None,
        alert_id: Optional[int] = None,
        event_id: Optional[str] = None,
        rule_name: Optional[str] = None,
        host_id: Optional[int] = None,
        content: Optional[str] = None,
        source_user: Optional[str] = None,
    ) -> Dict[str, Any]:
        """创建一条知识库反馈记录.

        Args:
            feedback_type: 反馈类型（false_positive / true_positive / suppress）.
            rule_id: 关联规则 ID（可选）.
            alert_id: 关联告警 ID（可选）.
            event_id: 关联事件 ID（可选）.
            rule_name: 关联规则名（用于自动抑制，可选）.
            host_id: 关联主机 ID（用于定向抑制，0 表示全局）.
            content: 反馈内容 / 分析师备注.
            source_user: 提交反馈的用户名（用于审计溯源）.

        Returns:
            创建的反馈记录字典.
        """
        if feedback_type not in VALID_FEEDBACK_TYPES:
            raise ValueError(
                f"feedback_type 必须为 {VALID_FEEDBACK_TYPES} 之一，收到: {feedback_type}"
            )
        is_false_positive = 1 if feedback_type == FEEDBACK_TYPE_FALSE_POSITIVE else 0
        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO kb_feedback
                    (feedback_type, is_false_positive, rule_id, alert_id, event_id,
                     rule_name, host_id, content, source_user, applied_to_kb,
                     kb_entry_id, suppression_id, knowledge_draft_id, entry_ref, summary)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, NULL, NULL, NULL, NULL, NULL)
                """,
                (
                    feedback_type,
                    is_false_positive,
                    rule_id,
                    alert_id,
                    event_id,
                    rule_name,
                    host_id,
                    content,
                    source_user,
                ),
            )
            feedback_id = cursor.lastrowid
        logger.info(
            "KbFeedback created: id=%s, type=%s, rule_name=%s",
            feedback_id, feedback_type, rule_name,
        )
        return KbFeedback.get_by_id(feedback_id)

    # ── 读取 ────────────────────────────────────────────────────────────
    @staticmethod
    def get_by_id(feedback_id: int) -> Optional[Dict[str, Any]]:
        """根据 ID 获取反馈记录."""
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM kb_feedback WHERE id = ?", (feedback_id,)
            ).fetchone()
            return KbFeedback._normalize(dict(row)) if row else None

    @staticmethod
    def list(
        feedback_type: Optional[str] = None,
        applied: Optional[int] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Dict[str, Any]:
        """分页列出反馈，可按类型与是否已沉淀过滤.

        Args:
            feedback_type: 按反馈类型过滤（可选）.
            applied: 按是否已沉淀过滤（1=已沉淀, 0=未沉淀, None=全部）.
            page: 页码（从 1 开始）.
            page_size: 每页大小.

        Returns:
            ``{"items": [...], "total": int, "page": int, "page_size": int}``.
        """
        conditions: List[str] = []
        params: List[Any] = []
        if feedback_type:
            conditions.append("feedback_type = ?")
            params.append(feedback_type)
        if applied is not None:
            conditions.append("applied_to_kb = ?")
            params.append(1 if applied else 0)
        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""

        with get_connection() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) AS cnt FROM kb_feedback{where}", params
            ).fetchone()["cnt"]
            rows = conn.execute(
                f"SELECT * FROM kb_feedback{where} "
                f"ORDER BY created_at DESC LIMIT ? OFFSET ?",
                [*params, page_size, (page - 1) * page_size],
            ).fetchall()
        return {
            "items": [KbFeedback._normalize(dict(r)) for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    @staticmethod
    def list_unapplied(limit: int = 1000) -> List[Dict[str, Any]]:
        """列出所有尚未沉淀到知识库的反馈（供自进化批量处理）."""
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM kb_feedback WHERE applied_to_kb = 0 "
                "ORDER BY created_at ASC LIMIT ?",
                (limit,),
            ).fetchall()
        return [KbFeedback._normalize(dict(r)) for r in rows]

    # ── 更新 ────────────────────────────────────────────────────────────
    @staticmethod
    def mark_applied(
        feedback_id: int,
        kb_entry_id: Optional[str] = None,
        suppression_id: Optional[int] = None,
        knowledge_draft_id: Optional[int] = None,
        entry_ref: Optional[str] = None,
        summary: Optional[str] = None,
    ) -> bool:
        """标记反馈已沉淀到知识库，并回填关联 ID.

        Args:
            feedback_id: 反馈 ID.
            kb_entry_id: 沉淀条目引用（如 ``draft_123``）.
            suppression_id: 生成的抑制记录 ID.
            knowledge_draft_id: 生成的知识草稿 ID.
            entry_ref: 向量库 entry_ref.
            summary: 沉淀摘要.

        Returns:
            是否更新成功.
        """
        try:
            with get_connection() as conn:
                conn.execute(
                    """
                    UPDATE kb_feedback
                       SET applied_to_kb = 1,
                           kb_entry_id = ?,
                           suppression_id = ?,
                           knowledge_draft_id = ?,
                           entry_ref = ?,
                           summary = ?
                     WHERE id = ?
                    """,
                    (
                        kb_entry_id,
                        suppression_id,
                        knowledge_draft_id,
                        entry_ref,
                        summary,
                        feedback_id,
                    ),
                )
            logger.info("KbFeedback %s marked applied_to_kb", feedback_id)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error("标记反馈 %s 沉淀失败: %s", feedback_id, exc)
            return False

    # ── 统计 ────────────────────────────────────────────────────────────
    @staticmethod
    def get_stats() -> Dict[str, Any]:
        """返回反馈与沉淀统计."""
        with get_connection() as conn:
            total = conn.execute("SELECT COUNT(*) FROM kb_feedback").fetchone()[0]
            applied = conn.execute(
                "SELECT COUNT(*) FROM kb_feedback WHERE applied_to_kb = 1"
            ).fetchone()[0]
            fp = conn.execute(
                "SELECT COUNT(*) FROM kb_feedback WHERE feedback_type = 'false_positive'"
            ).fetchone()[0]
            suppress = conn.execute(
                "SELECT COUNT(*) FROM kb_feedback WHERE feedback_type = 'suppress'"
            ).fetchone()[0]
            tp = conn.execute(
                "SELECT COUNT(*) FROM kb_feedback WHERE feedback_type = 'true_positive'"
            ).fetchone()[0]
            deposits = conn.execute(
                """
                SELECT id, feedback_type, rule_name, kb_entry_id, suppression_id,
                       knowledge_draft_id, summary, created_at
                  FROM kb_feedback
                 WHERE applied_to_kb = 1
                 ORDER BY created_at DESC
                 LIMIT 20
                """
            ).fetchall()
        return {
            "total": total,
            "applied": applied,
            "unapplied": total - applied,
            "false_positive": fp,
            "suppress": suppress,
            "true_positive": tp,
            "deposits": [KbFeedback._normalize(dict(r)) for r in deposits],
        }

    # ── 内部工具 ────────────────────────────────────────────────────────
    @staticmethod
    def _normalize(row: Dict[str, Any]) -> Dict[str, Any]:
        """将行中的整数标志位转换为 Python bool，便于前端/调用方使用."""
        row = dict(row)
        row["is_false_positive"] = bool(row.get("is_false_positive"))
        row["applied_to_kb"] = bool(row.get("applied_to_kb"))
        return row
