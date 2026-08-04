"""长期记忆模型 — agent_memories 表 CRUD（P2：长期记忆）.

对齐 ``hitl_approval.py`` 的静态方法模式：所有方法均为 ``@staticmethod``，
内部经 ``get_connection()`` 上下文管理器执行 SQL（自动 commit / rollback）。

设计要点（见 p2-design.md §2/§5.5）：
- 记忆是**追加式留痕**（append-only）：不提供更新；更正手段为删除后重写。
- 不建 FK：``agent_runs`` / ``security_events`` / ``hosts`` 可能被清案/删除，
  记忆作为独立留痕不应被级联删除；删除仅通过显式 ``DELETE /api/memories/{id}``。
- 关键词检索用 ``content LIKE ? OR tags LIKE ?``（``%q%``），P2 规模下零依赖可用；
  向量化仅留扩展位（文档注明，不在本模型实现）。
"""

from __future__ import annotations  # noqa: E402  # 延迟注解求值：类内 `list` 静态方法遮蔽内置 list，避免 `-> list[dict]` 注解在定义时求值报 TypeError（对齐 pipeline_default_rule.py 惯例）

import json
import logging
from typing import Any, Optional

from app.config import settings
from app.database import get_connection

logger = logging.getLogger(__name__)


def _j_tags(tags: Any) -> str:
    """把 tags 归一化为 JSON 数组字符串（兼容 list / tuple / JSON 字符串 / 标量）.

    Args:
        tags: 标签数组（list/tuple/set）、JSON 数组字符串或单个标量。

    Returns:
        JSON 数组字符串（如 ``["powershell","C2"]``）；空/None 返回 ``[]``。
    """
    if tags is None:
        return "[]"
    if isinstance(tags, str):
        stripped = tags.strip()
        if not stripped:
            return "[]"
        try:
            parsed = json.loads(stripped)
        except (json.JSONDecodeError, TypeError):
            return json.dumps([tags], ensure_ascii=False)
        if isinstance(parsed, list):
            return json.dumps(parsed, ensure_ascii=False, default=str)
        return json.dumps([parsed], ensure_ascii=False, default=str)
    if isinstance(tags, (list, tuple, set)):
        return json.dumps(list(tags), ensure_ascii=False, default=str)
    return json.dumps([tags], ensure_ascii=False, default=str)


def _coerce_type(memory_type: Optional[str]) -> str:
    """校验 memory_type ∈ 4 类型；非法回退 ``summary``（fail-safe，调用方再兜底）。"""
    if memory_type in AgentMemory.TYPES:
        return memory_type
    logger.debug("AgentMemory: invalid memory_type=%r, fallback to summary", memory_type)
    return "summary"


def _truncate_content(content: str) -> str:
    """按 ``settings.IR_MEMORY_MAX_CONTENT`` 截断正文（默认 4000 字符）。"""
    text = "" if content is None else str(content)
    max_len = int(getattr(settings, "IR_MEMORY_MAX_CONTENT", 4000) or 4000)
    if len(text) <= max_len:
        return text
    return text[:max_len]


