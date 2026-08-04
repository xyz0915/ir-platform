"""P1 测试：自动 RAG 注入钩子（知识增强）— 默认关红线 + 启用后行为。

依据：
- ``p1-design.md`` §2（钩子伪代码/触发条件/格式/开关机制）与 §6 验收标准
  A（向后兼容红线）与 B（知识增强钩子）；
- ``p1-dev.md`` §2.4（``pipeline_engine.py`` 6 个新方法 + ``_call_llm_safe`` ctx 参数
  + 三处接入点）。

覆盖（按任务 T1/T2）：
- T1 默认关红线：``_enhance_with_knowledge`` 直接返回原 prompt（零开销零行为变化）；
  ``_call_llm_safe`` 不传 ctx 行为完全不变（不触发增强）；``_run_llm``/``_run_unknown``
  默认关时 LLM 收到的 prompt 无 ``[知识增强]`` 注入；钩子不写回 ``run.ctx``。
- T2 启用后行为：全局开 → 检索命中 → prompt 前置注入 ``[知识增强]`` 块（Top-K 序号化
  formatted_text）；节点 opt-in/opt-out 覆盖；空命中不注入；retrieve 异常/超时不阻断；
  ``rag_top_k`` 夹取 [1,10]；``_format_knowledge_block`` 格式正确；``_build_rag_analysis_data``
  构造 summary/category/_raw_data（mock data_provider/DB），无 host 时 fail-safe。

约束：所有 LLM/检索全部 mock，无真实联网、无真实 chroma 依赖；用例相互独立（monkeypatch 自愈）。
"""

import asyncio
import sys
import time
from pathlib import Path
from types import SimpleNamespace

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import pytest

from app.config import settings
from app.services import agent_llm as agent_llm_module
from app.services.agents.pipeline_engine import PipelineEngine
from app.services.knowledge_retriever import KnowledgeRetriever


def _run(coro):
    """同步执行协程（每个用例独立事件循环）。"""
    return asyncio.run(coro)


def _make_ctx(**overrides):
    """构造最小节点执行上下文。"""
    ctx = {
        "agent_name": "llm_node",
        "event_id": "evt-1",
        "host_id": 1,
        "input_params": {},
        "context_vars": {"user": {"id": 1}},
        "stages": [],
    }
    ctx.update(overrides)
    return ctx


def _hits(n=2):
    """结构化命中样本（含来源/维度/引用附注字段）。"""
    return [
        {
            "formatted_text": "发现 powershell 拉起 rundll32 的无文件攻击链",
            "evidence_type": "process",
            "_source_collection": "ir_rules",
            "entry_ref": "rule_001",
        },
        {
            "formatted_text": "外连 IP 命中 Tor 出口节点",
            "evidence_type": "network",
            "_source_collection": "ir_seed",
            "entry_ref": "seed_002",
        },
    ][:n]


def _patch_retrieve(monkeypatch, hits):
    """把 KnowledgeRetriever.retrieve（静态方法）替换为返回 hits 的桩。"""
    monkeypatch.setattr(
        KnowledgeRetriever,
        "retrieve",
        staticmethod(lambda analysis_data, limit=5, structured=False: hits),
    )


def _patch_fake_llm(monkeypatch, prompts_out):
    """把 AgentLLM 替换为记录 prompt 的成功实现。"""
    class _FakeLLM:
        def __init__(self, profile=None):
            self.profile = profile

        async def call(self, prompt, user=None, trace_id=None, **kwargs):
            prompts_out.append(prompt)
            return {"content": "llm-ok", "degraded": False, "usage": {}}

    monkeypatch.setattr(agent_llm_module, "AgentLLM", _FakeLLM)
    return _FakeLLM


def _make_agent_def(**overrides):
    """最小 AgentDefinition 桩（_run_unknown 用到的属性）。"""
    base = dict(
        name="custom_analyzer",
        display_name="自定义分析",
        description="分析 agent",
        data_sources=[],
        tools=[],
        depends_on=[],
        model_profile="1",
        config={},
    )
    base.update(overrides)
    return SimpleNamespace(**base)


