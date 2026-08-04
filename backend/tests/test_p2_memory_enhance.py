"""P2 测试：检索增强钩子（记忆引用，T3）.

依据：
- ``p2-design.md`` §4（检索链路）/ §8 验收 D；
- ``p2-dev.md`` §2.4（_memory_enabled / _memory_top_k / _build_memory_query /
  _format_memory_block / _enhance_with_memory / _call_llm_safe 接入）。

覆盖：
- 默认关（IR_MEMORY_AUTO_ENHANCE=False）：_enhance_with_memory 直接返回原 prompt 不检索
  （mock 断言 AgentMemory.search 未被调用）；_call_llm_safe 传 ctx 也不注入；
- 全局开 → 检索命中 → prompt 前置注入 [记忆增强] 块（Top-K 序号化 content + 附注）；
- 节点 memory_enhance=True opt-in（全局关）；memory_enhance=False opt-out 覆盖全局开；
- 空命中 → 原 prompt 不注入；search 抛异常/超时 → 原 prompt 不阻断（fail-safe）；
- memory_top_k 夹取 [1,10]（非法回退全局）；_build_memory_query 过滤传递正确
  （q 截断 200 / event_id / host_id / 兜底关键词 / 兜底"安全事件"）；
- _enhance_with_memory 调 AgentMemory.search(q, event_id, host_id, None, None, K)（验收 D 入参断言）；
- _call_llm_safe 内知识增强后记忆增强顺序（静态 + 运行双确认）。

约束：AgentMemory.search 全 mock；无真实 DB 依赖；用例相互独立（monkeypatch 自愈）。
"""

import asyncio
import sys
import time
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import pytest

from app.config import settings
from app.models.agent_memory import AgentMemory
from app.services import agent_llm as agent_llm_module


def _run(coro):
    """同步执行协程（每用例独立事件循环）。"""
    return asyncio.run(coro)


def _engine():
    """构造 PipelineEngine（构造不触 DB；本文件全部 mock AgentMemory.search，无需 DB）。"""
    from app.services.agents.pipeline_engine import PipelineEngine
    return PipelineEngine()


def _make_ctx(**overrides):
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


def _memories(n=2):
    return [
        {
            "id": 1,
            "memory_type": "conclusion",
            "content": "根因：攻击者通过 powershell 拉起 rundll32 无文件攻击链",
            "source_node": "root_cause",
            "event_id": "evt-1",
            "host_id": 1,
            "created_at": "2026-08-04 10:00:00",
            "agent_name": "root_cause",
        },
        {
            "id": 2,
            "memory_type": "disposition",
            "content": "已隔离主机并阻断外联 IP",
            "source_node": "action",
            "event_id": "evt-2",
            "host_id": 2,
            "created_at": "2026-08-04 09:00:00",
            "agent_name": "responder",
        },
    ][:n]


def _patch_search(monkeypatch, hits):
    """把 AgentMemory.search（静态方法）替换为返回 hits 的桩。"""
    monkeypatch.setattr(
        AgentMemory, "search",
        staticmethod(
            lambda q="", event_id=None, host_id=None, agent_name=None,
                   memory_type=None, limit=5: hits
        ),
    )


def _patch_fake_llm(monkeypatch, prompts_out):
    class _FakeLLM:
        def __init__(self, profile=None):
            self.profile = profile

        async def call(self, prompt, user=None, trace_id=None, **kwargs):
            prompts_out.append(prompt)
            return {"content": "llm-ok", "degraded": False, "usage": {}}

    monkeypatch.setattr(agent_llm_module, "AgentLLM", _FakeLLM)
    return _FakeLLM


# ============================================================================
# T3-1 默认关红线
# ============================================================================


