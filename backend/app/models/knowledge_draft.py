"""知识草稿模型 — knowledge_drafts 表 CRUD 操作.

AI 分析主机时发现知识库未覆盖的新威胁模式，自动生成知识条目草稿，
经管理员审核后入库到 ChromaDB。闭环：分析 → 发现未知 → 自动建议 → 审核 → 入库。
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from app.database import get_connection

logger = logging.getLogger(__name__)


class KnowledgeDraft:
    """AI 自动生成的知识条目草稿模型.

    管理 AI 分析过程中发现的新威胁模式草稿，支持创建、查询、审批、拒绝操作.
    """

    @staticmethod
    def create(
        host_id: Optional[str] = None,
        analysis_report_id: Optional[int] = None,
        title: str = "",
        description: str = "",
        category: str = "auto",
        severity: str = "medium",
        mitre_attack: Optional[str] = None,
        pattern: Optional[str] = None,
        source: str = "ai_suggest",
        raw_ioc: Optional[str] = None,
    ) -> dict:
        """创建新的知识条目草稿.

        Args:
            host_id: 来源主机 ID（字符串，可为 None）.
            analysis_report_id: 来源分析报告 ID.
            title: 标题（如"新增恶意软件 XYZ"）.
            description: 详细描述.
            category: mitre_attack / c2_framework / malware / auto.
            severity: low / medium / high / critical.
            mitre_attack: MITRE 技术编号（可选）.
            pattern: 检测关键词（逗号分隔）.
            source: ai_suggest / manual / external.
            raw_ioc: 原始 IOC 数据（JSON string）.

        Returns:
            创建的草稿字典.
        """
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO knowledge_drafts
                (host_id, analysis_report_id, title, description, category,
                 severity, mitre_attack, pattern, status, source, raw_ioc, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)
                """,
                (
                    host_id,
                    analysis_report_id,
                    title,
                    description,
                    category,
                    severity,
                    mitre_attack,
                    pattern,
                    source,
                    raw_ioc,
                    now,
                ),
            )
            draft_id = cursor.lastrowid
        logger.info(
            "Knowledge draft created: id=%s, title=%s, category=%s, severity=%s",
            draft_id, title, category, severity,
        )
        return KnowledgeDraft.get_by_id(draft_id)

    @staticmethod
    def get_by_id(draft_id: int) -> Optional[dict]:
        """根据 ID 获取草稿详情."""
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM knowledge_drafts WHERE id = ?", (draft_id,)
            ).fetchone()
            return dict(row) if row else None

    @staticmethod
    def get_all(status: Optional[str] = None) -> list[dict]:
        """获取所有草稿列表，可按 status 过滤.

        Args:
            status: 过滤状态（pending / approved / rejected），None 则返回全部.

        Returns:
            草稿字典列表，按 created_at 降序排列.
        """
        with get_connection() as conn:
            if status:
                rows = conn.execute(
                    """SELECT * FROM knowledge_drafts
                       WHERE status = ?
                       ORDER BY created_at DESC""",
                    (status,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM knowledge_drafts ORDER BY created_at DESC"
                ).fetchall()
            return [dict(row) for row in rows]

    @staticmethod
    def list_pending() -> list[dict]:
        """获取所有待审核的草稿."""
        return KnowledgeDraft.get_all(status="pending")

    @staticmethod
    def list_approved() -> list[dict]:
        """获取所有已批准的草稿（供知识库种子数据加载使用）."""
        return KnowledgeDraft.get_all(status="approved")

    @staticmethod
    def approve(draft_id: int) -> Optional[dict]:
        """批准草稿：更新 status=approved，记录审核时间.

        批准后的草稿条目会在下次 _build_seed_index() 时作为额外种子源被索引到 ChromaDB.

        Args:
            draft_id: 草稿 ID.

        Returns:
            更新后的草稿字典.

        Raises:
            ValueError: 草稿不存在或状态不是 pending.
        """
        draft = KnowledgeDraft.get_by_id(draft_id)
        if draft is None:
            raise ValueError(f"知识草稿 {draft_id} 不存在")
        if draft.get("status") != "pending":
            raise ValueError(
                f"知识草稿 {draft_id} 状态为 {draft.get('status')}，无法批准（仅 pending 可批准）"
            )

        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        with get_connection() as conn:
            conn.execute(
                """UPDATE knowledge_drafts
                   SET status = 'approved', reviewed_at = ?
                   WHERE id = ?""",
                (now, draft_id),
            )
        logger.info("Knowledge draft %d approved: %s", draft_id, draft.get("title"))
        return KnowledgeDraft.get_by_id(draft_id)

    @staticmethod
    def reject(draft_id: int) -> Optional[dict]:
        """拒绝草稿：更新 status=rejected，记录审核时间.

        Args:
            draft_id: 草稿 ID.

        Returns:
            更新后的草稿字典.

        Raises:
            ValueError: 草稿不存在或状态不是 pending.
        """
        draft = KnowledgeDraft.get_by_id(draft_id)
        if draft is None:
            raise ValueError(f"知识草稿 {draft_id} 不存在")
        if draft.get("status") != "pending":
            raise ValueError(
                f"知识草稿 {draft_id} 状态为 {draft.get('status')}，无法拒绝（仅 pending 可拒绝）"
            )

        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        with get_connection() as conn:
            conn.execute(
                """UPDATE knowledge_drafts
                   SET status = 'rejected', reviewed_at = ?
                   WHERE id = ?""",
                (now, draft_id),
            )
        logger.info("Knowledge draft %d rejected: %s", draft_id, draft.get("title"))
        return KnowledgeDraft.get_by_id(draft_id)

    @staticmethod
    def get_as_seed_entries() -> list[dict]:
        """将已批准的草稿转换为与 ALL_SEED_KNOWLEDGE 兼容的种子数据格式.

        Returns:
            已批准草稿的种子格式列表（含 name/description/category/severity/pattern/id 字段）.
        """
        approved = KnowledgeDraft.list_approved()
        seed_entries: list[dict] = []
        for draft in approved:
            entry: dict = {
                "id": f"draft_{draft['id']}",
                "name": draft.get("title", ""),
                "description": draft.get("description", ""),
                "category": draft.get("category", "auto"),
                "severity": draft.get("severity", "medium"),
                "pattern": draft.get("pattern", ""),
            }
            if draft.get("mitre_attack"):
                entry["mitre_attack"] = draft["mitre_attack"]
            if draft.get("tactic"):
                entry["tactic"] = draft.get("tactic", "")
            seed_entries.append(entry)
        logger.info(
            "Loaded %d approved draft(s) as seed entries", len(seed_entries),
        )
        return seed_entries