class AgentMemory:
    """长期记忆表 CRUD。

    记忆正文 ``content`` 非空（模型层不强制抛错，调用方负责校验；空串写入
    会以空字符串落库，引擎/API 均已在上游做空内容跳过/400 校验）。
    """

    TYPES = ("conclusion", "summary", "action", "disposition")

    @staticmethod
    def create(
        run_id: Optional[str] = None,
        event_id: Optional[str] = None,
        host_id: Optional[int] = None,
        agent_name: str = "",
        memory_type: str = "summary",
        content: str = "",
        source_node: str = "",
        tags: Any = None,
        created_by: str = "system",
    ) -> dict:
        """创建一条长期记忆（纯追加）.

        Args:
            run_id: 来源运行 ID（``agent_runs.run_id``；手动写入可为空）。
            event_id: 关联安全事件 ID（可为空）。
            host_id: 关联主机 ID（可为空）。
            agent_name: 来源 Agent/节点名（root_cause / responder / reporter / llm / <custom>）。
            memory_type: conclusion | summary | action | disposition（非法回退 summary）。
            content: 记忆正文（截断 IR_MEMORY_MAX_CONTENT）。
            source_node: 来源节点类型（root_cause / action / report / llm ...）。
            tags: 标签（JSON 数组字符串或 list）。
            created_by: 写入人（API 手动=用户名；自动沉淀=system）。

        Returns:
            创建后的完整行 dict（含 id / created_at）。
        """
        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO agent_memories
                (run_id, event_id, host_id, agent_name, memory_type, content,
                 source_node, tags, created_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    event_id,
                    host_id,
                    agent_name or "",
                    _coerce_type(memory_type),
                    _truncate_content(content),
                    source_node or "",
                    _j_tags(tags),
                    created_by or "system",
                ),
            )
            mid = cursor.lastrowid
            row = conn.execute(
                "SELECT * FROM agent_memories WHERE id = ?", (mid,)
            ).fetchone()
        return dict(row)

    @staticmethod
    def get_by_id(mid: Any) -> Optional[dict]:
        """按主键获取一条记忆；不存在返回 None。

        兼容 int 主键或 ``create`` 返回的行 dict（内部自动提取 ``id``）。
        """
        mid = AgentMemory._coerce_id(mid)
        if mid is None:
            return None
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM agent_memories WHERE id = ?", (mid,)
            ).fetchone()
            return dict(row) if row else None

    @staticmethod
    def delete(mid: Any) -> bool:
        """硬删除一条记忆；不存在返回 False。

        兼容 int 主键或 ``create`` 返回的行 dict（内部自动提取 ``id``）。
        """
        mid = AgentMemory._coerce_id(mid)
        if mid is None:
            return False
        with get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM agent_memories WHERE id = ?", (mid,)
            )
            return cursor.rowcount > 0

    @staticmethod
    def _coerce_id(mid: Any) -> Optional[int]:
        """把 int 主键或行 dict 归一化为主键 int；无法解析返回 None。"""
        if isinstance(mid, dict):
            mid = mid.get("id")
        if mid is None:
            return None
        try:
            return int(mid)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _where_clause(
        event_id: Optional[str] = None,
        host_id: Optional[int] = None,
        agent_name: Optional[str] = None,
        memory_type: Optional[str] = None,
        q: Optional[str] = None,
    ) -> tuple[str, list]:
        """构造动态 WHERE 子句与参数（event/host/agent/type 精确过滤 + q 关键词 LIKE）.

        Returns:
            ``(where_sql, params)``；无过滤时 where_sql 为空串、params 为空列表。
        """
        clauses: list[str] = []
        params: list = []
        if event_id is not None and event_id != "":
            clauses.append("event_id = ?")
            params.append(event_id)
        if host_id is not None:
            clauses.append("host_id = ?")
            params.append(host_id)
        if agent_name is not None and agent_name != "":
            clauses.append("agent_name = ?")
            params.append(agent_name)
        if memory_type is not None and memory_type != "":
            clauses.append("memory_type = ?")
            params.append(memory_type)
        keyword = (q or "").strip()
        if keyword:
            clauses.append("(content LIKE ? OR tags LIKE ?)")
            like = f"%{keyword}%"
            params.extend([like, like])
        if clauses:
            return " WHERE " + " AND ".join(clauses), params
        return "", params

    @staticmethod
    def list(
        event_id: Optional[str] = None,
        host_id: Optional[int] = None,
        agent_name: Optional[str] = None,
        memory_type: Optional[str] = None,
        q: Optional[str] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> dict:
        """分页列出记忆（支持全部过滤维度 + q 关键词）.

        Returns:
            ``{"items": [...], "total": int, "page": int, "page_size": int}``，
            按 ``created_at DESC, id DESC`` 排序（最近优先）。
        """
        page = max(1, int(page or 1))
        page_size = max(1, min(200, int(page_size or 50)))
        offset = (page - 1) * page_size
        where, params = AgentMemory._where_clause(
            event_id=event_id, host_id=host_id, agent_name=agent_name,
            memory_type=memory_type, q=q,
        )
        with get_connection() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) FROM agent_memories{where}", params
            ).fetchone()[0]
            rows = conn.execute(
                f"SELECT * FROM agent_memories{where} "
                "ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
                [*params, page_size, offset],
            ).fetchall()
        return {
            "items": [dict(r) for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    @staticmethod
    def search(
        q: str = "",
        event_id: Optional[str] = None,
        host_id: Optional[int] = None,
        agent_name: Optional[str] = None,
        memory_type: Optional[str] = None,
        limit: int = 5,
    ) -> list[dict]:
        """关键词检索历史记忆（供记忆引用 / 前端检索框）.

        与 ``list`` 的区别：不做分页、只取最近 ``limit`` 条（``created_at DESC, id DESC``）；
        ``q`` 为空/空白时不按关键词过滤（仅按维度过滤取最近）。

        Args:
            q: 关键词（对 content/tags 做 LIKE）。
            event_id: 同事件复盘（可选）。
            host_id: 同主机跨事件长期记忆（P2 核心粒度，可选）。
            agent_name: 来源智能体（可选）。
            memory_type: 类型过滤（可选）。
            limit: 返回条数上限（调用方已夹取，此处再兜底 [1,50]）。

        Returns:
            list[dict]：最近优先的记忆行。
        """
        limit = max(1, min(50, int(limit or 5)))
        where, params = AgentMemory._where_clause(
            event_id=event_id, host_id=host_id, agent_name=agent_name,
            memory_type=memory_type, q=q,
        )
        with get_connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM agent_memories{where} "
                "ORDER BY created_at DESC, id DESC LIMIT ?",
                [*params, limit],
            ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def count(
        event_id: Optional[str] = None,
        host_id: Optional[int] = None,
        agent_name: Optional[str] = None,
        memory_type: Optional[str] = None,
        q: Optional[str] = None,
    ) -> int:
        """统计记忆条数（支持与 list 相同的过滤维度；缺省统计全表）."""
        where, params = AgentMemory._where_clause(
            event_id=event_id, host_id=host_id, agent_name=agent_name,
            memory_type=memory_type, q=q,
        )
        with get_connection() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) FROM agent_memories{where}", params
            ).fetchone()[0]
        return int(total)