class TestDefaultOffRedLine:
    def test_settings_default_off(self):
        """未设 env 时 settings.IR_MEMORY_AUTO_ENHANCE 默认 False（验收 A 第 1 条）。"""
        assert settings.IR_MEMORY_AUTO_ENHANCE is False

    def test_memory_enabled_default_off(self):
        assert _engine()._memory_enabled(_make_ctx()) is False

    def test_enhance_default_off_returns_original_no_search(self, monkeypatch):
        """默认关：_enhance_with_memory 直接返回原 prompt，且不触发检索（零开销）。"""
        def _should_not_be_called(*args, **kwargs):
            raise AssertionError("默认关不应触发 AgentMemory.search")

        monkeypatch.setattr(AgentMemory, "search", staticmethod(_should_not_be_called))
        out = _run(_engine()._enhance_with_memory(_make_ctx(), "原始 prompt"))
        assert out == "原始 prompt"

    def test_call_llm_safe_ctx_default_off_prompt_unchanged(self, monkeypatch):
        """传 ctx 但全局关（且节点未 opt-in）→ LLM 收到原 prompt，无 [记忆增强] 注入。"""
        llm_prompts = []
        _patch_fake_llm(monkeypatch, llm_prompts)
        ctx = _make_ctx(input_params={"prompt": "分析此事件"})
        res = _run(_engine()._call_llm_safe({"id": 1}, "分析此事件", {"id": 1}, ctx=ctx))
        assert res["used"] is True
        assert llm_prompts == ["分析此事件"]
        assert "[记忆增强]" not in llm_prompts[0]


# ============================================================================
# T3-2 钩子启用后行为
# ============================================================================


class TestEnhanceEnabled:
    def test_global_on_injects_top_k_block(self, monkeypatch):
        """全局开 + 命中 → 前置注入 [记忆增强] 块（Top-K 序号化 content）。"""
        monkeypatch.setattr(settings, "IR_MEMORY_AUTO_ENHANCE", True)
        _patch_search(monkeypatch, _memories(2))
        ctx = _make_ctx(input_params={"prompt": "分析攻击链"})
        out = _run(_engine()._enhance_with_memory(ctx, "原始 prompt"))

        assert out.startswith("[记忆增强]")
        assert out.endswith("原始 prompt")
        assert "\n\n原始 prompt" in out            # 前置注入：block + \n\n + 原 prompt
        assert "1. [conclusion] 根因：攻击者通过 powershell 拉起 rundll32 无文件攻击链" in out
        assert "2. [disposition] 已隔离主机并阻断外联 IP" in out
        assert "来源: root_cause" in out
        assert "[/记忆增强]" in out

    def test_search_call_args(self, monkeypatch):
        """验收 D：按 {q, event_id, host_id} 调 AgentMemory.search(q, event_id, host_id, None, None, K=3)。"""
        monkeypatch.setattr(settings, "IR_MEMORY_AUTO_ENHANCE", True)
        calls = []

        def _spy(q="", event_id=None, host_id=None, agent_name=None, memory_type=None, limit=5):
            calls.append((q, event_id, host_id, agent_name, memory_type, limit))
            return _memories(1)

        monkeypatch.setattr(AgentMemory, "search", staticmethod(_spy))
        ctx = _make_ctx(input_params={"prompt": "分析攻击链"})
        _run(_engine()._enhance_with_memory(ctx, "orig"))
        assert calls == [("分析攻击链", "evt-1", 1, None, None, 3)]

    def test_node_opt_in_global_off(self, monkeypatch):
        """全局关 + 节点 memory_enhance=True → opt-in 生效注入。"""
        monkeypatch.setattr(settings, "IR_MEMORY_AUTO_ENHANCE", False)
        _patch_search(monkeypatch, _memories(1))
        ctx = _make_ctx(input_params={"memory_enhance": True, "prompt": "分析"})
        out = _run(_engine()._enhance_with_memory(ctx, "orig"))
        assert out.startswith("[记忆增强]")
        assert out.endswith("orig")

    def test_node_opt_out_global_on(self, monkeypatch):
        """全局开 + 节点 memory_enhance=False → opt-out 覆盖，不注入。"""
        monkeypatch.setattr(settings, "IR_MEMORY_AUTO_ENHANCE", True)
        _patch_search(monkeypatch, _memories(1))
        ctx = _make_ctx(input_params={"memory_enhance": False, "prompt": "x"})
        out = _run(_engine()._enhance_with_memory(ctx, "orig"))
        assert out == "orig"

    def test_empty_hits_no_inject(self, monkeypatch):
        monkeypatch.setattr(settings, "IR_MEMORY_AUTO_ENHANCE", True)
        _patch_search(monkeypatch, [])
        out = _run(_engine()._enhance_with_memory(_make_ctx(), "orig"))
        assert out == "orig"

    def test_search_raises_no_block(self, monkeypatch):
        """search 抛异常 → 不注入、不抛，原 prompt 返回（fail-safe）。"""
        monkeypatch.setattr(settings, "IR_MEMORY_AUTO_ENHANCE", True)

        def _boom(*args, **kwargs):
            raise RuntimeError("db down")

        monkeypatch.setattr(AgentMemory, "search", staticmethod(_boom))
        out = _run(_engine()._enhance_with_memory(_make_ctx(), "orig"))
        assert out == "orig"

    def test_search_timeout_no_block(self, monkeypatch):
        """检索超时（短 timeout + 慢桩）→ 按未命中处理，不注入不抛。"""
        monkeypatch.setattr(settings, "IR_MEMORY_AUTO_ENHANCE", True)
        monkeypatch.setattr(settings, "IR_MEMORY_RETRIEVE_TIMEOUT", 0.05)

        def _slow(*args, **kwargs):
            time.sleep(0.3)
            return _memories(1)

        monkeypatch.setattr(AgentMemory, "search", staticmethod(_slow))
        out = _run(_engine()._enhance_with_memory(_make_ctx(), "orig"))
        assert out == "orig"


