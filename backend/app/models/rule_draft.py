"""规则草稿模型 CRUD（P0-B）.

对应 ``rule_drafts`` 表。草稿是 AI 生成的候选检测规则，经过 DSL 校验、影子运行，
最终由管理员审批启用（pending_review -> enabled）或驳回（rejected）。

该模型与 ``Rule`` 模型解耦：草稿生命周期完全独立，仅在管理员审批通过后才镜像/
升级为 ``rules`` 表中的正式规则。
"""

import json
import logging
from typing import Any, Dict, List, Optional

from app.database import get_connection

logger = logging.getLogger(__name__)


class RuleDraft:
    """规则草稿数据访问层."""

    # 状态常量
    STATUS_DRAFT = "draft"
    STATUS_SHADOW = "shadow"
    STATUS_PENDING_REVIEW = "pending_review"
    STATUS_ENABLED = "enabled"
    STATUS_REJECTED = "rejected"
    VALID_STATUSES = [
        STATUS_DRAFT,
        STATUS_SHADOW,
        STATUS_PENDING_REVIEW,
        STATUS_ENABLED,
        STATUS_REJECTED,
    ]

    # ── 创建 ────────────────────────────────────────────────────────────
    @staticmethod
    def create(
        name: str,
        rule_type: str,
        condition: Dict[str, Any],
        category: Optional[str] = None,
        severity: str = "medium",
        label: Optional[str] = None,
        rationale: Optional[str] = None,
        expected_fields: Optional[List[str]] = None,
        confidence: Optional[float] = None,
        source: str = "ai",
        generated_by: Optional[int] = None,
        dsl: Optional[str] = None,
        tuning_history: Optional[List[Dict[str, Any]]] = None,
        parent_draft_id: Optional[int] = None,
        status: str = STATUS_DRAFT,
        tuned_version: int = 0,
    ) -> Dict[str, Any]:
        """创建一条规则草稿."""
        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO rule_drafts
                    (name, category, rule_type, condition_json, severity, label,
                     status, source, generated_by, rationale, expected_fields,
                     confidence, dsl, tuning_history_json, parent_draft_id,
                     tuned_version, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                (
                    name,
                    category,
                    rule_type,
                    json.dumps(condition, ensure_ascii=False),
                    severity,
                    label,
                    status,
                    source,
                    generated_by,
                    rationale,
                    json.dumps(expected_fields or [], ensure_ascii=False),
                    confidence,
                    dsl,
                    json.dumps(tuning_history or [], ensure_ascii=False),
                    parent_draft_id,
                    tuned_version,
                ),
            )
            draft_id = cursor.lastrowid
        return RuleDraft.get_by_id(draft_id)

    # ── 读取 ────────────────────────────────────────────────────────────
    @staticmethod
    def get_by_id(draft_id: int) -> Optional[Dict[str, Any]]:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM rule_drafts WHERE id = ?", (draft_id,)
            ).fetchone()
            if row:
                return RuleDraft._normalize(dict(row))
            return None

    @staticmethod
    def get_by_name(name: str) -> Optional[Dict[str, Any]]:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM rule_drafts WHERE name = ?", (name,)
            ).fetchone()
            if row:
                return RuleDraft._normalize(dict(row))
            return None

    @staticmethod
    def list(
        status: Optional[str] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Dict[str, Any]:
        """分页列出草稿，可选按状态过滤."""
        with get_connection() as conn:
            if status:
                total = conn.execute(
                    "SELECT COUNT(*) AS cnt FROM rule_drafts WHERE status = ?", (status,)
                ).fetchone()["cnt"]
                rows = conn.execute(
                    "SELECT * FROM rule_drafts WHERE status = ? "
                    "ORDER BY created_at DESC LIMIT ? OFFSET ?",
                    (status, page_size, (page - 1) * page_size),
                ).fetchall()
            else:
                total = conn.execute("SELECT COUNT(*) AS cnt FROM rule_drafts").fetchone()["cnt"]
                rows = conn.execute(
                    "SELECT * FROM rule_drafts "
                    "ORDER BY created_at DESC LIMIT ? OFFSET ?",
                    (page_size, (page - 1) * page_size),
                ).fetchall()
            items = [RuleDraft._normalize(dict(r)) for r in rows]
        return {"items": items, "total": total}

    # ── 更新 ────────────────────────────────────────────────────────────
    @staticmethod
    def update(
        draft_id: int,
        status: Optional[str] = None,
        shadow_hit_count: Optional[int] = None,
        reviewed_by: Optional[int] = None,
        reject_reason: Optional[str] = None,
        rationale: Optional[str] = None,
        condition: Optional[Dict[str, Any]] = None,
        severity: Optional[str] = None,
        label: Optional[str] = None,
        confidence: Optional[float] = None,
        false_positive_count: Optional[int] = None,
        hit_count: Optional[int] = None,
        tuned_version: Optional[int] = None,
        tuning_history: Optional[List[Dict[str, Any]]] = None,
        expected_fields: Optional[List[str]] = None,
        sample_hits: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[Dict[str, Any]]:
        """更新草稿字段（仅传入的非空字段会被更新）."""
        fields: List[str] = []
        params: List[Any] = []
        if status is not None:
            fields.append("status = ?")
            params.append(status)
        if shadow_hit_count is not None:
            fields.append("shadow_hit_count = ?")
            params.append(shadow_hit_count)
        if reviewed_by is not None:
            fields.append("reviewed_by = ?")
            params.append(reviewed_by)
        if reject_reason is not None:
            fields.append("reject_reason = ?")
            params.append(reject_reason)
        if rationale is not None:
            fields.append("rationale = ?")
            params.append(rationale)
        if condition is not None:
            fields.append("condition_json = ?")
            params.append(json.dumps(condition, ensure_ascii=False))
        if severity is not None:
            fields.append("severity = ?")
            params.append(severity)
        if label is not None:
            fields.append("label = ?")
            params.append(label)
        if confidence is not None:
            fields.append("confidence = ?")
            params.append(confidence)
        if false_positive_count is not None:
            fields.append("false_positive_count = ?")
            params.append(false_positive_count)
        if hit_count is not None:
            fields.append("hit_count = ?")
            params.append(hit_count)
        if tuned_version is not None:
            fields.append("tuned_version = ?")
            params.append(tuned_version)
        if tuning_history is not None:
            fields.append("tuning_history_json = ?")
            params.append(json.dumps(tuning_history, ensure_ascii=False))
        if expected_fields is not None:
            fields.append("expected_fields = ?")
            params.append(json.dumps(expected_fields, ensure_ascii=False))
        if sample_hits is not None:
            fields.append("sample_hits_json = ?")
            params.append(json.dumps(sample_hits, ensure_ascii=False))
        if not fields:
            return RuleDraft.get_by_id(draft_id)
        fields.append("updated_at = datetime('now')")
        params.append(draft_id)
        with get_connection() as conn:
            conn.execute(
                f"UPDATE rule_drafts SET {', '.join(fields)} WHERE id = ?", params
            )
        return RuleDraft.get_by_id(draft_id)

    # ── 删除 ────────────────────────────────────────────────────────────
    @staticmethod
    def delete(draft_id: int) -> bool:
        with get_connection() as conn:
            cur = conn.execute("DELETE FROM rule_drafts WHERE id = ?", (draft_id,))
            return cur.rowcount > 0

    # ── 内部工具 ─────────────────────────────────────────────────────────
    @staticmethod
    def _normalize(row: Dict[str, Any]) -> Dict[str, Any]:
        """将 JSON 字符串列反序列化为对象，便于接口返回."""
        cj = row.get("condition_json")
        if isinstance(cj, str) and cj:
            try:
                row["condition"] = json.loads(cj)
            except (json.JSONDecodeError, TypeError):
                row["condition"] = {}
        elif cj is None:
            row["condition"] = {}

        ef = row.get("expected_fields")
        if isinstance(ef, str) and ef:
            try:
                row["expected_fields"] = json.loads(ef)
            except (json.JSONDecodeError, TypeError):
                row["expected_fields"] = []
        elif ef is None:
            row["expected_fields"] = []

        th = row.get("tuning_history_json")
        if isinstance(th, str) and th:
            try:
                row["tuning_history"] = json.loads(th)
            except (json.JSONDecodeError, TypeError):
                row["tuning_history"] = []
        elif th is None:
            row["tuning_history"] = []

        sh = row.get("sample_hits_json")
        if isinstance(sh, str) and sh:
            try:
                row["sample_hits"] = json.loads(sh)
            except (json.JSONDecodeError, TypeError):
                row["sample_hits"] = []
        elif sh is None:
            row["sample_hits"] = []

        return row
