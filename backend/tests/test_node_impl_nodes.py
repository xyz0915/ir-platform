"""T05-4：parallel / data-process / intel-query / action / output / mcp-tool / intel-source / llm 节点单元测试。

设计依据：``node-impl/design.md`` A3.4-A3.11 + B4 验收标准；``node-impl/dev.md`` §2.2/§2.3。

外部服务一律 mock（B3 共享知识 #8）：
- EnrichmentService（intel-query）、ActionService / disposition_service（action）、
  KnowledgeRetriever（output）、ToolRegistry / McpTool.get_by_id（mcp-tool）、
  ThreatIntelProviderConfig.load（intel-source）、AiConfigProfile / AgentLLM（llm）。

**零 DB 策略**：除 McpTool.get_by_id stub 外不触 DB（毫秒级执行）。
"""
import asyncio
import sys
import types
import uuid
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.models.ai_config import AiConfigProfile  # noqa: E402
from app.models.mcp import McpTool  # noqa: E402
from app.schemas.ai_advanced import ActionResult  # noqa: E402
from app.services import agent_llm as agent_llm_module  # noqa: E402
from app.services.action_service import ActionService  # noqa: E402
from app.services.agents.pipeline_engine import PipelineEngine  # noqa: E402
from app.services.enrichment_service import EnrichmentService  # noqa: E402
from app.services.knowledge_retriever import KnowledgeRetriever  # noqa: E402
from app.services.mcp.registry import ToolRegistry  # noqa: E402
from app.models.threat_intel import ThreatIntelProviderConfig  # noqa: E402

# 显式导入共享 fixture（pytest 解析）
from helpers.agent_test_utils import fake_profiles, mock_profiles, mock_llm_ok, mock_tools  # noqa: F401


@pytest.fixture(autouse=True)
def _stub_mcp_tool_lookup(monkeypatch):
    """让 _tool_timeout 不触碰任何 DB：McpTool.get_by_id 恒返回 None。"""
    monkeypatch.setattr(McpTool, "get_by_id", staticmethod(lambda tool_id: None))


def _run(coro):
    return asyncio.run(coro)


def _ctx(**kw) -> dict:
    return {
        "host_id": kw.get("host_id", "H1"),
        "event_id": kw.get("event_id"),
        "stages": kw.get("stages", []),
        "input_params": kw.get("input_params", {}),
        "context_vars": kw.get("context_vars", {}),
    }


# ──────────────────────────────────────────────────────────────
# parallel
# ──────────────────────────────────────────────────────────────
class TestParallelNode:
    def test_branches_output(self):
        eng = PipelineEngine()
        r = _run(eng._run_parallel(_ctx(), {"branches": [
            {"label": "分支A", "target": "network_analysis"},
            {"label": "分支B", "target": "file_analysis"},
        ]}, "real"))
        s = r["structured"]
        assert s["branch_count"] == 2
        assert s["parallel_mode"] == "batch"
        assert s["branches"][0]["label"] == "分支A"
        assert s["branches"][1]["target"] == "file_analysis"

    def test_empty_branches(self):
        eng = PipelineEngine()
        r = _run(eng._run_parallel(_ctx(), {}, "real"))
        assert r["structured"]["branch_count"] == 0

    def test_non_dict_branches_skipped(self):
        eng = PipelineEngine()
        r = _run(eng._run_parallel(_ctx(), {"branches": ["bad", {"label": "A", "target": "x"}]}, "real"))
        assert r["structured"]["branch_count"] == 1


