"""智能体运行模型 — agent_runs / agent_run_steps 表 CRUD（§4.1）."""

import json
import logging
from typing import Any, Optional

from app.database import get_connection

logger = logging.getLogger(__name__)


class AgentRun:
    """多智能体运行主表 CRUD。"""

    @staticmethod
    def create(
        run_id: str,
        event_id: Optional[str] = None,
        case_id: Optional[int] = None,
        title: str = "",
        stage: str = "triage",
        status: str = "pending",
        priority: str = "P2",
        confidence: float = 0.0,
        user_id: Optional[int] = None,
        ctx_json: Optional[str] = None,
    ) -> dict:
        """创建一次 agent_run。"""
        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO agent_runs
                (run_id, event_id, case_id, title, stage, status, priority,
                 confidence, user_id, ctx_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (run_id, event_id, case_id, title, stage, status, priority,
                 confidence, user_id, ctx_json),
            )
            rid = cursor.lastrowid
        return AgentRun.get_by_id(rid)

    @staticmethod
    def get_by_id(rid: int) -> Optional[dict]:
        """按主键获取。"""
        with get_connection() as conn:
            row = conn.execute("SELECT * FROM agent_runs WHERE id = ?", (rid,)).fetchone()
            return dict(row) if row else None

    @staticmethod
    def get_by_run_id(run_id: str) -> Optional[dict]:
        """按 run_id（唯一）获取。"""
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM agent_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            return dict(row) if row else None

    @staticmethod
    def update(run_id: str, **kwargs: Any) -> Optional[dict]:
        """更新字段（stage/status/confidence/current_agent/result_json 等）。"""
        allowed = {
            "event_id", "case_id", "title", "stage", "status", "priority",
            "current_agent", "confidence", "result_json", "ctx_json",
        }
        data = {k: v for k, v in kwargs.items() if k in allowed}
        if not data:
            return AgentRun.get_by_run_id(run_id)
        clauses = [f"{k} = ?" for k in data]
        values = list(data.values())
        values.append(run_id)
        with get_connection() as conn:
            conn.execute(
                f"UPDATE agent_runs SET {', '.join(clauses)}, updated_at = datetime('now') "
                f"WHERE run_id = ?",
                values,
            )
        return AgentRun.get_by_run_id(run_id)

    @staticmethod
    def list_all(
        status: Optional[str] = None, page: int = 1, page_size: int = 50
    ) -> dict:
        """分页列出 agent_runs。"""
        conditions = []
        params: list[Any] = []
        if status:
            conditions.append("status = ?")
            params.append(status)
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        with get_connection() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) FROM agent_runs {where}", params
            ).fetchone()[0]
            offset = (page - 1) * page_size
            rows = conn.execute(
                f"SELECT * FROM agent_runs {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                params + [page_size, offset],
            ).fetchall()
        return {
            "items": [dict(r) for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }


class AgentRunStep:
    """单步执行审计表 CRUD。"""

    @staticmethod
    def add(
        run_id: str,
        stage: Optional[str] = None,
        agent: Optional[str] = None,
        status: Optional[str] = None,
        input_json: Optional[Any] = None,
        output_json: Optional[Any] = None,
        confidence: float = 0.0,
        evidence_json: Optional[Any] = None,
        audit_log_id: Optional[int] = None,
    ) -> dict:
        """写入一步 Agent 执行记录（evidence 可溯源）。"""
        def _j(v: Any) -> str:
            if v is None:
                return "[]" if isinstance(v, list) else "{}"
            if isinstance(v, (dict, list)):
                return json.dumps(v, ensure_ascii=False, default=str)
            return str(v)

        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO agent_run_steps
                (run_id, stage, agent, status, input_json, output_json,
                 confidence, evidence_json, audit_log_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (run_id, stage, agent, status, _j(input_json), _j(output_json),
                 confidence, _j(evidence_json if evidence_json is not None else []),
                 audit_log_id),
            )
            sid = cursor.lastrowid
            row = conn.execute(
                "SELECT * FROM agent_run_steps WHERE id = ?", (sid,)
            ).fetchone()
        return dict(row)

    @staticmethod
    def list_by_run(run_id: str) -> list[dict]:
        """列出某 run 的所有步骤（按时间升序）。"""
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM agent_run_steps WHERE run_id = ? ORDER BY id ASC",
                (run_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def get_by_id(step_id: int) -> Optional[dict]:
        """按主键获取步骤。"""
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM agent_run_steps WHERE id = ?", (step_id,)
            ).fetchone()
            return dict(row) if row else None
