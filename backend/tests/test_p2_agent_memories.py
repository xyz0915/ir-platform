"""P2 测试：长期记忆模型 CRUD + 自动沉淀写入链路（T1/T2）.

依据：
- ``p2-design.md`` §2（数据模型）/ §3（写入链路）/ §8 验收 B、C；
- ``p2-dev.md`` §2.3（AgentMemory CRUD）/ §2.4（_memory_type_for / _extract_memory_content
  / _sediment_memory 与 _run_single 成功路径 + HITL 恢复路径接入）。

覆盖（T1 模型 CRUD，临时 sqlite）：
- create 返回 dict（含 id），字段完整（agent_name/memory_type/content/source_node/tags/
  created_by/created_at）；content 超 4000 截断；tags JSON 序列化/反序列化；
- get_by_id（int 与 dict 两种入参，_coerce_id 兼容）；delete（成功 / 不存在返回 False 不抛）；
- list 各维度筛选（event_id/host_id/agent_name/memory_type）+ 分页 offset/limit；
- search：content LIKE 命中、tags LIKE 命中、带过滤组合、q 空不崩；
- count 正确；表 + 5 索引存在（验收 B 第 1 条）。

覆盖（T2 自动沉淀，engine 实例 + 临时 sqlite）：
- 类型映射：root_cause→conclusion、llm/custom→conclusion、reporter/report→summary、
  responder/response→disposition、action→action、branch/triage/condition 等跳过；
- 空内容跳过；remember=False 跳过；remember=True 强制写（全局关也写）；
- 全局 IR_MEMORY_AUTO_WRITE=False 跳过；写入异常 fail-safe（mock create 抛异常不抛上层）；
- memory_tags 落库；content 截断；不写回 run.ctx / run.stages；
- 缓存命中不重复沉淀：静态审查确认（_run_single L405-417 缓存命中提前 return，
  早于 L596-600 沉淀调用）；execute_node 调试路径不经过 _run_single 亦不沉淀。

环境说明（Windows + Python3.14 已知问题）：conftest 的 function-scoped ``db_path``
在每个用例创建/删除一个临时 WAL 库文件，本机多文件快速增删会偶发进程级原生崩溃
（与 test_dag_validation 既有崩溃同源，非 P2 引入）。本文件改用 **module-scoped**
临时库（整个文件仅 1 次 init_db），每用例清空 ``agent_memories`` 表保持计数断言语义，
显著降低文件 churn，规避该环境崩溃。

约束：所有测试不依赖真实 LLM / chroma。
"""

import json
import os
import sys
import uuid
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import pytest

from app.config import settings
from app.models.agent_memory import AgentMemory
from app.services.agents.pipeline_engine import PipelineEngine, PipelineRun


# ----------------------------------------------------------------------------
# module-scoped 临时库：整个文件仅 1 次 init_db（规避 Windows+Py3.14 多库崩溃）
# ----------------------------------------------------------------------------


def _init_db_at(path: str) -> None:
    from app.config import settings as _s
    _s.DB_PATH = path
    Path(_s.DATA_DIR).mkdir(parents=True, exist_ok=True)
    from app.database import init_db
    init_db()
    from app.services.agents.agent_registry import AgentRegistry
    from app.services.agents.preset_data import seed_preset_agents
    try:
        seed_preset_agents(AgentRegistry())
    except Exception:
        pass


@pytest.fixture(scope="module")
def mem_db():
    """module-scoped 临时 SQLite（AgentMemory 表可用）+ 每用例清空记忆表。

    返回 str（DB 路径）。每用例执行前 ``DELETE FROM agent_memories``，
    保持「count==0 / total==N」断言语义，同时规避 function-scoped 多库崩溃。
    """
    from app.config import settings as _s
    original = _s.DB_PATH
    data_dir = _BACKEND / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    path = str(data_dir / f"test_p2_mem_{uuid.uuid4().hex[:8]}.db")
    _init_db_at(path)
    yield path
    _s.DB_PATH = original
    for suffix in ("", "-wal", "-shm"):
        try:
            if os.path.exists(path + suffix):
                os.remove(path + suffix)
        except OSError:
            pass


@pytest.fixture()
def _clear_memories(mem_db):
    """每用例清空 agent_memories，保证计数断言独立。"""
    from app.database import get_connection
    with get_connection() as conn:
        conn.execute("DELETE FROM agent_memories")
    return mem_db


def _engine() -> PipelineEngine:
    """构造 PipelineEngine（构造不触 DB，见 conftest engine fixture 注释）。"""
    return PipelineEngine()