# ──────────────────────────────────────────────────────────────
# data-process
# ──────────────────────────────────────────────────────────────
class TestDataProcessNode:
    def _dp_ctx(self):
        return _ctx(stages=[{
            "name": "file_analysis",
            "status": "completed",
            "output": {"structured": {"files": [
                {"file_name": "a.dll", "path": "/x/a.dll"},
                {"file_name": "b.exe", "path": "/x/b.exe"},
                {"file_name": "c.dll", "path": "/x/c.dll"},
            ]}},
        }])

    def test_full_chain_select_filter_rename_limit(self):
        eng = PipelineEngine()
        r = _run(eng._run_data_process(self._dp_ctx(), {
            "source": "{dep:file_analysis}.structured.files",
            "operations": [
                {"op": "select", "fields": ["file_name", "path"]},
                {"op": "filter", "field": "file_name", "regex": r"\.dll$"},
                {"op": "rename", "mapping": {"file_name": "name"}},
                {"op": "limit", "n": 10},
            ],
        }, "real"))
        s = r["structured"]
        assert s["processed_count"] == 2
        assert s["transformed"] == [
            {"name": "a.dll", "path": "/x/a.dll"},
            {"name": "c.dll", "path": "/x/c.dll"},
        ]
        assert s["errors"] == []

    def test_limit_truncates(self):
        eng = PipelineEngine()
        r = _run(eng._run_data_process(self._dp_ctx(), {
            "source": "{dep:file_analysis}.structured.files",
            "operations": [{"op": "limit", "n": 1}],
        }, "real"))
        assert r["structured"]["processed_count"] == 1

    def test_source_missing_returns_empty_hint(self):
        """source 缺失且无可用 stage → 空结果 + 提示，不抛异常。"""
        eng = PipelineEngine()
        r = _run(eng._run_data_process(_ctx(), {"operations": [{"op": "select", "fields": ["a"]}]}, "real"))
        assert r["structured"]["processed_count"] == 0
        assert "处理完成" in r["output"]

    def test_bad_op_records_error_continues(self):
        """未知 op 记 errors 但不阻断后续 op（fail-safe）。"""
        eng = PipelineEngine()
        r = _run(eng._run_data_process(self._dp_ctx(), {
            "source": "{dep:file_analysis}.structured.files",
            "operations": [
                {"op": "bogus"},
                {"op": "limit", "n": 1},
            ],
        }, "real"))
        assert any("未知" in e for e in r["structured"]["errors"])
        assert r["structured"]["processed_count"] == 1  # 后续 op 仍生效


# ──────────────────────────────────────────────────────────────
# intel-query
# ──────────────────────────────────────────────────────────────
class _FakeEnrichment:
    """EnrichmentService.instance() 的替身：记录调用并返回固定 record。"""
    def __init__(self):
        self.calls = []

    def enrich_ioc(self, ioc_id, ioc_type, ioc_value, provider_name=None, force_refresh=False):
        self.calls.append((ioc_id, ioc_type, ioc_value, provider_name, force_refresh))
        return {
            "ioc_type": ioc_type,
            "ioc_value": ioc_value,
            "provider": provider_name or "test-provider",
            "risk_score": 90,
            "judgments": ["malicious"],
            "threat_level": "high",
            "providers": [provider_name or "test-provider"],
        }


@pytest.fixture()
def mock_enrichment(monkeypatch):
    fake = _FakeEnrichment()
    monkeypatch.setattr(EnrichmentService, "instance", staticmethod(lambda: fake))
    return fake


class TestIntelQueryNode:
    def test_unsupported_type_hash_friendly_error(self):
        eng = PipelineEngine()
        r = _run(eng._run_intel_query(_ctx(), {"ioc_type": "hash", "ioc_value": "abcd1234"}, "real"))
        assert r["status"] == "failed"
        assert r["error"] == "unsupported_ioc_type"
        assert "仅支持 ip/domain" in r["output"]

    def test_missing_value_friendly_error(self):
        eng = PipelineEngine()
        r = _run(eng._run_intel_query(_ctx(), {"ioc_type": "ip", "ioc_value": ""}, "real"))
        assert r["status"] == "failed"
        assert r["error"] == "missing_ioc_value"

    def test_ip_goes_to_enrichment_service(self, mock_enrichment):
        """ip 走 EnrichmentService（mock 断言参数 None/ip/value/None/False）。"""
        eng = PipelineEngine()
        r = _run(eng._run_intel_query(_ctx(), {"ioc_type": "ip", "ioc_value": "8.8.8.8"}, "real"))
        # 成功路径 runner 不含 status 键（B3 #2：仅 blocked/failed 时出现）
        assert r.get("status") != "failed", r.get("error")
        assert mock_enrichment.calls == [(None, "ip", "8.8.8.8", None, False)]
        assert r["structured"]["risk_score"] == 90
        assert r["structured"]["threat_level"] == "high"

    def test_domain_with_provider(self, mock_enrichment):
        eng = PipelineEngine()
        r = _run(eng._run_intel_query(_ctx(), {"ioc_type": "domain", "ioc_value": "evil.example", "provider_name": "vt"}, "real"))
        assert r.get("status") != "failed", r.get("error")
        assert mock_enrichment.calls == [(None, "domain", "evil.example", "vt", False)]

    def test_enrichment_exception_fail_safe(self, monkeypatch):
        """EnrichmentService 抛异常 → status=failed + 可读 error，不抛 500。"""
        class _Boom:
            def enrich_ioc(self, *a, **kw):
                raise RuntimeError("quota exceeded")
        monkeypatch.setattr(EnrichmentService, "instance", staticmethod(lambda: _Boom()))
        eng = PipelineEngine()
        r = _run(eng._run_intel_query(_ctx(), {"ioc_type": "ip", "ioc_value": "8.8.8.8"}, "real"))
        assert r["status"] == "failed"
        assert "intel_query_failed" in r["error"]
        assert "quota exceeded" in r["output"]


