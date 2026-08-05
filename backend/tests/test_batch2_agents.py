"""第②批 T-A1 单元测试：DataProvider + 四 Agent（Triage/Investigator/Responder/Reporter）.

覆盖核心路径 + 边界 + LLM 降级安全闸（§工程约束：AgentLLM 返回 degraded 时
各 Agent 仍基于真实数据产出带 evidence 的输出且不抛 500）。

复用 _qa_batch1_common.IsolatedDBTestCase 的隔离 SQLite 设施（绝不触碰 ir.db）。
"""

import asyncio
import json
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock

# 确保 backend 与 tests 目录均在 sys.path（兼容 pytest / python 直接运行）
import sys
_THIS = Path(__file__).resolve().parent
_BACKEND = _THIS.parent
for _p in (str(_BACKEND), str(_THIS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from app.database import get_connection
from app.services.agents.base_agent import AgentResult
from app.services.agents import data_provider
from app.services.agents.triage_agent import TriageAgent
from app.services.agents.investigator_agent import InvestigatorAgent
from app.services.agents.responder_agent import ResponderAgent
from app.services.agents.reporter_agent import ReporterAgent
from app.services.agents import investigator_agent as _inv_mod
from app.models.agent_run import AgentRun, AgentRunStep

from _qa_batch1_common import IsolatedDBTestCase


def seed_full_incident() -> dict:
    """写入 case → host → security_events(critical/suspicious) → logs(high+ip)
    → process_events → enabled rule。返回关键 id。"""
    with get_connection() as conn:
        conn.execute("INSERT INTO cases (name) VALUES ('qa_case')")
        case_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO hosts (case_id, hostname, ip_address, os_type) "
            "VALUES (?, 'QAHOST', '10.0.0.7', 'Windows')",
            (case_id,),
        )
        host_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO security_events "
            "(id, timestamp, host_id, event_type, event_key, severity, ai_verdict) "
            "VALUES (?, '2026-07-18 10:00:00', ?, 'malware', 'ek1', 'critical', ?)",
            ("SE-1", host_id, json.dumps({"label": "suspicious", "reason": "beacon"})),
        )
        # high 严重度 + 外连 IP → 触发 Responder 推导 block_ip
        conn.execute(
            "INSERT INTO normalized_logs "
            "(host_id, log_source, event_type, event_label, severity, timestamp, "
            "source_ip, process_name, command_line) "
            "VALUES (?, 'test', 'network', 'outbound', 'high', '2026-07-18 10:00:01', "
            "'8.8.8.8', 'powershell.exe', 'IWR http://8.8.8.8/x')",
            (host_id,),
        )
        conn.execute(
            "INSERT INTO normalized_logs "
            "(host_id, log_source, event_type, event_label, severity, timestamp, "
            "source_ip, process_name, command_line) "
            "VALUES (?, 'test', 'process', 'exec', 'low', '2026-07-18 10:00:02', "
            "'10.0.0.9', 'cmd.exe', 'whoami')",
            (host_id,),
        )
        conn.execute(
            "INSERT INTO process_events "
            "(host_id, event_type, pid, ppid, process_name, process_path, "
            "command_line, parent_name, start_time) "
            "VALUES (?, 'process_start', 101, 1, 'evil.exe', 'C:\\\\tmp\\\\evil.exe', "
            "'evil.exe --c2', 'cmd.exe', '2026-07-18 09:59:00')",
            (host_id,),
        )
        conn.execute(
            "INSERT INTO rules "
            "(name, description, category, rule_type, condition, severity, enabled) "
            "VALUES ('Suspicious Beacon', 'beacon detect', 'malware', 'detection', "
            "'{}', 'high', 1)"
        )
    return {"host_id": host_id, "event_id": "SE-1", "source_ip": "8.8.8.8"}