# ============================================================================
# T3-3 开关决策与 Top-K
# ============================================================================


class TestSwitchLogic:
    def test_memory_enabled_node_opt_in(self, monkeypatch):
        monkeypatch.setattr(settings, "IR_MEMORY_AUTO_ENHANCE", False)
        assert _engine()._memory_enabled(_make_ctx(input_params={"memory_enhance": True})) is True

    def test_memory_enabled_node_opt_out_overrides_global(self, monkeypatch):
        monkeypatch.setattr(settings, "IR_MEMORY_AUTO_ENHANCE", True)
        assert _engine()._memory_enabled(_make_ctx(input_params={"memory_enhance": False})) is False
        assert _engine()._memory_enabled(_make_ctx()) is True

    def test_memory_top_k_clamp(self, monkeypatch):
        monkeypatch.setattr(settings, "IR_MEMORY_ENHANCE_K", 3)
        assert _engine()._memory_top_k(_make_ctx(input_params={"memory_top_k": 5})) == 5
        assert _engine()._memory_top_k(_make_ctx(input_params={"memory_top_k": 0})) == 1    # 下限
        assert _engine()._memory_top_k(_make_ctx(input_params={"memory_top_k": 100})) == 10  # 上限
        assert _engine()._memory_top_k(_make_ctx(input_params={"memory_top_k": "abc"})) == 3  # 非法回退全局
        assert _engine()._memory_top_k(_make_ctx()) == 3

    def test_memory_top_k_global_clamp(self, monkeypatch):
        monkeypatch.setattr(settings, "IR_MEMORY_ENHANCE_K", 999)
        assert _engine()._memory_top_k(_make_ctx()) == 10


# ============================================================================
# T3-4 检索入参构造（_build_memory_query）
# ============================================================================


class TestBuildMemoryQuery:
    def test_q_from_prompt(self):
        ctx = _make_ctx(input_params={"prompt": "  分析攻击链  "})
        q = _engine()._build_memory_query(ctx)
        assert q == {"q": "分析攻击链", "event_id": "evt-1", "host_id": 1}

    def test_q_from_query_fallback(self):
        ctx = _make_ctx(input_params={"query": "查询处置记录"})
        q = _engine()._build_memory_query(ctx)
        assert q["q"] == "查询处置记录"

    def test_q_truncated_to_200(self):
        long_prompt = "x" * 300
        ctx = _make_ctx(input_params={"prompt": long_prompt})
        q = _engine()._build_memory_query(ctx)
        assert len(q["q"]) == 200

    def test_q_from_stages_fallback(self, monkeypatch):
        """无节点意图 → _extract_keywords 兜底。"""
        eng = _engine()
        monkeypatch.setattr(eng, "_extract_keywords", lambda ctx: "前置摘要")
        ctx = _make_ctx(input_params={})
        q = eng._build_memory_query(ctx)
        assert q["q"] == "前置摘要"

    def test_q_default_fallback(self, monkeypatch):
        """无意图无 stage → 默认 '安全事件'。"""
        eng = _engine()
        monkeypatch.setattr(eng, "_extract_keywords", lambda ctx: "")
        ctx = _make_ctx(input_params={})
        q = eng._build_memory_query(ctx)
        assert q["q"] == "安全事件"

    def test_event_host_pass_through(self):
        ctx = _make_ctx(event_id="evt-x", host_id=9)
        q = _engine()._build_memory_query(ctx)
        assert q["event_id"] == "evt-x"
        assert q["host_id"] == 9


