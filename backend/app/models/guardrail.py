"""护栏模型 — guardrail_policies / guardrail_hits 表 CRUD（§3）.

遵循现有 KnowledgeDraft 风格：原生 SQLite + get_connection() + 静态方法返回 dict。

- GuardrailPolicy：护栏策略（运行时门禁），支持通配 action_pattern 匹配。
- GuardrailHit：命中记录（供 M1 护栏拦截数聚合）。
"""

import json
import logging
import re
import uuid
from typing import Any, Optional

from app.database import get_connection

logger = logging.getLogger(__name__)


def _pattern_matches(pattern: str, action: str) -> bool:
    """判断 action 是否匹配策略的 action_pattern（支持 ``*`` 通配）。

    Args:
        pattern: 策略的 action_pattern，如 ``host:isolate:*``。
        action: 待校验的动作标识，如 ``host:isolate:web01``。

    Returns:
        匹配返回 True，否则 False。
    """
    if not pattern or not action:
        return False
    if pattern == "*":
        return True
    if "*" not in pattern:
        return pattern == action
    # 以 * 为分隔，依次校验前缀 / 中间段有序出现 / 后缀
    segments = pattern.split("*")
    if not action.startswith(segments[0]):
        return False
    if not action.endswith(segments[-1]):
        return False
    cursor = len(segments[0])
    for segment in segments[1:-1]:
        if not segment:
            continue
        pos = action.find(segment, cursor)
        if pos == -1:
            return False
        cursor = pos + len(segment)
    return True


class GuardrailPolicy:
    """护栏策略 CRUD。"""

    @staticmethod
    def _serialize_whitelist(whitelist: Any) -> str:
        """白名单序列化为 JSON 字符串。"""
        if whitelist is None:
            return "[]"
        if isinstance(whitelist, str):
            return whitelist
        return json.dumps(list(whitelist), ensure_ascii=False)

    @staticmethod
    def match_action(action: str) -> Optional[dict]:
        """取首个 enabled 且 action_pattern 通配命中 action 的策略。

        Args:
            action: 待校验的动作标识。

        Returns:
            命中的策略 dict；无匹配返回 None。
        """
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM guardrail_policies WHERE enabled = 1 ORDER BY id ASC"
            ).fetchall()
        for row in rows:
            policy = dict(row)
            if _pattern_matches(policy.get("action_pattern", ""), action):
                return policy
        return None

    @staticmethod
    def create(
        name: str,
        action_pattern: str,
        whitelist: Any = None,
        risk_level: str = "medium",
        require_confirm: bool = False,
        rollback_plan: str = "",
        enabled: bool = True,
    ) -> dict:
        """创建护栏策略。

        Returns:
            新建的策略 dict（含生成的 policy_id）。
        """
        policy_id = f"gp-{uuid.uuid4().hex[:10]}"
        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO guardrail_policies
                    (policy_id, name, action_pattern, whitelist, risk_level,
                     require_confirm, rollback_plan, enabled)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    policy_id,
                    name,
                    action_pattern,
                    GuardrailPolicy._serialize_whitelist(whitelist),
                    risk_level,
                    1 if require_confirm else 0,
                    rollback_plan,
                    1 if enabled else 0,
                ),
            )
            pid = cursor.lastrowid
            row = conn.execute(
                "SELECT * FROM guardrail_policies WHERE id = ?", (pid,)
            ).fetchone()
        return dict(row)

    @staticmethod
    def get_by_id(policy_id: str) -> Optional[dict]:
        """按 policy_id（业务主键）获取策略。"""
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM guardrail_policies WHERE policy_id = ?", (policy_id,)
            ).fetchone()
            return dict(row) if row else None

    @staticmethod
    def get_all() -> list[dict]:
        """列出全部策略，按创建时间升序。"""
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM guardrail_policies ORDER BY created_at ASC, id ASC"
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def update(policy_id: str, **kwargs: Any) -> Optional[dict]:
        """更新策略字段（name/action_pattern/whitelist/risk_level/...）。"""
        allowed = {
            "name", "action_pattern", "whitelist", "risk_level",
            "require_confirm", "rollback_plan", "enabled",
        }
        data = {k: v for k, v in kwargs.items() if k in allowed}
        if not data:
            return GuardrailPolicy.get_by_id(policy_id)
        if "whitelist" in data:
            data["whitelist"] = GuardrailPolicy._serialize_whitelist(data["whitelist"])
        if "require_confirm" in data:
            data["require_confirm"] = 1 if data["require_confirm"] else 0
        if "enabled" in data:
            data["enabled"] = 1 if data["enabled"] else 0
        clauses = [f"{k} = ?" for k in data]
        values = list(data.values())
        values.append(policy_id)
        with get_connection() as conn:
            conn.execute(
                f"UPDATE guardrail_policies SET {', '.join(clauses)}, "
                f"updated_at = datetime('now') WHERE policy_id = ?",
                values,
            )
        return GuardrailPolicy.get_by_id(policy_id)

    @staticmethod
    def delete(policy_id: str) -> bool:
        """删除策略。返回 True 表示删除成功。"""
        with get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM guardrail_policies WHERE policy_id = ?", (policy_id,)
            )
            return cursor.rowcount > 0


class GuardrailHit:
    """护栏命中记录 CRUD。"""

    @staticmethod
    def record(
        policy_id: Optional[str],
        run_id: Optional[str],
        action: str,
        passed: bool,
    ) -> dict:
        """记录一次护栏命中（evaluate 命中即记）。

        Returns:
            新建的命中记录 dict。
        """
        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO guardrail_hits (policy_id, run_id, action, passed)
                VALUES (?, ?, ?, ?)
                """,
                (policy_id, run_id, action, 1 if passed else 0),
            )
            hid = cursor.lastrowid
            row = conn.execute(
                "SELECT * FROM guardrail_hits WHERE id = ?", (hid,)
            ).fetchone()
        return dict(row)

    @staticmethod
    def list_all(limit: int = 200) -> list[dict]:
        """列出命中记录，按时间降序。"""
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM guardrail_hits ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]