# ============================================================================
# T1 默认关红线（最高优先级）
# ============================================================================


class TestDefaultOffRedLine:
    def test_settings_default_off(self):
        """未设 env 时 settings.IR_RAG_AUTO_ENHANCE 默认 False（验收 A 第 1 条）。"""
        assert settings.IR_RAG_AUTO_ENHANCE is False

    def test_enhance_default_off_returns_original_prompt_no_retrieve(self, monkeypatch):
        """默认关：_enhance_with_knowledge 直接返回原 prompt，且不触发检索（零开销）。"""
        def _should_not_be_called(*args, **kwargs):
            raise AssertionError("默认关不应触发 retrieve")

        monkeypatch.setattr(KnowledgeRetriever, "retrieve", staticmethod(_should_not_be_called))
        engine = PipelineEngine()
        ctx = _make_ctx()
        out = _run(engine._enhance_with_knowledge(ctx, "原始 prompt"))
        assert out == "原始 prompt"

    def test_call_llm_safe_no_ctx_does_not_enhance(self, monkeypatch):
        """存量调用不传 ctx → _enhance_with_knowledge 不被调用（验收 A：行为完全不变）。"""
        engine = PipelineEngine()
        enhance_calls = []

        async def _fake_enhance(ctx, prompt):
            enhance_calls.append(prompt)
            return prompt

        monkeypatch.setattr(engine, "_enhance_with_knowledge", _fake_enhance)
        llm_prompts = []
        _patch_fake_llm(monkeypatch, llm_prompts)

        res = _run(engine._call_llm_safe({"id": 1, "profile_name": "p"}, "原始 prompt", {"id": 1}))
        assert res["used"] is True
        assert llm_prompts == ["原始 prompt"]      # LLM 收到原 prompt
        assert enhance_calls == []                  # 钩子未触发

    def test_call_llm_safe_ctx_default_off_prompt_unchanged(self, monkeypatch):
        """传 ctx 但全局关：仍不注入，LLM 收到原 prompt（节点级未 opt-in）。"""
        engine = PipelineEngine()
        llm_prompts = []
        _patch_fake_llm(monkeypatch, llm_prompts)
        ctx = _make_ctx(input_params={"prompt": "分析此事件"})
        res = _run(engine._call_llm_safe({"id": 1}, "分析此事件", {"id": 1}, ctx=ctx))
        assert res["used"] is True
        assert llm_prompts == ["分析此事件"]

    def test_run_llm_default_off_prompt_unchanged(self, monkeypatch):
        """默认关整节点：_run_llm 内部 LLM 收到的 prompt 无 [知识增强]（mock 断言原 prompt）。"""
        engine = PipelineEngine()
        llm_prompts = []
        _patch_fake_llm(monkeypatch, llm_prompts)
        monkeypatch.setattr(engine, "_resolve_llm_profile", lambda mp: {"id": 1, "profile_name": "p"})

        ctx = _make_ctx(input_params={"prompt": "分析此事件", "model_profile": "1"})
        result = _run(engine._run_llm(ctx, ctx["input_params"], "real"))
        assert result["structured"]["used_llm"] is True
        assert llm_prompts == ["分析此事件"]
        assert "[知识增强]" not in llm_prompts[0]

    def test_run_unknown_default_off_prompt_unchanged(self, monkeypatch):
        """默认关自定义智能体：_run_unknown 内 LLM 收到的 prompt 无注入。"""
        engine = PipelineEngine()
        llm_prompts = []
        _patch_fake_llm(monkeypatch, llm_prompts)
        monkeypatch.setattr(engine, "_resolve_llm_profile", lambda mp: {"id": 1})

        agent_def = _make_agent_def(model_profile="1")
        ctx = _make_ctx(input_params={"prompt": "未知节点 prompt"})
        result = _run(engine._run_unknown(agent_def, ctx))
        assert result["structured"]["used_llm"] is True
        assert llm_prompts == ["未知节点 prompt"]

    def test_enhance_no_ctx_write_back(self, monkeypatch):
        """钩子是 ctx 的纯函数：开关开注入后不写回 run.ctx（无跨节点污染，验收 B）。"""
        monkeypatch.setattr(settings, "IR_RAG_AUTO_ENHANCE", True)
        _patch_retrieve(monkeypatch, _hits(1))
        engine = PipelineEngine()
        ctx = _make_ctx(input_params={"prompt": "分析"})
        before = dict(ctx)
        _run(engine._enhance_with_knowledge(ctx, "orig"))
        assert ctx == before