# ============================================================================
# T1 模型 CRUD
# ============================================================================


class TestModelCreate:
    def test_create_returns_dict_with_full_fields(self, _clear_memories):
        row = AgentMemory.create(
            run_id="run-1", event_id="evt-1", host_id=3,
            agent_name="root_cause", memory_type="conclusion",
            content="根因：powershell 无文件攻击链", source_node="root_cause",
            tags=["powershell", "C2"], created_by="system",
        )
        assert isinstance(row, dict)
        assert row["id"] > 0
        assert row["run_id"] == "run-1"
        assert row["event_id"] == "evt-1"
        assert row["host_id"] == 3
        assert row["agent_name"] == "root_cause"
        assert row["memory_type"] == "conclusion"
        assert row["content"] == "根因：powershell 无文件攻击链"
        assert row["source_node"] == "root_cause"
        assert row["created_by"] == "system"
        assert row["created_at"]            # 非空

    def test_create_defaults(self, _clear_memories):
        """缺省值：agent_name=''、memory_type='summary'、tags='[]'、created_by='system'。"""
        row = AgentMemory.create(content="仅正文")
        assert row["agent_name"] == ""
        assert row["memory_type"] == "summary"
        assert json.loads(row["tags"]) == []
        assert row["created_by"] == "system"
        assert row["source_node"] == ""

    def test_create_truncates_content_over_4000(self, _clear_memories):
        long_content = "x" * 5000
        row = AgentMemory.create(content=long_content)
        assert len(row["content"]) == settings.IR_MEMORY_MAX_CONTENT == 4000

    def test_create_invalid_type_falls_back_summary(self, _clear_memories):
        """非法 memory_type → 回退 summary（fail-safe，验收 B 第 2 条）。"""
        row = AgentMemory.create(content="内容", memory_type="bad_type")
        assert row["memory_type"] == "summary"

    def test_tags_json_roundtrip(self, _clear_memories):
        """tags 以 JSON 数组字符串落库，可反序列化。"""
        row = AgentMemory.create(content="带标签", tags=["a", "b", "中文"])
        assert json.loads(row["tags"]) == ["a", "b", "中文"]
        # 兼容 JSON 字符串入参
        row2 = AgentMemory.create(content="带标签2", tags='["x","y"]')
        assert json.loads(row2["tags"]) == ["x", "y"]
        # 兼容标量入参
        row3 = AgentMemory.create(content="带标签3", tags="single")
        assert json.loads(row3["tags"]) == ["single"]


class TestModelGetDelete:
    def test_get_by_id_int(self, _clear_memories):
        row = AgentMemory.create(content="查询目标")
        got = AgentMemory.get_by_id(row["id"])
        assert got == row

    def test_get_by_id_dict_input(self, _clear_memories):
        """_coerce_id 兼容 create 返回的行 dict。"""
        row = AgentMemory.create(content="查询目标2")
        got = AgentMemory.get_by_id(row)
        assert got["id"] == row["id"]

    def test_get_by_id_missing_returns_none(self, _clear_memories):
        assert AgentMemory.get_by_id(999999) is None
        assert AgentMemory.get_by_id(None) is None

    def test_delete_success(self, _clear_memories):
        row = AgentMemory.create(content="待删除")
        assert AgentMemory.delete(row["id"]) is True
        assert AgentMemory.get_by_id(row["id"]) is None

    def test_delete_dict_input(self, _clear_memories):
        row = AgentMemory.create(content="待删除2")
        assert AgentMemory.delete(row) is True

    def test_delete_missing_returns_false_no_raise(self, _clear_memories):
        assert AgentMemory.delete(999999) is False
        assert AgentMemory.delete(None) is False