# ───────────────────────── DataProvider ─────────────────────────
class TestDataProvider(IsolatedDBTestCase):
    def test_event_and_log_retrieval(self):
        seed = seed_full_incident()
        ev = data_provider.get_event("SE-1")
        self.assertIsNotNone(ev)
        self.assertEqual(ev["severity"], "critical")
        events = data_provider.get_events(["SE-1"])
        self.assertEqual(len(events), 1)
        logs = data_provider.get_logs_by_host(seed["host_id"])
        self.assertEqual(len(logs), 2)
        procs = data_provider.get_process_events(seed["host_id"])
        self.assertEqual(len(procs), 1)
        host = data_provider.get_host(seed["host_id"])
        self.assertEqual(host["hostname"], "QAHOST")
        self.assertIsNone(data_provider.get_event("NOPE"))

    def test_enabled_rules_and_hit_summary(self):
        seed_full_incident()
        # get_enabled_rules 返回已启用规则（init_db 默认已载规则库，非空）
        rules = data_provider.get_enabled_rules()
        self.assertTrue(len(rules) > 0)
        # 用真实事件 + 已启用规则验证命中摘要产出（不依赖具体规则名/分页）
        ev = data_provider.get_event("SE-1")
        summary = data_provider.get_rules_hit_summary(ev, rules)
        self.assertIsInstance(summary, str)
        self.assertTrue(len(summary) > 0)
        # 构造可确定性命中的规则，验证摘要包含规则名。
        # 根因（A4 ④）：get_rules_hit_summary 按 rule.label 匹配 event_type，
        # 旧 fake_rules 只提供 category 字段 → 永不命中；label 与事件 event_type 对齐。
        fake_rules = [{"name": "Suspicious Beacon", "severity": "high",
                       "label": "malware", "description": "beacon"}]
        self.assertIn("Suspicious Beacon",
                      data_provider.get_rules_hit_summary(ev, fake_rules))
        # 无规则 → 空串不报错
        self.assertEqual(data_provider.get_rules_hit_summary(ev, []), "")

    def test_extract_refs(self):
        events = [{"id": "SE-1", "severity": "critical", "event_type": "malware"}]
        logs = [{"id": 5, "event_type": "network", "severity": "high",
                 "mitre_attack": "T1071"}]
        procs = [{"id": 9, "process_name": "evil.exe", "pid": 101,
                 "parent_name": "cmd.exe"}]
        er = data_provider.extract_event_refs(events)
        self.assertEqual(er[0]["ref"], "security_events.id=SE-1")
        lr = data_provider.extract_log_refs(logs)
        self.assertEqual(lr[0]["ref"], "normalized_logs.id=5")
        pr = data_provider.extract_process_refs(procs)
        self.assertEqual(pr[0]["ref"], "process_events.id=9")

    def test_retrieve_cases_returns_empty_on_rag_failure(self):
        """RAG 检索异常必须降级为空列表，不阻断调查链路。"""
        with patch(
            "app.services.knowledge_retriever.KnowledgeRetriever.retrieve",
            side_effect=RuntimeError("chroma down"),
        ):
            out = data_provider.retrieve_cases("anything", limit=3)
        self.assertEqual(out, [])


# ───────────────────────── TriageAgent ─────────────────────────
class TestTriageAgent(IsolatedDBTestCase):
    def test_instantiation_metadata(self):
        a = TriageAgent()
        self.assertEqual(a.name, "triage_agent")
        self.assertFalse(a.requires_hitl)

    def test_run_produces_agent_result_with_evidence(self):
        seed_full_incident()
        ctx = {"event_id": "SE-1", "user": {"id": 1}}
        result = asyncio.run(TriageAgent().run(ctx, {"event_id": "SE-1"}))
        self.assertIsInstance(result, AgentResult)
        self.assertEqual(result.stage, "triage")
        self.assertIsInstance(result.evidence, list)
        self.assertGreater(len(result.evidence), 0)
        # 数据驱动：critical + suspicious → P0；置信度由证据丰富度给出
        self.assertEqual(ctx["triage"]["priority"], "P0")
        self.assertGreater(result.confidence, 0.0)
        self.assertEqual(ctx["triage"]["confidence"], result.confidence)

    def test_llm_unavailable_annotates_marker(self):
        """默认无 AI Profile → AgentLLM degraded → 仍基于真实数据并标注降级。"""
        seed_full_incident()
        ctx = {"event_id": "SE-1", "user": {"id": 1}}
        result = asyncio.run(TriageAgent().run(ctx, {"event_id": "SE-1"}))
        self.assertIn("当前 LLM 服务不可用", result.output)
        self.assertGreater(len(result.evidence), 0)
        self.assertGreater(result.confidence, 0.0)

    def test_llm_available_uses_content(self):
        """Mock AgentLLM.call 返回摘要 → output 直接采用 LLM 文本。"""
        seed_full_incident()
        ctx = {"event_id": "SE-1", "user": {"id": 1}}
        fake = {
            "content": "LLM 研判：高危外连",
            "usage": {},
            "degraded": False,
            "error": None,
        }
        with patch("app.services.agent_llm.AgentLLM.call",
                   new=AsyncMock(return_value=fake)):
            result = asyncio.run(TriageAgent().run(ctx, {"event_id": "SE-1"}))
        self.assertEqual(result.output, "LLM 研判：高危外连")
        self.assertNotIn("LLM 摘要不可用", result.output)
        self.assertEqual(ctx["triage"]["summary"], "LLM 研判：高危外连")

    def test_run_no_events_returns_zero_confidence(self):
        ctx = {"event_id": "NOPE", "user": {"id": 1}}
        result = asyncio.run(TriageAgent().run(ctx, {"event_id": "NOPE"}))
        self.assertEqual(result.confidence, 0.0)
        self.assertEqual(result.evidence, [])


