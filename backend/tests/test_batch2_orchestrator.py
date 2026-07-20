"""第②批 T-A1 编排器测试：Orchestrator.run_pipeline / resume / _finish_with_reporter。

验证：
- run_pipeline 串行 triage→investigation→responder 并置 run=waiting_hitl，
  写 hitl_approvals(pending)，agent_run_steps 状态正确。
- resume(approve) 在管理员决议后执行处置（ActionService）+ 写 event_disposition_log
  + reporter 收尾 → run=completed。
- resume(reject) 跳过执行，run 收尾 completed。
- LLM 降级路径：默认无 Profile → 各 Agent degraded 仍完成流水线不抛 500。

复用 _qa_batch1_common 隔离 DB（绝不触碰 ir.db）。
"""

import asyncio
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock

import sys
_THIS = Path(__file__).resolve().parent
_BACKEND = _THIS.parent
for _p in (str(_BACKEND), str(_THIS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from app.services.agents.orchestrator import Orchestrator
from app.models.agent_run import AgentRun, AgentRunStep
from app.models.hitl_approval import HitlApproval
from app.database import get_connection

from _qa_batch1_common import IsolatedDBTestCase, make_isolated_db, cleanup_db


def seed_full_incident():
    """写 case→host→security_events(critical/suspicious)→logs(high+ip)→rules。"""
    from app.database import get_connection
    import json
    with get_connection() as conn:
        conn.execute("INSERT INTO cases (name) VALUES ('qa_case')")
        case_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO hosts (case_id, hostname, ip_address, os_type) "
            "VALUES (?, 'QAHOST', '10.0.0.7', 'Windows')", (case_id,))
        host_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO security_events "
            "(id, timestamp, host_id, event_type, event_key, severity, ai_verdict) "
            "VALUES (?, '2026-07-18 10:00:00', ?, 'malware', 'ek1', 'critical', ?)",
            ("SE-1", host_id, json.dumps({"label": "suspicious", "reason": "beacon"})))
        conn.execute(
            "INSERT INTO normalized_logs "
            "(host_id, log_source, event_type, event_label, severity, timestamp, "
            "source_ip, process_name, command_line) "
            "VALUES (?, 'test', 'network', 'outbound', 'high', '2026-07-18 10:00:01', "
            "'8.8.8.8', 'powershell.exe', 'IWR http://8.8.8.8/x')", (host_id,))
        conn.execute(
            "INSERT INTO rules "
            "(name, description, category, rule_type, condition, severity, enabled) "
            "VALUES ('Suspicious Beacon', 'beacon detect', 'malware', 'detection', "
            "'{}', 'high', 1)")
    return host_id


class TestOrchestratorPipeline(IsolatedDBTestCase):
    def _run_pipeline_to_hitl(self):
        seed_full_incident()
        orch = Orchestrator()
        user = {"id": 1, "username": "admin", "role": "admin"}
        run = orch.start_run(event_id="SE-1", user=user)
        rid = run["run_id"]
        outcome = asyncio.run(
            orch.run_pipeline(rid, user, ctx={"event_id": "SE-1"})
        )
        return orch, rid, outcome

    def test_run_pipeline_reaches_waiting_hitl(self):
        orch, rid, outcome = self._run_pipeline_to_hitl()
        self.assertEqual(outcome["status"], "waiting_hitl")
        self.assertEqual(AgentRun.get_by_run_id(rid)["status"], "waiting_hitl")
        # 三个阶段各写一步
        steps = AgentRunStep.list_by_run(rid)
        self.assertEqual(len(steps), 3)
        self.assertEqual({s["stage"] for s in steps},
                         {"triage", "investigation", "response"})
        self.assertTrue(all(s["status"] == "success" for s in steps))
        # 写一条 pending 审批
        approvals = HitlApproval.list_by_run(rid)
        self.assertEqual(len(approvals), 1)
        self.assertEqual(approvals[0]["status"], "pending")
        self.assertEqual(approvals[0]["action"], "block_ip")

    def test_resume_approve_executes_and_completes(self):
        orch, rid, _ = self._run_pipeline_to_hitl()
        # 管理员决议：approve
        ap = HitlApproval.list_by_run(rid)[0]
        HitlApproval.update_status(ap["id"], HitlApproval.STATUS_APPROVED,
                                   decided_by=1, reason=None)
        approval = HitlApproval.get_by_id(ap["id"])
        mock_exec = AsyncMock(return_value={
            "success": True, "action": "block_ip",
            "status": "completed", "result": {"ip": "8.8.8.8"}})
        with patch("app.services.action_service.ActionService.execute", new=mock_exec), \
                patch("app.services.knowledge_retriever.KnowledgeRetriever.rebuild_seed_index",
                      new=MagicMock()):
            outcome = asyncio.run(orch.resume(
                rid, approval, decided_by=1,
                user={"id": 1, "username": "admin", "role": "admin"}))
        self.assertEqual(outcome["status"], "completed")
        self.assertEqual(AgentRun.get_by_run_id(rid)["status"], "completed")
        # reporter 收尾新增一步
        steps = AgentRunStep.list_by_run(rid)
        self.assertEqual(len(steps), 4)
        self.assertTrue(any(s["stage"] == "report" for s in steps))
        # ActionService 被调用
        mock_exec.assert_awaited_once_with("block_ip", {"ip": "8.8.8.8"})
        # 处置记录写库
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM event_disposition_log WHERE event_id=?",
                ("SE-1",)).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["action"], "block_ip")

    def test_resume_reject_skips_execution(self):
        orch, rid, _ = self._run_pipeline_to_hitl()
        ap = HitlApproval.list_by_run(rid)[0]
        HitlApproval.update_status(ap["id"], HitlApproval.STATUS_REJECTED,
                                   decided_by=1, reason="误报")
        approval = HitlApproval.get_by_id(ap["id"])
        mock_exec = AsyncMock(return_value={"success": True})
        with patch("app.services.action_service.ActionService.execute", new=mock_exec), \
                patch("app.services.knowledge_retriever.KnowledgeRetriever.rebuild_seed_index",
                      new=MagicMock()):
            outcome = asyncio.run(orch.resume(
                rid, approval, decided_by=1,
                user={"id": 1, "username": "admin", "role": "admin"}))
        self.assertEqual(outcome["status"], "completed")
        self.assertEqual(AgentRun.get_by_run_id(rid)["status"], "completed")
        # 拒绝 → 不执行真实动作
        mock_exec.assert_not_awaited()
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM event_disposition_log WHERE event_id=?",
                ("SE-1",)).fetchone()
        self.assertIsNone(row)


if __name__ == "__main__":
    import unittest
    unittest.main(verbosity=2)