# ============================================================================
# T2 钩子启用后行为
# ============================================================================


class TestEnhanceEnabled:
    def test_global_on_injects_top_k_block(self, monkeypatch):
        """全局开 + 命中 → 前置注入 [知识增强] 块，含 Top-K 序号化 formatted_text。"""
        monkeypatch.setattr(settings, "IR_RAG_AUTO_ENHANCE", True)
        _patch_retrieve(monkeypatch, _hits(2))
        engine = PipelineEngine()
        ctx = _make_ctx(input_params={"prompt": "分析攻击链"})
        out = _run(engine._enhance_with_knowledge(ctx, "原始 prompt"))

        assert out.startswith("[知识增强]")
        assert out.endswith("原始 prompt")
        assert "\n\n原始 prompt" in out            # 前置注入：block + \n\n + 原 prompt
        assert "1. 发现 powershell 拉起 rundll32 的无文件攻击链" in out
        assert "2. 外连 IP 命中 Tor 出口节点" in out
        assert "[/知识增强]" in out

    def test_node_opt_in_global_off(self, monkeypatch):
        """全局关 + 节点 rag_enhance=True → opt-in 生效注入。"""
        monkeypatch.setattr(settings, "IR_RAG_AUTO_ENHANCE", False)
        _patch_retrieve(monkeypatch, _hits(1))
        engine = PipelineEngine()
        ctx = _make_ctx(input_params={"rag_enhance": True, "prompt": "分析"})
        out = _run(engine._enhance_with_knowledge(ctx, "orig"))
        assert out.startswith("[知识增强]")
        assert out.endswith("orig")

    def test_node_opt_out_global_on(self, monkeypatch):
        """全局开 + 节点 rag_enhance=False → opt-out 覆盖，不注入。"""
        monkeypatch.setattr(settings, "IR_RAG_AUTO_ENHANCE", True)
        _patch_retrieve(monkeypatch, _hits(1))
        engine = PipelineEngine()
        ctx = _make_ctx(input_params={"rag_enhance": False, "prompt": "x"})
        out = _run(engine._enhance_with_knowledge(ctx, "orig"))
        assert out == "orig"

    def test_empty_hits_no_inject(self, monkeypatch):
        """空命中 → 不注入、原 prompt。"""
        monkeypatch.setattr(settings, "IR_RAG_AUTO_ENHANCE", True)
        _patch_retrieve(monkeypatch, [])
        engine = PipelineEngine()
        out = _run(engine._enhance_with_knowledge(_make_ctx(), "orig"))
        assert out == "orig"

    def test_retrieve_none_no_inject(self, monkeypatch):
        """retrieve 意外返回 None → 按未命中处理，不注入不抛。"""
        monkeypatch.setattr(settings, "IR_RAG_AUTO_ENHANCE", True)
        _patch_retrieve(monkeypatch, None)
        engine = PipelineEngine()
        out = _run(engine._enhance_with_knowledge(_make_ctx(), "orig"))
        assert out == "orig"

    def test_retrieve_raises_no_block(self, monkeypatch):
        """retrieve 抛异常 → 不注入、不抛，原 prompt 返回（fail-safe）。"""
        monkeypatch.setattr(settings, "IR_RAG_AUTO_ENHANCE", True)

        def _boom(*args, **kwargs):
            raise RuntimeError("chroma down")

        monkeypatch.setattr(KnowledgeRetriever, "retrieve", staticmethod(_boom))
        engine = PipelineEngine()
        out = _run(engine._enhance_with_knowledge(_make_ctx(), "orig"))
        assert out == "orig"

    def test_retrieve_timeout_no_block(self, monkeypatch):
        """检索超时（短 timeout + 慢桩）→ 按未命中处理，不注入不抛。"""
        monkeypatch.setattr(settings, "IR_RAG_AUTO_ENHANCE", True)
        monkeypatch.setattr(settings, "IR_RAG_RETRIEVE_TIMEOUT", 0.05)

        def _slow(*args, **kwargs):
            time.sleep(0.3)  # 超过 timeout，等待被 wait_for 取消
            return _hits(1)

        monkeypatch.setattr(KnowledgeRetriever, "retrieve", staticmethod(_slow))
        engine = PipelineEngine()
        out = _run(engine._enhance_with_knowledge(_make_ctx(), "orig"))
        assert out == "orig"

    def test_run_llm_global_on_injects(self, monkeypatch):
        """整节点链路：全局开 + 命中 → _run_llm 内 LLM 收到的 prompt 已注入。"""
        monkeypatch.setattr(settings, "IR_RAG_AUTO_ENHANCE", True)
        _patch_retrieve(monkeypatch, _hits(1))
        engine = PipelineEngine()
        llm_prompts = []
        _patch_fake_llm(monkeypatch, llm_prompts)
        monkeypatch.setattr(engine, "_resolve_llm_profile", lambda mp: {"id": 1})

        ctx = _make_ctx(input_params={"prompt": "分析此事件", "model_profile": "1"})
        result = _run(engine._run_llm(ctx, ctx["input_params"], "real"))
        assert result["structured"]["used_llm"] is True
        assert llm_prompts[0].startswith("[知识增强]")
        assert "分析此事件" in llm_prompts[0]

    def test_run_unknown_global_on_injects(self, monkeypatch):
        """整节点链路：全局开 + 命中 → _run_unknown 内 LLM 收到的 prompt 已注入。"""
        monkeypatch.setattr(settings, "IR_RAG_AUTO_ENHANCE", True)
        _patch_retrieve(monkeypatch, _hits(1))
        engine = PipelineEngine()
        llm_prompts = []
        _patch_fake_llm(monkeypatch, llm_prompts)
        monkeypatch.setattr(engine, "_resolve_llm_profile", lambda mp: {"id": 1})

        agent_def = _make_agent_def(model_profile="1")
        ctx = _make_ctx(input_params={"prompt": "未知节点 prompt"})
        result = _run(engine._run_unknown(agent_def, ctx))
        assert result["structured"]["used_llm"] is True
        assert llm_prompts[0].startswith("[知识增强]")

    def test_call_llm_safe_ctx_global_on_enhances(self, monkeypatch):
        """_call_llm_safe 传 ctx + 全局开 → 增强一次并注入。"""
        monkeypatch.setattr(settings, "IR_RAG_AUTO_ENHANCE", True)
        _patch_retrieve(monkeypatch, _hits(1))
        engine = PipelineEngine()
        llm_prompts = []
        _patch_fake_llm(monkeypatch, llm_prompts)
        ctx = _make_ctx(input_params={"prompt": "分析"})
        res = _run(engine._call_llm_safe({"id": 1}, "分析", {"id": 1}, ctx=ctx))
        assert res["used"] is True
        assert llm_prompts[0].startswith("[知识增强]")