# ──────────────────────────────────────────────────────────────
# action
# ──────────────────────────────────────────────────────────────
@pytest.fixture()
def mock_action_service(monkeypatch):
    calls = []

    async def _execute(action, target):
        calls.append((action, target))
        return ActionResult(success=True, action=action, status="done", result={"ok": True})

    monkeypatch.setattr(ActionService, "execute", _execute)
    return calls


@pytest.fixture()
def mock_disposition(monkeypatch):
    calls = []

    def _add(event_id, action, operator="", comment=""):
        calls.append((event_id, action, operator, comment))
        return {"id": 1}

    import app.services.disposition_service as disp_mod
    monkeypatch.setattr(disp_mod, "add_disposition", _add)
    return calls


class TestActionNode:
    def test_require_hitl_returns_signal(self):
        eng = PipelineEngine()
        r = _run(eng._run_action(_ctx(), {"action": "block_ip", "target": {"ip": "1.1.1.1"}, "require_hitl": True}, "real"))
        assert r["hitl_triggered"] is True
        assert r["structured"]["mode"] == "hitl"
        assert r["structured"]["action"] == "block_ip"

    def test_direct_execute_calls_action_service(self, mock_action_service):
        """require_hitl=false → ActionService.execute 直执行（mock 断言参数）。"""
        eng = PipelineEngine()
        r = _run(eng._run_action(_ctx(), {"action": "block_ip", "target": {"ip": "8.8.8.8"}}, "real"))
        assert mock_action_service == [("block_ip", {"ip": "8.8.8.8"})]
        assert r["structured"]["executed"]["success"] is True
        assert r["structured"]["action"] == "block_ip"

    def test_action_service_exception_fail_safe(self, monkeypatch):
        """executor 异常 → executed success=False，不抛。"""
        async def _boom(action, target):
            raise RuntimeError("executor down")
        monkeypatch.setattr(ActionService, "execute", _boom)
        eng = PipelineEngine()
        r = _run(eng._run_action(_ctx(), {"action": "block_ip", "target": {}}, "real"))
        assert r["structured"]["executed"]["success"] is False
        assert "executor down" in r["structured"]["executed"]["error"]

    def test_disposition_written_on_event(self, mock_action_service, mock_disposition):
        """有 event_id → add_disposition 写入（mock 断言）。"""
        eng = PipelineEngine()
        _run(eng._run_action(_ctx(event_id="SE-1"), {"action": "block_ip", "target": {"ip": "1.1.1.1"}, "operator": "qa"}, "real"))
        assert len(mock_disposition) == 1
        ev_id, action, operator, comment = mock_disposition[0]
        assert ev_id == "SE-1"
        assert action == "block_ip"
        assert operator == "qa"

    def test_default_operator_admin(self, mock_action_service, mock_disposition):
        """无 operator → 缺省 admin。"""
        eng = PipelineEngine()
        r = _run(eng._run_action(_ctx(event_id="SE-1"), {"action": "block_ip", "target": {}}, "real"))
        assert r["structured"]["operator"] == "admin"


# ──────────────────────────────────────────────────────────────
# output
# ──────────────────────────────────────────────────────────────
@pytest.fixture()
def mock_knowledge_retriever(monkeypatch):
    calls = []

    def _retrieve(analysis_data, limit=5, structured=False):
        calls.append((analysis_data, limit, structured))
        return [{"text": "勒索软件分析", "score": 0.9}, {"text": "另一条", "score": 0.5}]

    monkeypatch.setattr(KnowledgeRetriever, "retrieve", _retrieve)
    return calls