# ───────────────────────── InvestigatorAgent ─────────────────────────
class TestInvestigatorAgent(IsolatedDBTestCase):
    def test_instantiation_and_rootcause_lazy_fallback(self):
        a = InvestigatorAgent()
        self.assertEqual(a.name, "investigator_agent")
        self.assertFalse(a.requires_hitl)
        # RootCauseAgent 已实现（A4 ③：B2 修复后不再为 None），懒导入返回真实类
        self.assertIsNotNone(_inv_mod.RootCauseAgent)

    def test_run_produces_timeline_and_local_root_cause(self):
        seed = seed_full_incident()
        ctx = {"host_id": seed["host_id"], "user": {"id": 1}}
        with patch("app.services.agents.data_provider.retrieve_cases",
                   return_value=[]):
            result = asyncio.run(InvestigatorAgent().run(ctx, {}))
        self.assertIsInstance(result, AgentResult)
        self.assertEqual(result.stage, "investigation")
        self.assertGreater(len(result.evidence), 0)
        inv = ctx["investigation"]
        self.assertGreater(len(inv["timeline"]), 0)
        # 本地进程树回溯兜底 + RootCauseAgent 增强说明（现文案）
        self.assertIn("RootCauseAgent 增强", inv["root_cause"])
        self.assertIn("第一触发点", inv["root_cause"])

    def test_llm_unavailable_still_produces_output(self):
        seed = seed_full_incident()
        ctx = {"host_id": seed["host_id"], "user": {"id": 1}}
        with patch("app.services.agents.data_provider.retrieve_cases",
                   return_value=[]):
            result = asyncio.run(InvestigatorAgent().run(ctx, {}))
        self.assertIn("当前 LLM 服务不可用", result.output)


# ───────────────────────── ResponderAgent ─────────────────────────
class TestResponderAgent(IsolatedDBTestCase):
    def test_metadata_requires_hitl(self):
        a = ResponderAgent()
        self.assertEqual(a.name, "responder_agent")
        self.assertTrue(a.requires_hitl)

    def test_derive_action_block_ip(self):
        logs = [{"severity": "high", "source_ip": "8.8.8.8"}]
        # A4 ①：签名现为 _derive_action(host, logs, sec_events, investigation)
        action, target, rollback = ResponderAgent._derive_action(None, logs, [], {})
        self.assertEqual(action, "block_ip")
        self.assertEqual(target, {"ip": "8.8.8.8"})
        self.assertTrue(rollback.get("reversible"))

    def test_derive_action_isolate_host(self):
        host = {"hostname": "H1", "id": 7}
        action, target, rollback = ResponderAgent._derive_action(host, [], [], {})
        self.assertEqual(action, "isolate_host")
        self.assertEqual(target, {"hostname": "H1", "host_id": 7})

    def test_derive_action_export_report_fallback(self):
        action, target, rollback = ResponderAgent._derive_action(None, [], [], {})
        self.assertEqual(action, "export_report")
        self.assertEqual(target, {"report_type": "incident"})

    def test_run_writes_responder_action_and_hitl(self):
        seed = seed_full_incident()
        ctx = {
            "host_id": seed["host_id"],
            "investigation": {"summary": "x", "evidence": []},
            "triage": {"confidence": 0.8},
            "user": {"id": 1},
        }
        result = asyncio.run(ResponderAgent().run(ctx, {}))
        self.assertIsInstance(result, AgentResult)
        self.assertEqual(result.stage, "response")
        self.assertTrue(result.hitl)
        ra = ctx["responder_action"]
        self.assertEqual(ra["action"], "block_ip")
        self.assertEqual(ra["target"], {"ip": "8.8.8.8"})
        self.assertIn("auto_rollback_plan", ra)
        # 证据中含处置动作 ref
        self.assertTrue(any(e.get("type") == "responder_action" for e in result.evidence))

    def test_execute_action_writes_disposition(self):
        """execute_action 经 ActionService 执行并写 event_disposition_log。"""
        # 写一个安全事件供处置记录关联
        with get_connection() as conn:
            conn.execute("INSERT INTO cases (name) VALUES ('c')")
            case_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.execute(
                "INSERT INTO hosts (case_id, hostname, ip_address, os_type) "
                "VALUES (?, 'H', '1.2.3.4', 'Linux')", (case_id,))
            conn.execute(
                "INSERT INTO security_events "
                "(id, timestamp, host_id, event_type, event_key, severity) "
                "VALUES (?, '2026-07-18 11:00:00', ?, 'malware', 'ek2', 'high')",
                ("SE-EXEC", case_id))
        mock_exec = AsyncMock(return_value={
            "success": True, "action": "block_ip",
            "status": "completed", "result": {"ip": "8.8.8.8"},
        })
        with patch("app.services.action_service.ActionService.execute",
                   new=mock_exec):
            resp = ResponderAgent()
            exec_result, rollback = asyncio.run(
                resp.execute_action("block_ip", {"ip": "8.8.8.8"},
                                    event_id="SE-EXEC", operator="admin")
            )
        mock_exec.assert_awaited_once_with("block_ip", {"ip": "8.8.8.8"})
        self.assertTrue(rollback.get("reversible"))
        # 验证写库：event_disposition_log 应有该事件记录
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM event_disposition_log WHERE event_id=?",
                ("SE-EXEC",)).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["action"], "block_ip")
        self.assertEqual(row["operator"], "admin")