class TestModelList:
    @pytest.fixture(autouse=True)
    def _seed(self, _clear_memories):
        self.m1 = AgentMemory.create(
            run_id="r1", event_id="evt-a", host_id=1, agent_name="root_cause",
            memory_type="conclusion", content="事件A 根因结论", source_node="root_cause",
            tags=["powershell"],
        )
        self.m2 = AgentMemory.create(
            run_id="r2", event_id="evt-a", host_id=1, agent_name="responder",
            memory_type="disposition", content="事件A 处置记录", source_node="response",
            tags=["隔离"],
        )
        self.m3 = AgentMemory.create(
            run_id="r3", event_id="evt-b", host_id=2, agent_name="reporter",
            memory_type="summary", content="事件B 报告摘要", source_node="report",
            tags=[],
        )

    def test_list_all_sorted_desc(self, _clear_memories):
        res = AgentMemory.list()
        assert res["total"] == 3
        ids = [it["id"] for it in res["items"]]
        assert ids == sorted(ids, reverse=True)          # created_at DESC, id DESC

    def test_list_filter_event_id(self, _clear_memories):
        res = AgentMemory.list(event_id="evt-a")
        assert res["total"] == 2
        assert {it["event_id"] for it in res["items"]} == {"evt-a"}

    def test_list_filter_host_id(self, _clear_memories):
        res = AgentMemory.list(host_id=2)
        assert res["total"] == 1
        assert res["items"][0]["id"] == self.m3["id"]

    def test_list_filter_agent_name(self, _clear_memories):
        res = AgentMemory.list(agent_name="responder")
        assert res["total"] == 1
        assert res["items"][0]["id"] == self.m2["id"]

    def test_list_filter_memory_type(self, _clear_memories):
        res = AgentMemory.list(memory_type="conclusion")
        assert res["total"] == 1
        assert res["items"][0]["memory_type"] == "conclusion"

    def test_list_filter_combined(self, _clear_memories):
        res = AgentMemory.list(event_id="evt-a", host_id=1)
        assert res["total"] == 2

    def test_list_pagination(self, _clear_memories):
        res = AgentMemory.list(page=1, page_size=2)
        assert res["total"] == 3
        assert len(res["items"]) == 2
        assert res["page"] == 1
        assert res["page_size"] == 2
        res2 = AgentMemory.list(page=2, page_size=2)
        assert len(res2["items"]) == 1

    def test_list_q_keyword(self, _clear_memories):
        res = AgentMemory.list(q="根因")
        assert res["total"] == 1
        assert res["items"][0]["id"] == self.m1["id"]


class TestModelSearch:
    @pytest.fixture(autouse=True)
    def _seed(self, _clear_memories):
        self.m1 = AgentMemory.create(
            event_id="evt-a", host_id=1, agent_name="root_cause",
            memory_type="conclusion", content="攻击者通过 powershell 拉起 rundll32",
            source_node="root_cause", tags=["powershell", "C2"],
        )
        self.m2 = AgentMemory.create(
            event_id="evt-a", host_id=1, agent_name="responder",
            memory_type="disposition", content="已隔离主机", source_node="response",
            tags=["隔离"],
        )
        self.m3 = AgentMemory.create(
            event_id="evt-b", host_id=2, agent_name="reporter",
            memory_type="summary", content="报告摘要", source_node="report",
            tags=["分析"],
        )

    def test_search_content_like_hit(self, _clear_memories):
        hits = AgentMemory.search(q="powershell")
        assert len(hits) == 1
        assert hits[0]["id"] == self.m1["id"]

    def test_search_tags_like_hit(self, _clear_memories):
        hits = AgentMemory.search(q="C2")
        assert len(hits) == 1
        assert hits[0]["id"] == self.m1["id"]

    def test_search_combined_filter(self, _clear_memories):
        hits = AgentMemory.search(q="隔离", host_id=1, event_id="evt-a")
        assert len(hits) == 1
        assert hits[0]["id"] == self.m2["id"]
        # 过滤不匹配 → 无命中
        hits2 = AgentMemory.search(q="隔离", host_id=2)
        assert hits2 == []

    def test_search_empty_q_no_crash(self, _clear_memories):
        """q 为空/空白 → 不按关键词过滤，仅按维度取最近。"""
        hits = AgentMemory.search(q="")
        assert len(hits) == 3
        hits2 = AgentMemory.search(q="   ")
        assert len(hits2) == 3
        # 维度过滤仍然生效
        hits3 = AgentMemory.search(q="", host_id=1)
        assert len(hits3) == 2

    def test_search_limit(self, _clear_memories):
        hits = AgentMemory.search(q="", limit=2)
        assert len(hits) == 2

    def test_search_no_match_empty_list(self, _clear_memories):
        assert AgentMemory.search(q="不存在关键词") == []


class TestModelCount:
    def test_count(self, _clear_memories):
        assert AgentMemory.count() == 0
        AgentMemory.create(content="a", agent_name="root_cause")
        AgentMemory.create(content="b", agent_name="responder", memory_type="disposition")
        assert AgentMemory.count() == 2
        assert AgentMemory.count(memory_type="disposition") == 1
        assert AgentMemory.count(agent_name="nobody") == 0