# ============================================================================
# 开关决策与 Top-K
# ============================================================================


class TestSwitchLogic:
    def test_rag_enabled_default_off(self, monkeypatch):
        monkeypatch.setattr(settings, "IR_RAG_AUTO_ENHANCE", False)
        engine = PipelineEngine()
        assert engine._rag_enabled(_make_ctx()) is False

    def test_rag_enabled_node_opt_in(self, monkeypatch):
        monkeypatch.setattr(settings, "IR_RAG_AUTO_ENHANCE", False)
        engine = PipelineEngine()
        assert engine._rag_enabled(_make_ctx(input_params={"rag_enhance": True})) is True

    def test_rag_enabled_node_opt_out_overrides_global(self, monkeypatch):
        monkeypatch.setattr(settings, "IR_RAG_AUTO_ENHANCE", True)
        engine = PipelineEngine()
        assert engine._rag_enabled(_make_ctx(input_params={"rag_enhance": False})) is False
        assert engine._rag_enabled(_make_ctx()) is True

    def test_rag_top_k_clamp(self, monkeypatch):
        monkeypatch.setattr(settings, "IR_RAG_AUTO_ENHANCE_K", 3)
        engine = PipelineEngine()
        assert engine._rag_top_k(_make_ctx(input_params={"rag_top_k": 5})) == 5
        assert engine._rag_top_k(_make_ctx(input_params={"rag_top_k": 0})) == 1    # 下限
        assert engine._rag_top_k(_make_ctx(input_params={"rag_top_k": 100})) == 10  # 上限
        assert engine._rag_top_k(_make_ctx(input_params={"rag_top_k": "abc"})) == 3  # 非法回退全局
        assert engine._rag_top_k(_make_ctx()) == 3

    def test_rag_top_k_global_clamp(self, monkeypatch):
        """全局 K=999（env 解析合法但超界）→ 夹取到 10。"""
        monkeypatch.setattr(settings, "IR_RAG_AUTO_ENHANCE_K", 999)
        engine = PipelineEngine()
        assert engine._rag_top_k(_make_ctx()) == 10


