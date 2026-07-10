"""Ioc 数据模型 — IOC 指标管理 CRUD（T-P1-4）.

仅负责 IOC 的管理与入库，不参与引擎匹配逻辑（list 类规则仍使用自身 condition.values）。
"""

import json
import logging
from typing import Any, Optional

from app.database import get_connection

logger = logging.getLogger(__name__)


class Ioc:
    """IOC 指标数据模型."""

    @staticmethod
    def create(
        ioc_type: str,
        ioc_value: str,
        source: str = "user",
        description: Optional[str] = None,
        enabled: bool = True,
    ) -> dict:
        """创建单条 IOC."""
        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO iocs (ioc_type, ioc_value, source, description, enabled)
                VALUES (?, ?, ?, ?, ?)
                """,
                (ioc_type, ioc_value, source, description, 1 if enabled else 0),
            )
            ioc_id = cursor.lastrowid
        return Ioc.get_by_id(ioc_id)

    @staticmethod
    def get_by_id(ioc_id: int) -> Optional[dict]:
        """根据 ID 获取 IOC."""
        with get_connection() as conn:
            row = conn.execute("SELECT * FROM iocs WHERE id = ?", (ioc_id,)).fetchone()
            if row:
                result = dict(row)
                result["enabled"] = bool(result.get("enabled"))
                return result
            return None

    @staticmethod
    def list(ioc_type: Optional[str] = None) -> list:
        """获取 IOC 列表（可按类型筛选）."""
        with get_connection() as conn:
            query = "SELECT * FROM iocs WHERE 1=1"
            params: list = []
            if ioc_type:
                query += " AND ioc_type = ?"
                params.append(ioc_type)
            query += " ORDER BY ioc_type, id"
            rows = conn.execute(query, params).fetchall()
            results = []
            for row in rows:
                item = dict(row)
                item["enabled"] = bool(item.get("enabled"))
                results.append(item)
            return results

    @staticmethod
    def update(
        ioc_id: int,
        enabled: Optional[bool] = None,
        description: Optional[str] = None,
        source: Optional[str] = None,
    ) -> Optional[dict]:
        """更新单条 IOC（部分字段更新，仅传入非 None 的字段）.

        支持更新字段：enabled / description / source。
        未传入（None）的字段保持原值不变。

        Args:
            ioc_id: IOC 主键.
            enabled: 是否启用（True/False 二选一）.
            description: 描述（可置空字符串）.
            source: 来源标识.

        Returns:
            更新后的 IOC 字典；若 ID 不存在则返回 None.
        """
        existing = Ioc.get_by_id(ioc_id)
        if not existing:
            return None

        fields: list = []
        params: list = []
        if enabled is not None:
            fields.append("enabled = ?")
            params.append(1 if enabled else 0)
        if description is not None:
            fields.append("description = ?")
            params.append(description)
        if source is not None:
            fields.append("source = ?")
            params.append(source)

        if not fields:
            # 无字段可更新，直接返回原记录
            return existing

        params.append(ioc_id)
        with get_connection() as conn:
            conn.execute(
                f"UPDATE iocs SET {', '.join(fields)} WHERE id = ?",
                params,
            )
        return Ioc.get_by_id(ioc_id)

    @staticmethod
    def delete(ioc_id: int) -> bool:
        """删除 IOC."""
        with get_connection() as conn:
            conn.execute("DELETE FROM iocs WHERE id = ?", (ioc_id,))
            return True

    @staticmethod
    def batch_create(items: list) -> int:
        """批量插入 IOC（去重：相同 ioc_type+ioc_value 已存在则跳过）.

        Args:
            items: 列表，每项 {ioc_type, ioc_value, source?, description?, enabled?}.

        Returns:
            实际插入条数.
        """
        inserted = 0
        with get_connection() as conn:
            existing = conn.execute("SELECT ioc_type, ioc_value FROM iocs").fetchall()
            seen = {(r["ioc_type"], r["ioc_value"]) for r in existing}
            for it in items:
                ioc_type = it.get("ioc_type")
                ioc_value = it.get("ioc_value")
                if not ioc_type or not ioc_value:
                    continue
                if (ioc_type, ioc_value) in seen:
                    continue
                conn.execute(
                    """
                    INSERT INTO iocs (ioc_type, ioc_value, source, description, enabled)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        ioc_type,
                        ioc_value,
                        it.get("source", "user"),
                        it.get("description", ""),
                        1 if it.get("enabled", True) else 0,
                    ),
                )
                seen.add((ioc_type, ioc_value))
                inserted += 1
        return inserted