class TestSchema:
    def test_table_and_indexes_exist(self, _clear_memories):
        """验收 B 第 1 条：agent_memories 表 + 5 索引在全新库自动创建。"""
        from app.database import get_connection

        with get_connection() as conn:
            tables = {
                r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='agent_memories'"
                ).fetchall()
            }
            indexes = {
                r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_agent_memories_%'"
                ).fetchall()
            }
        assert "agent_memories" in tables
        assert {
            "idx_agent_memories_event", "idx_agent_memories_host", "idx_agent_memories_type",
            "idx_agent_memories_agent", "idx_agent_memories_created",
        } <= indexes


# ============================================================================
# T2 自动沉淀写入链路（_sediment_memory）
# ============================================================================


def _make_run(event_id="evt-1", host_id=3, input_params=None, run_id="run-1"):
    """构造最小 PipelineRun（_sediment_memory 只依赖 run_id/event_id/ctx）。"""
    ctx = {"host_id": host_id, "input_params": input_params or {}}
    return PipelineRun(run_id=run_id, agent_names=["root_cause"], event_id=event_id, ctx=ctx)


def _all_memories():
    return AgentMemory.list(page=1, page_size=200)["items"]


class TestSedimentTypeMapping:
    def test_root_cause_to_conclusion(self, _clear_memories):
        engine = _engine()
        run = _make_run()
        engine._sediment_memory(run, "root_cause", {"structured": {"root_cause": "根因文本", "summary": "摘要"}, "output": "out"})
        items = _all_memories()
        assert len(items) == 1
        it = items[0]
        assert it["memory_type"] == "conclusion"
        assert it["content"] == "根因文本"        # root_cause 优先级最高
        assert it["source_node"] == "root_cause"
        assert it["agent_name"] == "root_cause"
        assert it["created_by"] == "system"
        assert it["event_id"] == "evt-1"
        assert it["host_id"] == 3
        assert it["run_id"] == "run-1"

    def test_llm_to_conclusion(self, _clear_memories):
        engine = _engine()
        engine._sediment_memory(_make_run(), "llm", {"structured": {"summary": "LLM 摘要"}, "output": "out"})
        items = _all_memories()
        assert items[0]["memory_type"] == "conclusion"
        assert items[0]["content"] == "LLM 摘要"
        assert items[0]["source_node"] == "llm"

    def test_custom_agent_to_conclusion(self, _clear_memories):
        """未命中映射且不在跳过集合的名称 → 自定义 agent → conclusion。"""
        engine = _engine()
        engine._sediment_memory(_make_run(), "custom_analyzer", {"output": "自定义结论"})
        items = _all_memories()
        assert items[0]["memory_type"] == "conclusion"
        assert items[0]["content"] == "自定义结论"
        assert items[0]["source_node"] == "custom_analyzer"

    def test_reporter_to_summary(self, _clear_memories):
        engine = _engine()
        engine._sediment_memory(_make_run(), "reporter", {"structured": {"summary": "报告摘要"}, "output": "out"})
        items = _all_memories()
        assert items[0]["memory_type"] == "summary"
        assert items[0]["content"] == "报告摘要"
        assert items[0]["source_node"] == "report"

    def test_report_to_summary(self, _clear_memories):
        engine = _engine()
        engine._sediment_memory(_make_run(), "report", {"output": "报告输出"})
        items = _all_memories()
        assert items[0]["memory_type"] == "summary"
        assert items[0]["source_node"] == "report"

    def test_responder_to_disposition(self, _clear_memories):
        engine = _engine()
        engine._sediment_memory(_make_run(), "responder", {"output": "已隔离主机并阻断外联"})
        items = _all_memories()
        assert items[0]["memory_type"] == "disposition"
        assert items[0]["content"] == "已隔离主机并阻断外联"
        assert items[0]["source_node"] == "response"

    def test_response_to_disposition(self, _clear_memories):
        engine = _engine()
        engine._sediment_memory(_make_run(), "response", {"output": "处置说明"})
        items = _all_memories()
        assert items[0]["memory_type"] == "disposition"

    def test_action_to_action(self, _clear_memories):
        engine = _engine()
        engine._sediment_memory(
            _make_run(), "action",
            {"structured": {"summary": "动作摘要"}, "action": "isolate", "target": {"host_id": 3}, "output": "done"},
        )
        items = _all_memories()
        assert items[0]["memory_type"] == "action"
        assert items[0]["content"] == "动作摘要"     # structured.summary 优先

    def test_action_fallback_action_target(self, _clear_memories):
        """action 无 structured.summary → 动作/目标兜底。"""
        engine = _engine()
        engine._sediment_memory(
            _make_run(), "action",
            {"action": "isolate", "target": {"host_id": 3}, "output": "done"},
        )
        items = _all_memories()
        assert items[0]["memory_type"] == "action"
        assert "动作: isolate" in items[0]["content"]

    def test_skip_nodes_no_write(self, _clear_memories):
        """branch/triage/condition 等 → 不沉淀（验收 C 第 1 条）。"""
        engine = _engine()
        for name in ("triage", "branch", "condition", "parallel", "data_process", "output", "guard", "hitl"):
            engine._sediment_memory(_make_run(run_id=f"run-{name}"), name, {"output": "不应写入"})
        assert AgentMemory.count() == 0