# ───────────────────────── ReporterAgent ─────────────────────────
class TestReporterAgent(IsolatedDBTestCase):
    def test_metadata(self):
        a = ReporterAgent()
        self.assertEqual(a.name, "reporter_agent")
        self.assertFalse(a.requires_hitl)

    def test_run_aggregates_stages_and_marks_llm_unavailable(self):
        ctx = {
            "triage": {"summary": "分诊：P0 高危",
                       "evidence": [{"ref": "security_events.id=SE-1"}]},
            "investigation": {"summary": "调查：evil.exe 外连",
                              "evidence": [{"ref": "process_events.id=9"}]},
            "response": {"summary": "处置：封禁 8.8.8.8",
                         "evidence": [{"ref": "normalized_logs.id=5"}]},
        }
        task = {"run_id": "run_rep1", "hitl_decision": {}}
        with patch("app.services.knowledge_retriever.KnowledgeRetriever.rebuild_seed_index",
                   new=MagicMock()):
            result = asyncio.run(ReporterAgent().run(ctx, task))
        self.assertIsInstance(result, AgentResult)
        self.assertEqual(result.stage, "report")
        self.assertIn("安全事件复盘报告", result.output)
        self.assertIn("HITL 审批", result.output)
        self.assertIn("当前 LLM 服务不可用", result.output)
        self.assertIsInstance(result.confidence, float)
        self.assertGreater(result.confidence, 0.0)
        self.assertGreater(len(result.evidence), 0)

    def test_run_does_not_write_cases(self):
        """行为契约（A4 ⑤）：reporter_agent.py:71-73 已停用写 cases（避免污染
        案件管理列表），报告内容存 agent_run_steps.output_json 兜底。

        此用例保护该设计决策：报告不写 cases，cases 计数保持不变。
        """
        with get_connection() as conn:
            before = conn.execute(
                "SELECT COUNT(*) FROM cases").fetchone()[0]
        task = {"run_id": "run_sink1", "hitl_decision": {}}
        with patch("app.services.knowledge_retriever.KnowledgeRetriever.rebuild_seed_index",
                   new=MagicMock()):
            asyncio.run(ReporterAgent().run({}, task))
        with get_connection() as conn:
            after = conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
        self.assertEqual(after, before)  # 报告不写 cases

    def test_run_reads_stage_outputs_from_db(self):
        """ReporterAgent 能从 agent_run_steps 读取各阶段输出（跨请求鲁棒）。"""
        run_id = "run_db1"
        AgentRun.create(run_id=run_id, title="t", user_id=1)
        AgentRunStep.add(run_id=run_id, stage="triage", agent="triage_agent",
                        status="success", output_json={"output": "DB分诊结论"})
        AgentRunStep.add(run_id=run_id, stage="investigation", agent="investigator_agent",
                        status="success", output_json={"output": "DB调查结论"})
        AgentRunStep.add(run_id=run_id, stage="response", agent="responder_agent",
                        status="success", output_json={"output": "DB处置结论"})
        task = {"run_id": run_id, "hitl_decision": {}}
        with patch("app.services.knowledge_retriever.KnowledgeRetriever.rebuild_seed_index",
                   new=MagicMock()):
            result = asyncio.run(ReporterAgent().run({}, task))
        self.assertIn("DB分诊结论", result.output)
        self.assertIn("DB调查结论", result.output)
        self.assertIn("DB处置结论", result.output)


if __name__ == "__main__":
    import unittest
    unittest.main(verbosity=2)
