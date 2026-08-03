"""T05-1 集成验证：整管中 guard 阻断 → 下游 stage 不执行（B4 验收）。

设计依据：``node-impl/design.md`` A3.1（guard 阻断由 _run_single 反映为 stage failed，
下游节点（拓扑序在后续 batch）不会执行）+ B4（整管中 guard 阻断 → 下游 stage 不执行）。

**类级临时 SQLite**（test_pipeline_node_triage 同款）：一次建库 + seed preset，
多个用例共享，避免 conftest db_path 每用例 init 的 ~12s 开销。
"""
import asyncio
import sys
import uuid
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import settings  # noqa: E402
from app.services.agents.agent_definition import AgentDefinition  # noqa: E402
from app.services.agents.agent_registry import AgentRegistry  # noqa: E402
from app.services.agents.pipeline_engine import PipelineEngine  # noqa: E402

TEST_DB_PATH = str(BACKEND_DIR / "data" / f"test_node_impl_integration_{uuid.uuid4().hex[:8]}.db")

_ADMIN = {"id": 1, "username": "admin", "role": "admin"}


@pytest.fixture(scope="module")
def integration_db():
    """模块级临时 SQLite：建表 + seed preset agents（一次）。"""
    original = settings.DB_PATH
    settings.DB_PATH = TEST_DB_PATH
    Path(settings.DATA_DIR).mkdir(parents=True, exist_ok=True)
    from app.database import init_db
    init_db()
    from app.services.agents.preset_data import seed_preset_agents
    try:
        seed_preset_agents(AgentRegistry())
    except Exception:
        pass
    yield
    settings.DB_PATH = original
    import os
    for suffix in ("", "-wal", "-shm"):
        try:
            if os.path.exists(TEST_DB_PATH + suffix):
                os.remove(TEST_DB_PATH + suffix)
        except OSError:
            pass


def _register_custom(name: str, depends_on: list[str]) -> None:
    """注册一个自定义下游 agent（name 唯一，避免重复注册抛错）。"""
    reg = AgentRegistry()
    try:
        reg.register(AgentDefinition(
            name=name,
            display_name=name,
            description="qa 自定义下游节点",
            type="custom",
            depends_on=depends_on,
        ))
    except ValueError:
        pass  # 已存在


def _run(coro):
    return asyncio.run(coro)


class TestGuardFullPipelineBlocking:
    """整管路径：guard 阻断语义（B4）。"""

    @pytest.fixture(autouse=True)
    def _ensure_custom_agent(self, integration_db):
        _register_custom("qa_after_guard", depends_on=["guard"])

    def test_guard_block_prevents_downstream(self, integration_db):
        """guard block=true → guard stage failed 且下游 qa_after_guard 不执行。"""
        _register_custom("qa_after_guard", depends_on=["guard"])
        eng = PipelineEngine()
        run_id = f"qa_guard_block_{uuid.uuid4().hex[:6]}"
        ctx = {
            "event_id": "SE-1",
            "host_id": "H1",
            "user": _ADMIN,
            # run 级 ctx input_params 覆盖 guard preset 的 block=false → block=true
            "input_params": {"block": True, "reason": "qa 阻断验证"},
        }
        res = _run(eng.run(run_id, ["guard", "qa_after_guard"], "SE-1", ctx, _ADMIN,
                            use_cache=False, ensure_reporter=False))
        stage_map = {s["name"]: s["status"] for s in res["stages"]}
        # guard 自身 stage 必须 failed（blocked 反映为 failed）
        assert stage_map.get("guard") == "failed", f"guard stage 应 failed，实际 {stage_map}"
        # 下游（依赖 guard，拓扑序在后续 batch）不得执行
        assert stage_map.get("qa_after_guard") in (None, "skipped"), (
            f"guard 阻断后下游不应执行，实际 {stage_map}"
        )
        assert res["status"] in ("failed", "completed"), res["status"]

    def test_guard_pass_allows_downstream(self, integration_db):
        """guard block=false → 放行，下游正常执行。"""
        _register_custom("qa_after_guard", depends_on=["guard"])
        eng = PipelineEngine()
        run_id = f"qa_guard_pass_{uuid.uuid4().hex[:6]}"
        ctx = {
            "event_id": "SE-1",
            "host_id": "H1",
            "user": _ADMIN,
            "input_params": {"block": False},
        }
        res = _run(eng.run(run_id, ["guard", "qa_after_guard"], "SE-1", ctx, _ADMIN,
                            use_cache=False, ensure_reporter=False))
        stage_map = {s["name"]: s["status"] for s in res["stages"]}
        assert stage_map.get("guard") == "completed", f"guard 应放行，实际 {stage_map}"
        assert stage_map.get("qa_after_guard") == "completed", f"下游应执行，实际 {stage_map}"