class TestSedimentSwitches:
    def test_empty_content_skip(self, _clear_memories):
        engine = _engine()
        engine._sediment_memory(_make_run(), "root_cause", {})
        engine._sediment_memory(_make_run(), "root_cause", {"structured": {}, "output": ""})
        assert AgentMemory.count() == 0

    def test_remember_false_skip(self, _clear_memories):
        engine = _engine()
        run = _make_run(input_params={"remember": False})
        engine._sediment_memory(run, "root_cause", {"structured": {"root_cause": "有内容"}})
        assert AgentMemory.count() == 0

    def test_remember_true_force_write_global_off(self, _clear_memories, monkeypatch):
        """全局关 + 节点 remember=True → 强制写（skip 节点也写，memory_type 缺省 summary）。"""
        monkeypatch.setattr(settings, "IR_MEMORY_AUTO_WRITE", False)
        engine = _engine()
        run = _make_run(input_params={"remember": True})
        engine._sediment_memory(run, "triage", {"output": "强制沉淀内容"})
        items = _all_memories()
        assert len(items) == 1
        assert items[0]["memory_type"] == "summary"
        assert items[0]["source_node"] == "triage"

    def test_global_off_skip(self, _clear_memories, monkeypatch):
        monkeypatch.setattr(settings, "IR_MEMORY_AUTO_WRITE", False)
        engine = _engine()
        engine._sediment_memory(_make_run(), "root_cause", {"structured": {"root_cause": "内容"}})
        assert AgentMemory.count() == 0

    def test_global_on_default_writes(self, _clear_memories):
        """默认 IR_MEMORY_AUTO_WRITE=True → 自动写。"""
        assert settings.IR_MEMORY_AUTO_WRITE is True
        engine = _engine()
        engine._sediment_memory(_make_run(), "root_cause", {"structured": {"root_cause": "内容"}})
        assert AgentMemory.count() == 1


class TestSedimentFailSafe:
    def test_create_raise_does_not_propagate(self, _clear_memories, monkeypatch):
        """mock AgentMemory.create 抛异常 → _sediment_memory 不抛、不落库。"""
        def _boom(*a, **k):
            raise RuntimeError("db down")

        monkeypatch.setattr(AgentMemory, "create", staticmethod(_boom))
        engine = _engine()
        engine._sediment_memory(_make_run(), "root_cause", {"structured": {"root_cause": "内容"}})  # 不抛
        assert AgentMemory.count() == 0

    def test_no_write_back_to_ctx_stages(self, _clear_memories):
        """沉淀不写回 run.ctx / run.stages（无跨节点污染，验收 C 第 4 条）。"""
        engine = _engine()
        run = _make_run()
        before_ctx = dict(run.ctx)
        before_stages = list(run.stages)
        engine._sediment_memory(run, "root_cause", {"structured": {"root_cause": "内容"}})
        assert run.ctx == before_ctx
        assert run.stages == before_stages

    def test_content_truncated_by_engine(self, _clear_memories, monkeypatch):
        monkeypatch.setattr(settings, "IR_MEMORY_MAX_CONTENT", 20)
        engine = _engine()
        engine._sediment_memory(_make_run(), "root_cause", {"structured": {"root_cause": "长" * 100}})
        items = _all_memories()
        assert len(items[0]["content"]) == 20

    def test_memory_tags_persisted(self, _clear_memories):
        engine = _engine()
        run = _make_run(input_params={"memory_tags": ["powershell", "C2"]})
        engine._sediment_memory(run, "root_cause", {"structured": {"root_cause": "带标签内容"}})
        items = _all_memories()
        assert json.loads(items[0]["tags"]) == ["powershell", "C2"]


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-v"]))