# ============================================================================
# T3-5 注入格式（_format_memory_block）
# ============================================================================


class TestFormatMemoryBlock:
    def test_format_full(self, monkeypatch):
        custom_header = "[记忆增强] CUSTOM 历史记忆"
        monkeypatch.setattr(settings, "IR_MEMORY_INJECT_HEADER", custom_header)
        block = _engine()._format_memory_block(_memories(2))
        assert block.startswith(custom_header)
        assert block.endswith("[/记忆增强]")
        assert "1. [conclusion] 根因：攻击者通过 powershell 拉起 rundll32 无文件攻击链" in block
        assert "2. [disposition] 已隔离主机并阻断外联 IP" in block
        assert "来源: root_cause" in block
        assert "事件: evt-1" in block
        assert "主机: 1" in block
        assert "时间: 2026-08-04 10:00:00" in block

    def test_format_empty_returns_empty(self):
        assert _engine()._format_memory_block([]) == ""
        assert _engine()._format_memory_block([None, "str"]) == ""       # 非 dict 跳过
        assert _engine()._format_memory_block([{"no_text": 1}]) == ""    # 无文本跳过

    def test_format_omits_missing_notes(self):
        hits = [{"memory_type": "summary", "content": "仅正文"}]
        block = _engine()._format_memory_block(hits)
        assert "1. [summary] 仅正文" in block
        # 无附注字段则条目行不带括号（注：默认 header 自身含全角括号，只校验条目行）
        assert "仅正文（" not in block

    def test_format_content_truncated_300(self):
        hits = [{"memory_type": "summary", "content": "长" * 400, "source_node": "x"}]
        block = _engine()._format_memory_block(hits)
        # 300 字符正文 + 序号/类型/附注
        assert "长" * 300 in block
        assert "长" * 301 not in block


# ============================================================================
# T3-6 _call_llm_safe 顺序（先知识后记忆）
# ============================================================================


class TestCallLlmSafeOrder:
    def test_knowledge_then_memory_order(self, monkeypatch):
        """知识增强之后追加记忆增强（静态审查 + 运行双确认，验收 D 第 2 条）。"""
        order = []

        async def _fake_knowledge(ctx, prompt):
            order.append("knowledge")
            return prompt

        async def _fake_memory(ctx, prompt):
            order.append("memory")
            return prompt

        eng = _engine()
        monkeypatch.setattr(eng, "_enhance_with_knowledge", _fake_knowledge)
        monkeypatch.setattr(eng, "_enhance_with_memory", _fake_memory)
        _patch_fake_llm(monkeypatch, [])

        ctx = _make_ctx(input_params={"prompt": "分析"})
        res = _run(eng._call_llm_safe({"id": 1}, "分析", {"id": 1}, ctx=ctx))
        assert res["used"] is True
        assert order == ["knowledge", "memory"]

    def test_call_llm_safe_no_ctx_skips_both(self, monkeypatch):
        """存量调用不传 ctx → 两个增强钩子都不触发（P1/P2 红线，行为完全不变）。"""
        order = []

        async def _fake_knowledge(ctx, prompt):
            order.append("knowledge")
            return prompt

        async def _fake_memory(ctx, prompt):
            order.append("memory")
            return prompt

        eng = _engine()
        monkeypatch.setattr(eng, "_enhance_with_knowledge", _fake_knowledge)
        monkeypatch.setattr(eng, "_enhance_with_memory", _fake_memory)
        _patch_fake_llm(monkeypatch, [])

        res = _run(eng._call_llm_safe({"id": 1}, "原始 prompt", {"id": 1}))
        assert res["used"] is True
        assert order == []


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-v"]))