class TestOutputNode:
    def test_keyword_retrieve(self, mock_knowledge_retriever):
        eng = PipelineEngine()
        r = _run(eng._run_output(_ctx(), {"keyword": "勒索软件", "category": "malware", "limit": 5}, "real"))
        assert r["structured"]["count"] == 2
        assert r["structured"]["keyword"] == "勒索软件"
        # 断言传给 retrieve 的 analysis_data 含 summary 关键词
        assert mock_knowledge_retriever[0][0]["summary"] == "勒索软件"
        assert mock_knowledge_retriever[0][1] == 5
        assert mock_knowledge_retriever[0][2] is True

    def test_empty_keyword_falls_back(self, mock_knowledge_retriever):
        """keyword 空 → 用前置 stage 输出拼接（_extract_keywords 兜底）。"""
        eng = PipelineEngine()
        ctx = _ctx(stages=[{"name": "root_cause", "status": "completed", "output": {"output": "发现勒索软件感染"}}])
        r = _run(eng._run_output(ctx, {}, "real"))
        assert "勒索软件" in r["structured"]["keyword"]
        assert r["structured"]["count"] == 2

    def test_retrieve_exception_fallback_empty(self, monkeypatch):
        """检索异常 → 空结果 + count=0，不抛。"""
        def _boom(*a, **kw):
            raise RuntimeError("chroma down")
        monkeypatch.setattr(KnowledgeRetriever, "retrieve", _boom)
        eng = PipelineEngine()
        r = _run(eng._run_output(_ctx(), {"keyword": "x"}, "real"))
        assert r["structured"]["count"] == 0
        assert r["structured"]["items"] == []


# ──────────────────────────────────────────────────────────────
# mcp-tool
# ──────────────────────────────────────────────────────────────
class TestMcpToolNode:
    def test_missing_tool_id_error(self):
        eng = PipelineEngine()
        r = _run(eng._run_mcp_tool(_ctx(), {"tool_id": "", "args": {}}, "real"))
        assert r["status"] == "failed"
        assert r["error"] == "missing_tool_id"

    def test_tool_call_with_args(self, mock_tools):
        """tool_id → ToolRegistry.call_tool（mock 断言 args 透传）。"""
        eng = PipelineEngine()
        r = _run(eng._run_mcp_tool(_ctx(), {"tool_id": "vt_scan", "args": {"hash": "abc"}}, "real"))
        assert r["structured"]["used"] is True
        assert r["structured"]["tool_id"] == "vt_scan"
        assert r["structured"]["results"][0]["result"] == "result-vt_scan"

    def test_tool_call_args_include_host_event(self, mock_tools):
        """args 注入 host_id/event_id（_run_tools_safe 通用上下文）。"""
        seen = {}

        def _handler(tool_id, args):
            seen.update(args)
            return {"ok": True, "tool_id": tool_id, "result": "r"}
        mock_tools["handler"] = _handler
        eng = PipelineEngine()
        _run(eng._run_mcp_tool(_ctx(event_id="SE-1"), {"tool_id": "vt_scan", "args": {"hash": "abc"}}, "real"))
        assert seen.get("hash") == "abc"
        assert seen.get("host_id") == "H1"
        assert seen.get("event_id") == "SE-1"

    def test_tool_failure_does_not_block_node(self, mock_tools):
        """工具失败 → evidence 记 failed + errors，但 node 本身 success（不阻断）。"""
        def _fail(tool_id, args):
            return {"ok": False, "tool_id": tool_id, "error": "not registered"}
        mock_tools["handler"] = _fail
        eng = PipelineEngine()
        r = _run(eng._run_mcp_tool(_ctx(), {"tool_id": "missing_tool", "args": {}}, "real"))
        # 工具失败不阻断 node：成功路径无 status 键（B3 #2）
        assert r.get("status") != "failed"
        assert r["structured"]["used"] is False
        assert any("not registered" in e for e in r["structured"]["errors"])


# ──────────────────────────────────────────────────────────────
# intel-source
# ──────────────────────────────────────────────────────────────
@pytest.fixture()
def mock_provider_config(monkeypatch):
    configs = [
        {"name": "vt", "type": "vt", "base_url": "https://vt", "enabled": True, "rate_limit_qps": 5, "api_key_ref": "VT_KEY", "endpoints": ["/search"]},
        {"name": "tb", "type": "threatbook", "base_url": "https://tb", "enabled": False, "rate_limit_qps": 1, "api_key_ref": "TB_KEY", "endpoints": ["/query"]},
    ]
    monkeypatch.setattr(ThreatIntelProviderConfig, "load", staticmethod(lambda: configs))
    return configs