# ============================================================================
# 注入格式
# ============================================================================


class TestFormatBlock:
    def test_format_full(self, monkeypatch):
        """完整命中：header 用 settings.IR_RAG_INJECT_HEADER，序号 1..K，附注来源/维度/引用。"""
        custom_header = "[知识增强] CUSTOM 历史处置经验"
        monkeypatch.setattr(settings, "IR_RAG_INJECT_HEADER", custom_header)
        engine = PipelineEngine()
        block = engine._format_knowledge_block(_hits(2))
        assert block.startswith(custom_header)
        assert block.endswith("[/知识增强]")
        assert "1. 发现 powershell 拉起 rundll32 的无文件攻击链" in block
        assert "2. 外连 IP 命中 Tor 出口节点" in block
        assert "来源: ir_rules" in block
        assert "维度: process" in block
        assert "引用: rule_001" in block

    def test_format_empty_returns_empty(self):
        engine = PipelineEngine()
        assert engine._format_knowledge_block([]) == ""
        assert engine._format_knowledge_block([None, "str"]) == ""       # 非 dict 跳过
        assert engine._format_knowledge_block([{"no_text": 1}]) == ""    # 无文本跳过

    def test_format_evidence_text_fallback(self):
        """无 formatted_text 时回退 evidence_text。"""
        engine = PipelineEngine()
        hits = [{"evidence_text": "仅证据文本命中"}]
        block = engine._format_knowledge_block(hits)
        assert "1. 仅证据文本命中" in block
        assert "来源" not in block  # 无来源字段则省略附注


# ============================================================================
# 检索入参构造
# ============================================================================


