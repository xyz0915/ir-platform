"""智能体运行模型 — agent_runs / agent_run_steps 表 CRUD（§4.1）."""

import json
import logging
import uuid
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
        """列出某 run 的所有步骤（按时间升序），自动解析 JSON 字段。"""
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM agent_run_steps WHERE run_id = ? ORDER BY id ASC",
                (run_id,),
            ).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            # 自动解析 JSON 字段为对象
            for k in ('output_json', 'evidence_json', 'input_json'):
                if d.get(k) and isinstance(d[k], str):
                    try:
                        d[k] = json.loads(d[k])
                    except (json.JSONDecodeError, TypeError):
                        pass
            results.append(d)
        return results

    @staticmethod
    def get_by_id(step_id: int) -> Optional[dict]:
        """按主键获取步骤。"""
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM agent_run_steps WHERE id = ?", (step_id,)
            ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def update(step_id: int, **kwargs: Any) -> Optional[dict]:
        """更新已有步骤（custom 模式 resume 刷新 reporter 步骤时使用，避免重复新建）.

        Args:
            step_id: 步骤主键 id。
            **kwargs: 可更新的字段（stage/agent/status/input_json/output_json/
                confidence/evidence_json/audit_log_id）。

        Returns:
            更新后的步骤行，或 None（记录不存在）。
        """
        allowed = {
            "stage", "agent", "status", "input_json",
            "output_json", "confidence", "evidence_json", "audit_log_id",
        }

        def _j(v: Any) -> str:
            if v is None:
                return "[]" if isinstance(v, list) else "{}"
            if isinstance(v, (dict, list)):
                return json.dumps(v, ensure_ascii=False, default=str)
            return str(v)

        data: dict[str, Any] = {}
        for k in allowed:
            if k in kwargs:
                v = kwargs[k]
                data[k] = _j(v) if k in ("input_json", "output_json", "evidence_json") else v
        if not data:
            return AgentRunStep.get_by_id(step_id)
        clauses = [f"{k} = ?" for k in data]
        values = list(data.values())
        values.append(step_id)
        with get_connection() as conn:
            conn.execute(
                f"UPDATE agent_run_steps SET {', '.join(clauses)} WHERE id = ?",
                values,
            )
        return AgentRunStep.get_by_id(step_id)


class NodeRunRepository:
    """单节点调试历史持久化（复用 agent_runs / agent_run_steps，debug-<uuid> 前缀）。

    设计依据：02-design.md §4.1（零新建表、零 schema 变更）。
    - 每次单节点执行写入一条 ``agent_runs``（run_id 形如 ``debug-<12位hex>``）
      与一条 ``agent_run_steps``（``input_json`` 补全 ``{mode, input_params, context_vars, resolved_host_id}``）。
    - 查询按 ``run_id LIKE 'debug-%'`` + ``status='debug'`` 识别，按 ``created_at`` 倒序；
      ``mode`` 过滤在 Python 层完成（避免 ALTER 加列）。
    """

    @staticmethod
    def persist_debug_run(
        node_name: str,
        node_type: str,
        status: str,
        output_text: str,
        structured: dict,
        mode: str,
        input_params: dict,
        context_vars: dict,
        elapsed_ms: float,
        confidence: float,
        evidence: list,
        error: Optional[str] = None,
    ) -> str:
        """写入一条单节点调试运行，返回合成 run_id。"""
        run_id = f"debug-{uuid.uuid4().hex[:12]}"
        resolved_host_id = (context_vars or {}).get("host_id")
        event_id = (context_vars or {}).get("event_id")

        input_json = {
            "mode": mode,
            "input_params": input_params or {},
            "context_vars": context_vars or {},
            "resolved_host_id": resolved_host_id,
        }
        output_json = {
            "output_text": output_text,
            "structured": structured or {},
            "confidence": confidence,
            "evidence": evidence or [],
            "error": error,
            "elapsed_ms": elapsed_ms,
        }

        AgentRun.create(
            run_id=run_id,
            event_id=event_id,
            title=f"Debug · {node_name}",
            stage=node_name,
            status="debug",
            confidence=confidence,
            ctx_json=json.dumps(
                {
                    "node_type": node_type,
                    "input_params": input_params,
                    "context_vars": context_vars,
                },
                default=str, ensure_ascii=False,
            ),
        )
        AgentRunStep.add(
            run_id=run_id,
            stage=node_name,
            agent=node_name,
            status=status,
            input_json=input_json,
            output_json=output_json,
            confidence=confidence,
            evidence_json=evidence or [],
        )
        return run_id

    @staticmethod
    def list_debug_runs_by_node(
        node_name: Optional[str] = None,
        mode: Optional[str] = None,
        limit: int = 20,
    ) -> list[dict]:
        """列出单节点调试历史（JOIN agent_run_steps，按 created_at 倒序）。

        过滤：
            - node_name：匹配 ``agent_runs.stage``；
            - mode：匹配 step 的 ``input_json.mode``（Python 层过滤，避免 ALTER）。
        """
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM agent_runs WHERE run_id LIKE 'debug-%' "
                "AND status = 'debug' ORDER BY created_at DESC"
            ).fetchall()

        items: list[dict] = []
        for r in rows:
            d = dict(r)
            run_id = d.get("run_id")
            steps = AgentRunStep.list_by_run(run_id)
            step0 = steps[0] if steps else {}
            input_json = step0.get("input_json") if isinstance(step0.get("input_json"), dict) else {}
            output_json = step0.get("output_json") if isinstance(step0.get("output_json"), dict) else {}
            step_mode = input_json.get("mode")

            # node_name 过滤
            if node_name and d.get("stage") != node_name:
                continue
            # mode 过滤（Python 层）
            if mode and step_mode != mode:
                continue

            # node_type 存于 ctx_json
            node_type = None
            ctx_json = d.get("ctx_json")
            if ctx_json:
                try:
                    node_type = json.loads(ctx_json).get("node_type")
                except (json.JSONDecodeError, TypeError):
                    pass

            items.append({
                "run_id": run_id,
                "node_name": d.get("stage"),
                "node_type": node_type,
                "mode": step_mode,
                "status": step0.get("status"),
                "elapsed_ms": output_json.get("elapsed_ms"),
                "confidence": step0.get("confidence"),
                "timestamp": d.get("created_at"),
                "input": input_json,
                "output": {
                    "output_text": output_json.get("output_text"),
                    "structured": output_json.get("structured"),
                    "confidence": output_json.get("confidence"),
                    "evidence": output_json.get("evidence"),
                },
                "error": output_json.get("error"),
            })
        return items[:limit]
