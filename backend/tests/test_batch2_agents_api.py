"""第②批 T-A2 编排 API + HITL 测试（重点）。

使用 FastAPI TestClient 对 agents 路由做隔离测试：
- 鉴权闸门：无 token → 401；非 admin → HITL 决议端点 403。
- 正常路径：带合法 token 创建 run 进入流水线（终态 waiting_hitl / completed）。
- 端到端 HITL 闭环：waiting_hitl → admin approve → 执行处置（ActionService 被调用）
  + 写 event_disposition_log + run 收尾 completed。

独立最小 app（仅挂载 agents.router，prefix=/api），避免触发全量 startup / 调度器，
DB 走 _qa_batch1_common 隔离 SQLite（绝不触碰 ir.db）。
"""

import asyncio
import json
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock

import sys
_THIS = Path(__file__).resolve().parent
_BACKEND = _THIS.parent
for _p in (str(_BACKEND), str(_THIS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api.agents import router as agents_router
from app.services.auth_service import get_current_user
from app.models.hitl_approval import HitlApproval
from app.database import get_connection

from _qa_batch1_common import IsolatedDBTestCase


# 最小 app：仅挂编排 + HITL 路由
_api_app = FastAPI()
_api_app.include_router(agents_router, prefix="/api")


def seed_full_incident():
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


class TestAgentOrchestrationAPI(IsolatedDBTestCase):
    def setUp(self):
        super().setUp()  # 创建隔离 DB 并 init_db
        self.client = TestClient(_api_app)
        _api_app.dependency_overrides.clear()

    def tearDown(self):
        _api_app.dependency_overrides.clear()
        super().tearDown()

    def _auth(self, role="admin"):
        user = {
            "id": 1 if role == "admin" else 2,
            "username": "admin" if role == "admin" else "analyst",
            "role": role,
        }
        _api_app.dependency_overrides[get_current_user] = lambda: user

    # ── 鉴权闸门 ──
    def test_no_token_returns_401(self):
        _api_app.dependency_overrides.clear()
        resp = self.client.post("/api/agents/run", json={"event_id": "SE-1"})
        self.assertEqual(resp.status_code, 401)

    def test_non_admin_cannot_approve_403(self):
        self._auth("analyst")
        resp = self.client.post(
            "/api/agents/runs/nonexistent/approve", json={"approval_id": 1})
        self.assertEqual(resp.status_code, 403)
        r2 = self.client.get("/api/agents/approvals")
        self.assertEqual(r2.status_code, 403)

    def test_non_admin_can_list_runs(self):
        """list/detail 仅需鉴权（任何角色），非 admin 可访问。"""
        self._auth("analyst")
        r1 = self.client.get("/api/agents/runs")
        self.assertEqual(r1.status_code, 200)
        r2 = self.client.get("/api/agents/runs/whatever")
        self.assertEqual(r2.status_code, 404)  # 鉴权通过，仅 run 不存在

    def test_admin_approvals_list_200(self):
        self._auth("admin")
        r = self.client.get("/api/agents/approvals")
        self.assertEqual(r.status_code, 200)

    # ── 正常路径 + 端到端 HITL 闭环 ──
    def test_create_run_reaches_waiting_hitl(self):
        self._auth("admin")
        seed_full_incident()
        resp = self.client.post("/api/agents/run", json={"event_id": "SE-1"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertEqual(data["status"], "waiting_hitl")
        run_id = data["run_id"]
        # 列表 + 详情
        lst = self.client.get("/api/agents/runs")
        self.assertEqual(lst.status_code, 200)
        self.assertGreaterEqual(lst.json()["data"]["total"], 1)
        det = self.client.get(f"/api/agents/runs/{run_id}")
        self.assertEqual(det.status_code, 200)
        steps = det.json()["data"]["steps"]
        self.assertGreaterEqual(len(steps), 3)

    def test_end_to_end_hitl_loop(self):
        self._auth("admin")
        seed_full_incident()
        # 1) 启动闭环
        resp = self.client.post("/api/agents/run", json={"event_id": "SE-1"})
        self.assertEqual(resp.status_code, 200)
        run_id = resp.json()["data"]["run_id"]
        # 2) 提取待审批记录
        ap = HitlApproval.list_by_run(run_id)[0]
        approval_id = ap["id"]
        self.assertEqual(ap["status"], "pending")
        # 3) admin 批准 → 执行处置 + 写库 + 收尾
        mock_exec = AsyncMock(return_value={
            "success": True, "action": "block_ip",
            "status": "completed", "result": {"ip": "8.8.8.8"}})
        with patch("app.services.action_service.ActionService.execute", new=mock_exec), \
                patch("app.services.knowledge_retriever.KnowledgeRetriever.rebuild_seed_index",
                      new=MagicMock()):
            apr = self.client.post(
                f"/api/agents/runs/{run_id}/approve",
                json={"approval_id": approval_id})
        self.assertEqual(apr.status_code, 200)
        # ActionService 被调用
        mock_exec.assert_awaited_once_with("block_ip", {"ip": "8.8.8.8"})
        # 处置记录写库
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM event_disposition_log WHERE event_id=?",
                ("SE-1",)).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["action"], "block_ip")
        # run 收尾 completed
        final = self.client.get(f"/api/agents/runs/{run_id}").json()["data"]["run"]
        self.assertEqual(final["status"], "completed")

    def test_approve_nonexistent_approval_404(self):
        self._auth("admin")
        # 需要一个真实 run 才能进入“查找审批记录”逻辑（否则 404=run 不存在先触发）
        seed_full_incident()
        resp = self.client.post("/api/agents/run", json={"event_id": "SE-1"})
        run_id = resp.json()["data"]["run_id"]
        bad = self.client.post(
            f"/api/agents/runs/{run_id}/approve",
            json={"approval_id": 999999})
        self.assertEqual(bad.status_code, 404)

    def test_reject_endpoint_403_for_non_admin(self):
        self._auth("analyst")
        resp = self.client.post(
            "/api/agents/runs/rid/reject", json={"approval_id": 1})
        self.assertEqual(resp.status_code, 403)


if __name__ == "__main__":
    import unittest
    unittest.main(verbosity=2)
