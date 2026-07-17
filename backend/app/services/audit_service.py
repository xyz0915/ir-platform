"""审计日志服务 — 通用审计日志写入函数."""

import logging
from typing import Optional

from app.database import get_connection

logger = logging.getLogger(__name__)


class AuditService:
    """审计日志服务类(兼容旧版导入)."""

    @staticmethod
    def create_audit_log(
        user_id: int,
        username: str,
        action_type: str,
        detail: str = "",
        target_type: str = "",
        target_id: str = "",
        ip_address: str = "",
    ) -> None:
        """写入一条审计日志(静态方法, 兼容旧调用方)."""
        create_audit_log(user_id, username, action_type, detail, target_type, target_id, ip_address)

    @staticmethod
    def log_call(**kwargs) -> None:
        """记录一条 AI 调用审计日志（写入 ai_audit_log 表）."""
        with get_connection() as conn:
            columns = [
                "host_id", "host_name", "profile_id", "profile_name", "model_name",
                "status", "prompt_tokens", "completion_tokens", "total_tokens",
                "latency_ms", "masked_mode", "prompt", "response", "error_message",
                "ip_address", "user_id",
            ]
            insert_cols = [c for c in columns if c in kwargs]
            insert_vals = [kwargs.get(c) for c in insert_cols]
            placeholders = ", ".join(["?"] * len(insert_cols))
            col_str = ", ".join(insert_cols)
            sql = f"INSERT INTO ai_audit_log ({col_str}) VALUES ({placeholders})"
            conn.execute(sql, insert_vals)
            conn.commit()
        logger.debug("AuditService.log_call: host_id=%s status=%s", kwargs.get("host_id"), kwargs.get("status"))

    @staticmethod
    def query_logs(page: int = 1, page_size: int = 20, host_id: Optional[int] = None,
                   status: Optional[str] = None, days: int = 90) -> dict:
        """分页查询 AI 调用审计日志."""
        with get_connection() as conn:
            conditions = []
            params = []
            if host_id is not None:
                conditions.append("host_id = ?")
                params.append(host_id)
            if status:
                conditions.append("status = ?")
                params.append(status)
            if days:
                conditions.append("created_at >= datetime('now', ?)")
                params.append(f"-{days} days")

            where = ""
            if conditions:
                where = "WHERE " + " AND ".join(conditions)

            # 总数
            total = conn.execute(
                f"SELECT COUNT(*) FROM ai_audit_log {where}", params
            ).fetchone()[0]

            # 分页
            offset = (page - 1) * page_size
            cursor = conn.execute(
                f"SELECT * FROM ai_audit_log {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                params + [page_size, offset],
            )
            rows = cursor.fetchall()

            columns = [desc[0] for desc in cursor.description]
            items = [dict(zip(columns, row)) for row in rows]

            return {
                "items": items,
                "total": total,
                "page": page,
                "page_size": page_size,
            }

    @staticmethod
    def get_detail(log_id: int) -> dict:
        """获取单条 AI 调用审计日志详情."""
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM ai_audit_log WHERE id = ?", (log_id,)
            ).fetchone()
            if not row:
                raise ValueError(f"Audit log {log_id} not found")
            return dict(row)


def create_audit_log(
    user_id: int,
    username: str,
    action_type: str,
    detail: str = "",
    target_type: str = "",
    target_id: str = "",
    ip_address: str = "",
) -> None:
    """写入一条审计日志.

    Args:
        user_id: 操作用户 ID.
        username: 操作用户名.
        action_type: 操作类型(login/logout/rule_change/event_dispose/ai_analysis/settings_change/user_manage).
        detail: 操作详情.
        target_type: 目标类型.
        target_id: 目标 ID.
        ip_address: 客户端 IP 地址.
    """
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO audit_logs (user_id, username, action_type, detail, target_type, target_id, ip_address) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, username, action_type, detail, target_type, target_id, ip_address),
        )
        conn.commit()
    logger.debug("Audit log created: user=%s action=%s detail=%s", username, action_type, detail)