class TestBuildAnalysisData:
    def test_summary_from_intent_and_category(self, monkeypatch):
        engine = PipelineEngine()
        monkeypatch.setattr(engine, "_build_rag_raw_data", lambda host_id: {"processes": [], "network_connections": [], "webshell_items": [], "memory_shell_items": []})
        ctx = _make_ctx(input_params={"prompt": "  分析攻击链  ", "rag_category": "c2"})
        data = engine._build_rag_analysis_data(ctx)
        assert data["summary"] == "分析攻击链"
        assert data["category"] == "c2"
        assert data["_raw_data"] == {"processes": [], "network_connections": [], "webshell_items": [], "memory_shell_items": []}

    def test_summary_from_stages_fallback(self, monkeypatch):
        """无节点意图 → 前置 stage 输出兜底（复用 _extract_keywords）。"""
        engine = PipelineEngine()
        monkeypatch.setattr(engine, "_build_rag_raw_data", lambda host_id: {})
        ctx = _make_ctx(
            input_params={},
            stages=[{"name": "process_analysis", "status": "completed", "output": "发现 powershell 异常"}],
        )
        data = engine._build_rag_analysis_data(ctx)
        assert data["summary"] == "发现 powershell 异常"

    def test_summary_default_fallback(self, monkeypatch):
        """无意图无 stage → 默认 '安全事件分析'。"""
        engine = PipelineEngine()
        monkeypatch.setattr(engine, "_build_rag_raw_data", lambda host_id: {})
        ctx = _make_ctx(input_params={})
        data = engine._build_rag_analysis_data(ctx)
        assert data["summary"] == "安全事件分析"

    def test_no_host_fail_safe(self, monkeypatch):
        """无 host_id → _build_rag_raw_data 不调用，_raw_data={}（fail-safe 降级）。"""
        engine = PipelineEngine()

        def _should_not_call(host_id):
            raise AssertionError("无 host_id 不应反查 raw_data")

        monkeypatch.setattr(engine, "_build_rag_raw_data", _should_not_call)
        ctx = _make_ctx(host_id=None)
        data = engine._build_rag_analysis_data(ctx)
        assert data["_raw_data"] == {}

    def test_build_rag_raw_data_processes(self, monkeypatch):
        """host_id 存在 → processes 复用 data_provider.get_process_events（process_name/name 归一）。"""
        import app.services.agents.data_provider as dp

        monkeypatch.setattr(
            dp,
            "get_process_events",
            lambda host_id, limit=50: [
                {"process_name": "powershell.exe", "command_line": "-enc"},
                {"name": "rundll32", "cmd": "x"},
            ],
        )
        engine = PipelineEngine()
        raw = engine._build_rag_raw_data(1)
        assert raw["processes"] == [
            {"name": "powershell.exe", "cmd": "-enc"},
            {"name": "rundll32", "cmd": "x"},
        ]
        assert raw["network_connections"] == []
        assert raw["webshell_items"] == []
        assert raw["memory_shell_items"] == []

    def test_build_rag_raw_data_network(self, monkeypatch):
        """network_connections 直查限额 SQL（mock get_connection）。"""
        import app.database as db

        class _FakeConn:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def execute(self, sql, params):
                return self

            def fetchall(self):
                return [{
                    "local_addr": "1.2.3.4", "local_port": 4444,
                    "remote_addr": "8.8.8.8", "remote_port": 53,
                    "protocol": "udp", "process_name": "svchost",
                }]

        monkeypatch.setattr(db, "get_connection", lambda: _FakeConn())
        engine = PipelineEngine()
        raw = engine._build_rag_raw_data(1)
        assert raw["network_connections"] == [{
            "local_addr": "1.2.3.4", "local_port": 4444,
            "remote_addr": "8.8.8.8", "remote_port": 53,
            "protocol": "udp", "process_name": "svchost",
        }]

    def test_build_rag_raw_data_data_provider_raises_fail_safe(self, monkeypatch):
        """data_provider 抛异常 → 进程维度留空，不抛（fail-safe）。"""
        import app.services.agents.data_provider as dp

        def _boom(host_id, limit=50):
            raise RuntimeError("db down")

        monkeypatch.setattr(dp, "get_process_events", _boom)
        engine = PipelineEngine()
        raw = engine._build_rag_raw_data(1)
        assert raw["processes"] == []


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-v"]))
