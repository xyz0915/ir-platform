"""IncidentCluster 模型 — 语义归并后的真实事件簇 CRUD（§4.1 / T-D1 / P1-D）.

语义级跨资产告警降噪 2.0 把 `security_events` 中经 AI 研判为可疑/真实的事件，
聚类为"真实事件簇（Incident Cluster）"，并落库到 `incident_clusters` 表，
供前端事件归并视图（IncidentClusterView）分页检索与详情查看。
"""

import json
import logging
import sqlite3
import uuid
from typing import Any, Optional

from app.database import get_connection

logger = logging.getLogger(__name__)


class IncidentCluster:
    """语义归并后的真实事件簇（Incident Cluster）."""

    VALID_SEVERITIES = ("low", "medium", "high", "critical")

    # ────────────────────────────────────────────────────────────────
    # 创建
    # ────────────────────────────────────────────────────────────────
    @classmethod
    def create(
        cls,
        title: str,
        severity: str = "medium",
        confidence: float = 0.0,
        member_event_ids: Optional[list] = None,
        host_ids: Optional[list] = None,
        summary: str = "",
        ai_verdict_agg: Optional[dict] = None,
        cluster_id: Optional[str] = None,
    ) -> str:
        """写入一条事件簇记录，返回其 cluster_id。

        Args:
            title: 簇标题。
            severity: 严重度（low/medium/high/critical）。
            confidence: 聚类置信度 0~1。
            member_event_ids: 成员 security_events.id 列表。
            host_ids: 涉及主机 id 列表。
            summary: 一句话研判摘要。
            ai_verdict_agg: 聚合的 ai_verdict 标签统计（JSON）。
            cluster_id: 可选指定；缺省自动生成。

        Returns:
            生成的 cluster_id 字符串。
        """
        cluster_id = cluster_id or f"ic-{uuid.uuid4().hex[:12]}"
        member_event_ids = member_event_ids or []
        host_ids = host_ids or []
        ai_verdict_agg = ai_verdict_agg or {}
        if severity not in cls.VALID_SEVERITIES:
            severity = "medium"
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO incident_clusters
                    (cluster_id, title, severity, confidence,
                     member_event_ids, host_ids, summary, ai_verdict_agg,
                     created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
                """,
                (
                    cluster_id,
                    title,
                    severity,
                    float(confidence),
                    json.dumps(member_event_ids, ensure_ascii=False),
                    json.dumps(host_ids, ensure_ascii=False),
                    summary,
                    json.dumps(ai_verdict_agg, ensure_ascii=False),
                ),
            )
            conn.commit()
        return cluster_id

    # ────────────────────────────────────────────────────────────────
    # 列表（筛选 + 分页）
    # ────────────────────────────────────────────────────────────────
    @classmethod
    def list(
        cls,
        severity: Optional[str] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> dict:
        """分页查询事件簇。

        Returns:
            ``{"items": [...], "total": N, "page": int, "page_size": int}``
        """
        page = max(1, int(page))
        page_size = max(1, min(int(page_size), 200))
        offset = (page - 1) * page_size
        conditions: list[str] = []
        params: list[Any] = []
        if severity:
            conditions.append("severity = ?")
            params.append(severity)
        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        with get_connection() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) AS cnt FROM incident_clusters{where}", params
            ).fetchone()["cnt"]
            rows = conn.execute(
                f"SELECT * FROM incident_clusters{where} "
                f"ORDER BY created_at DESC LIMIT ? OFFSET ?",
                params + [page_size, offset],
            ).fetchall()
        items = [cls._row_to_dict(r) for r in rows]
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    # ────────────────────────────────────────────────────────────────
    # 单条查询 / 删除
    # ────────────────────────────────────────────────────────────────
    @classmethod
    def get(cls, cluster_id: str) -> Optional[dict]:
        """按 cluster_id 查询单条事件簇。"""
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM incident_clusters WHERE cluster_id = ?", (cluster_id,)
            ).fetchone()
        return cls._row_to_dict(row) if row else None

    @classmethod
    def delete(cls, cluster_id: str) -> bool:
        """按 cluster_id 删除事件簇，返回是否删除成功。"""
        with get_connection() as conn:
            cur = conn.execute(
                "DELETE FROM incident_clusters WHERE cluster_id = ?", (cluster_id,)
            )
            conn.commit()
            return cur.rowcount > 0

    # ────────────────────────────────────────────────────────────────
    # 行转换（JSON 反序列化）
    # ────────────────────────────────────────────────────────────────
    @staticmethod
    def _row_to_dict(row) -> dict:
        """sqlite3.Row → dict，并对 JSON 字段做反序列化。"""
        d = dict(row)
        for field in ("member_event_ids", "host_ids", "ai_verdict_agg"):
            if field in d and isinstance(d[field], str):
                try:
                    d[field] = json.loads(d[field])
                except (json.JSONDecodeError, TypeError):
                    d[field] = [] if field in ("member_event_ids", "host_ids") else {}
        return d
