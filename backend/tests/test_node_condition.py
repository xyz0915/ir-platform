"""T05-3：condition 条件分支节点表达式求值单元测试。

设计依据：``node-impl/design.md`` A3.3 / A5.2（JSONPath 子集 + 比较运算符）+
B4 验收（``{dep:x}.field == val`` 求值正确；无命中 condition_met=false；非法表达式不抛）。

覆盖：
- 短路：首个 true 分支即 branch_taken（后续不再命中）；
- 运算符：== / != / > / < / >= / <= / contains / exists / regex；
- 引用：``{dep:name}.structured.field`` 点路径 + ``[n]`` 整数索引；
- 非法表达式 fail-safe（单条 error 不阻断、不抛异常）；
- conditions 空 → 未配置提示。

**零 DB 策略**：直接构造 ctx.stages，不触 DB（毫秒级执行）。
"""
import asyncio
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.agents.pipeline_engine import PipelineEngine  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


def _ctx_with_stage(name="root_cause", structured=None, output="stage output"):
    """构造含单个 completed stage 的 ctx。"""
    return {
        "host_id": "H1",
        "event_id": None,
        "stages": [{
            "name": name,
            "status": "completed",
            "output": {
                "output": output,
                "structured": structured if structured is not None else {"used_llm": True, "risk_score": 92, "tags": ["c2", "malware"], "detail": {"level": "high"}, "samples": [{"name": "a.dll"}, {"name": "b.exe"}]},
            },
        }],
        "input_params": {},
        "context_vars": {},
    }


class TestConditionEval:
    """_eval_condition_expr 表达式求值（A5.2）。"""

    def test_eq_true(self):
        eng = PipelineEngine()
        assert eng._eval_condition_expr("{dep:root_cause}.structured.used_llm == true", _ctx_with_stage()) is True

    def test_eq_false(self):
        eng = PipelineEngine()
        assert eng._eval_condition_expr("{dep:root_cause}.structured.used_llm == false", _ctx_with_stage()) is False

    def test_neq(self):
        eng = PipelineEngine()
        assert eng._eval_condition_expr("{dep:root_cause}.structured.detail.level != 'low'", _ctx_with_stage()) is True

    def test_gt_lt(self):
        eng = PipelineEngine()
        ctx = _ctx_with_stage()
        assert eng._eval_condition_expr("{dep:root_cause}.structured.risk_score > 90", ctx) is True
        assert eng._eval_condition_expr("{dep:root_cause}.structured.risk_score < 90", ctx) is False
        assert eng._eval_condition_expr("{dep:root_cause}.structured.risk_score >= 92", ctx) is True
        assert eng._eval_condition_expr("{dep:root_cause}.structured.risk_score <= 91", ctx) is False

    def test_contains_list(self):
        eng = PipelineEngine()
        assert eng._eval_condition_expr("{dep:root_cause}.structured.tags contains 'c2'", _ctx_with_stage()) is True
        assert eng._eval_condition_expr("{dep:root_cause}.structured.tags contains 'benign'", _ctx_with_stage()) is False

    def test_exists(self):
        eng = PipelineEngine()
        assert eng._eval_condition_expr("{dep:root_cause}.structured.used_llm exists", _ctx_with_stage()) is True
        assert eng._eval_condition_expr("{dep:root_cause}.structured.missing_field exists", _ctx_with_stage()) is False

    def test_regex(self):
        eng = PipelineEngine()
        assert eng._eval_condition_expr("{dep:root_cause}.structured.detail.level regex '^h'", _ctx_with_stage()) is True
        assert eng._eval_condition_expr("{dep:root_cause}.structured.detail.level regex '^z'", _ctx_with_stage()) is False

    def test_dot_path_and_index(self):
        eng = PipelineEngine()
        # 点路径 + 整数索引：{dep:x}.structured.samples[0].name == 'a.dll'
        assert eng._eval_condition_expr("{dep:root_cause}.structured.samples[0].name == 'a.dll'", _ctx_with_stage()) is True
        assert eng._eval_condition_expr("{dep:root_cause}.structured.samples[1].name == 'b.exe'", _ctx_with_stage()) is True

    def test_bare_true_literal(self):
        eng = PipelineEngine()
        assert eng._eval_condition_expr("true", _ctx_with_stage()) is True
        assert eng._eval_condition_expr("false", _ctx_with_stage()) is False

    def test_missing_dep_no_crash(self):
        """引用不存在的 stage → 求值 False 而非抛异常。"""
        eng = PipelineEngine()
        assert eng._eval_condition_expr("{dep:nonexistent}.structured.x == 1", _ctx_with_stage()) is False

    def test_jsonpath_get_helper(self):
        assert PipelineEngine._jsonpath_get({"a": {"b": [10, 20]}}, "a.b[1]") == 20
        assert PipelineEngine._jsonpath_get({"a": {"b": [10, 20]}}, "a.b[9]") is None
        assert PipelineEngine._jsonpath_get({"a": 1}, "a.b") is None
        assert PipelineEngine._jsonpath_get(None, "a") is None

    def test_read_dep_output_helper(self):
        eng = PipelineEngine()
        ctx = _ctx_with_stage()
        assert eng._read_dep_output(ctx, "{dep:root_cause}.structured.used_llm") is True