class TestIntelSourceNode:
    def test_sources_exclude_api_key_ref(self, mock_provider_config):
        """返回源列表且不含 api_key_ref（不泄露）。"""
        eng = PipelineEngine()
        r = _run(eng._run_intel_source(_ctx(), {"enabled_only": True}, "real"))
        sources = r["structured"]["sources"]
        assert len(sources) == 1  # 仅 enabled
        assert sources[0]["name"] == "vt"
        assert "api_key_ref" not in sources[0]
        assert r["structured"]["count"] == 1

    def test_enabled_only_false_returns_all(self, mock_provider_config):
        eng = PipelineEngine()
        r = _run(eng._run_intel_source(_ctx(), {"enabled_only": False}, "real"))
        assert r["structured"]["count"] == 2
        for s in r["structured"]["sources"]:
            assert "api_key_ref" not in s

    def test_provider_filter(self, mock_provider_config):
        eng = PipelineEngine()
        r = _run(eng._run_intel_source(_ctx(), {"enabled_only": False, "provider": "tb"}, "real"))
        assert r["structured"]["count"] == 1
        assert r["structured"]["sources"][0]["name"] == "tb"

    def test_load_exception_fail_safe(self, monkeypatch):
        def _boom():
            raise RuntimeError("config missing")
        monkeypatch.setattr(ThreatIntelProviderConfig, "load", staticmethod(_boom))
        eng = PipelineEngine()
        r = _run(eng._run_intel_source(_ctx(), {"enabled_only": True}, "real"))
        assert r["structured"]["count"] == 0
        assert r["structured"]["message"] == "未配置情报源。"


# ──────────────────────────────────────────────────────────────
# llm（allow_default_llm 增强）
# ──────────────────────────────────────────────────────────────
class TestLlmNode:
    def test_default_no_network(self, mock_profiles, mock_llm_ok):
        """allow_default_llm=false（默认）→ 不调用 LLM（零意外联网），静态合成输出。"""
        eng = PipelineEngine()
        r = _run(eng._run_llm(_ctx(), {"query": "test", "prompt": ""}, "real"))
        assert r["structured"]["used_llm"] is False
        assert r["structured"]["allow_default_llm"] is False
        assert mock_llm_ok == []  # 无任何 LLM 调用
        assert "合成" in r["output"]

    def test_allow_default_llm_uses_active_profile(self, mock_profiles, mock_llm_ok):
        """allow_default_llm=true 且无显式 profile → 用激活 profile（mock 断言调用）。"""
        eng = PipelineEngine()
        r = _run(eng._run_llm(_ctx(), {"query": "test", "prompt": "", "allow_default_llm": True}, "real"))
        assert r["structured"]["used_llm"] is True
        assert r["structured"]["allow_default_llm"] is True
        assert len(mock_llm_ok) == 1
        # 激活 profile = id=1（fake_profiles）
        assert mock_llm_ok[0]["profile"]["id"] == 1

    def test_explicit_profile_calls_without_switch(self, mock_profiles, mock_llm_ok):
        """显式 model_profile → 即使 allow_default_llm=false 也调用 LLM（显式授权）。"""
        eng = PipelineEngine()
        r = _run(eng._run_llm(_ctx(), {"query": "test", "prompt": "", "model_profile": "2"}, "real"))
        assert r["structured"]["used_llm"] is True
        assert len(mock_llm_ok) == 1
        assert mock_llm_ok[0]["profile"]["id"] == 2


# ──────────────────────────────────────────────────────────────
# preset agents 与 runner 键一致性（B3 共享知识 #1）
# ──────────────────────────────────────────────────────────────
class TestPresetAgentRegistryConsistency:
    def test_new_preset_names_match_runner_keys(self):
        """10 个新 preset agent 的 name 都能命中 _get_node_runner（防 guard/guardrail 类错位重演）。"""
        from app.services.agents.preset_data import PRESET_AGENTS
        eng = PipelineEngine()
        new_names = ["guard", "hitl", "condition", "parallel", "data-process", "intel-query", "action", "output", "mcp-tool", "intel-source"]
        preset_names = {a["name"] for a in PRESET_AGENTS}
        for n in new_names:
            assert n in preset_names, f"preset agent '{n}' 缺失"
            assert eng._get_node_runner(n) is not None, f"runner 键 '{n}' 缺失"

    def test_new_presets_type_custom_hitl_only_hitl(self):
        """新 preset：type='custom'；hitl=True 仅 hitl 节点。"""
        from app.services.agents.preset_data import PRESET_AGENTS
        new_names = ["guard", "hitl", "condition", "parallel", "data-process", "intel-query", "action", "output", "mcp-tool", "intel-source"]
        for a in PRESET_AGENTS:
            if a["name"] in new_names:
                assert a["type"] == "custom"
                assert a["hitl"] == (a["name"] == "hitl")