class TestConditionNode:
    """_run_condition 节点行为（A3.3）。"""

    def test_short_circuit_first_true_branch(self):
        """短路：首个为 true 的分支即 branch_taken，后续分支不覆盖。"""
        eng = PipelineEngine()
        ctx = _ctx_with_stage()
        res = _run(eng._run_condition(ctx, {"conditions": [
            {"label": "高危", "expr": "{dep:root_cause}.structured.risk_score > 90"},
            {"label": "默认", "expr": "true"},
        ]}, "real"))
        s = res["structured"]
        assert s["branch_taken"] == "高危"
        assert s["condition_met"] is True
        assert len(s["evaluations"]) == 2
        assert s["evaluations"][0]["result"] is True
        assert s["evaluations"][1]["result"] is True  # 仍逐条求值（记录），但 branch_taken 不更新

    def test_first_false_then_true(self):
        """首个 false、次个 true → branch_taken 取次个。"""
        eng = PipelineEngine()
        ctx = _ctx_with_stage()
        res = _run(eng._run_condition(ctx, {"conditions": [
            {"label": "误报", "expr": "{dep:root_cause}.structured.risk_score < 10"},
            {"label": "默认", "expr": "true"},
        ]}, "real"))
        s = res["structured"]
        assert s["branch_taken"] == "默认"
        assert s["condition_met"] is True

    def test_no_match_returns_false(self):
        """无命中 → branch_taken=None + condition_met=false。"""
        eng = PipelineEngine()
        ctx = _ctx_with_stage()
        res = _run(eng._run_condition(ctx, {"conditions": [
            {"label": "x", "expr": "{dep:root_cause}.structured.risk_score > 999"},
        ]}, "real"))
        s = res["structured"]
        assert s["branch_taken"] is None
        assert s["condition_met"] is False
        assert s["downstream_active"] == []

    def test_garbage_expr_fail_safe_false(self):
        """设计 A3.3：表达式非法 → 该条件 result=false + error 记录（不抛异常）。

        当前实现把无运算符的垃圾串按真值处理（'!!!' → bool('!!!')=True），
        与"非法表达式 result=false"的 fail-safe 语义冲突。按设计断言 result=False。
        """
        eng = PipelineEngine()
        ctx = _ctx_with_stage()
        res = _run(eng._run_condition(ctx, {"conditions": [
            {"label": "bad", "expr": "!!!"},
        ]}, "real"))
        ev = res["structured"]["evaluations"][0]
        assert ev["result"] is False, f"非法表达式应 result=False，实际 {ev['result']!r}（error={ev['error']!r}）"
        assert res["structured"]["branch_taken"] is None

    def test_single_bad_expr_does_not_block_node(self):
        """单条表达式异常只记 error，不阻断整节点；后续合法表达式仍求值。"""
        eng = PipelineEngine()
        ctx = _ctx_with_stage()
        res = _run(eng._run_condition(ctx, {"conditions": [
            {"label": "bad", "expr": "!!!"},
            {"label": "ok", "expr": "{dep:root_cause}.structured.used_llm == true"},
        ]}, "real"))
        s = res["structured"]
        assert len(s["evaluations"]) == 2
        assert s["evaluations"][0]["result"] is False
        assert s["evaluations"][1]["result"] is True
        assert s["branch_taken"] == "ok"
        assert s["condition_met"] is True

    def test_empty_conditions_prompt(self):
        """conditions 空 → 未配置提示输出，不抛异常。"""
        eng = PipelineEngine()
        res = _run(eng._run_condition(_ctx_with_stage(), {}, "real"))
        assert "未配置 conditions" in res["output"]
        assert res["structured"]["condition_met"] is False
        assert res["structured"]["branch_taken"] is None

    def test_condition_met_false_confidence(self):
        """未命中时 confidence=0.5（命中 1.0）。"""
        eng = PipelineEngine()
        res = _run(eng._run_condition(_ctx_with_stage(), {"conditions": [{"label": "x", "expr": "false"}]}, "real"))
        assert res["confidence"] == 0.5
        res2 = _run(eng._run_condition(_ctx_with_stage(), {"conditions": [{"label": "x", "expr": "true"}]}, "real"))
        assert res2["confidence"] == 1.0
