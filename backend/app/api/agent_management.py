"""智能体管理 Phase 2 — REST API 端点。"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.models.agent_definition import AgentDefinitionModel, PipelinePresetModel
from app.services.agents.agent_definition import AgentDefinition
from app.services.agents.agent_registry import AgentRegistry
from app.services.agents.cache_manager import cache_manager
from app.services.agents.hitl_manager import hitl_manager
from app.services.agents.pipeline_engine import pipeline_engine
from app.services.auth_service import get_current_user
from app.services.sse_manager import sse_manager

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Helper ──
def _ok(data=None, message="ok"):
    """标准成功响应格式。"""
    return {"code": 0, "data": data, "message": message}


def _err(code: int, detail: str):
    raise HTTPException(status_code=code, detail=detail)


# ════════════════════════════════════════════
# 1. Agent CRUD
# ════════════════════════════════════════════

@router.get("/api/agent-management/agents")
def list_agents(
    enabled_only: bool = Query(True),
    current_user: Optional[dict] = Depends(get_current_user),
):
    """列出所有 Agent（可按启用状态筛选）。"""
    registry = AgentRegistry()
    agents = registry.list_agents(enabled_only=enabled_only)
    return _ok(data=[a.to_dict() for a in agents])


@router.post("/api/agent-management/agents", status_code=201)
def create_agent(
    data: dict,
    current_user: Optional[dict] = Depends(get_current_user),
):
    """注册新 Agent。"""
    registry = AgentRegistry()
    try:
        agent_def = AgentDefinition.from_dict(data)
        result = registry.register(agent_def)
        return _ok(data=result.to_dict())
    except ValueError as e:
        _err(409, str(e))


@router.put("/api/agent-management/agents/{name}")
def update_agent(
    name: str,
    data: dict,
    current_user: Optional[dict] = Depends(get_current_user),
):
    """更新 Agent 配置。"""
    registry = AgentRegistry()
    try:
        result = registry.update(name, data)
        return _ok(data=result.to_dict())
    except ValueError as e:
        _err(404, str(e))


@router.delete("/api/agent-management/agents/{name}")
def delete_agent(
    name: str,
    current_user: Optional[dict] = Depends(get_current_user),
):
    """注销 Agent。"""
    registry = AgentRegistry()
    try:
        registry.unregister(name)
        return _ok(message=f"Agent '{name}' deleted")
    except ValueError as e:
        _err(409, str(e))


@router.get("/api/agent-management/agents/deps")
def get_dependency_graph(
    agents: str = Query("", description="逗号分隔的 Agent 名称"),
    current_user: Optional[dict] = Depends(get_current_user),
):
    """查询依赖图。"""
    agent_names = [a.strip() for a in agents.split(",") if a.strip()]
    if not agent_names:
        return _ok(data={"graph": {}, "batches": []})
    registry = AgentRegistry()
    graph = registry.get_dependency_graph(agent_names)
    # 也用 PipelineEngine 计算拓扑排序
    batches = pipeline_engine._topological_sort(graph)
    return _ok(data={
        "graph": graph,
        "batches": batches,
    })


# ════════════════════════════════════════════
# 2. Pipeline 执行
# ════════════════════════════════════════════

@router.post("/api/agent-management/pipeline/validate")
def validate_pipeline(
    data: dict,
    current_user: Optional[dict] = Depends(get_current_user),
):
    """验证管道配置。"""
    agent_names = data.get("agents", [])
    if not agent_names:
        return _ok(data={"valid": False, "warnings": ["No agents specified"]})
    registry = AgentRegistry()
    warnings = registry.validate_pipeline(agent_names)
    return _ok(data={
        "valid": len(warnings) == 0,
        "warnings": warnings,
    })


@router.post("/api/agent-management/pipeline/run", status_code=202)
async def run_pipeline(
    data: dict,
    current_user: Optional[dict] = Depends(get_current_user),
):
    """执行管道。返回 run_id，前端可通过 SSE 监听进度。"""
    event_id = data.get("event_id", "")
    agent_names = data.get("agents", [])
    use_cache = data.get("use_cache", True)

    if not event_id:
        _err(400, "event_id is required")
    if not agent_names:
        _err(400, "agents list is required")

    import uuid
    run_id = f"run_custom_{uuid.uuid4().hex[:12]}"
    ctx = {"event_id": event_id, "user": current_user or {}}

    # 异步执行（不阻塞 HTTP 响应）
    import asyncio

    async def _run():
        result = await pipeline_engine.run(
            run_id=run_id,
            agent_names=agent_names,
            event_id=event_id,
            ctx=ctx,
            user=current_user or {},
            use_cache=use_cache,
            on_sse=lambda evt, data: sse_manager.push(run_id, evt, data),
        )
        return result

    asyncio.ensure_future(_run())

    return _ok(data={
        "run_id": run_id,
        "status": "running",
    })


@router.get("/api/agent-management/pipeline/run/{run_id}")
def get_run_status(
    run_id: str,
    current_user: Optional[dict] = Depends(get_current_user),
):
    """查询管道运行状态。"""
    status = pipeline_engine.get_status(run_id)
    if not status:
        _err(404, f"Run '{run_id}' not found")
    return _ok(data=status)


@router.post("/api/agent-management/pipeline/run/{run_id}/cancel")
def cancel_run(
    run_id: str,
    current_user: Optional[dict] = Depends(get_current_user),
):
    """取消运行。"""
    success = pipeline_engine.cancel(run_id)
    if not success:
        _err(400, f"Cannot cancel run '{run_id}' (not running or already finished)")
    return _ok(message=f"Run '{run_id}' cancelled")


@router.post("/api/agent-management/pipeline/run/{run_id}/resume")
async def resume_run(
    run_id: str,
    data: dict,
    current_user: Optional[dict] = Depends(get_current_user),
):
    """恢复 HITL 暂停的管道。"""
    approved = data.get("approved", False)
    comment = data.get("comment", "")
    success = await pipeline_engine.resume(run_id, approved, current_user or {})
    if not success:
        _err(400, f"Cannot resume run '{run_id}' (no pending HITL)")
    return _ok(data={"run_id": run_id, "resumed": True})


@router.get("/api/agent-management/pipeline/run/{run_id}/stream")
async def stream_run_status(
    run_id: str,
    current_user: Optional[dict] = Depends(get_current_user),
):
    """SSE 流 — 实时推送管道执行状态。"""
    run = pipeline_engine.get_run(run_id)
    if not run:
        _err(404, f"Run '{run_id}' not found")
    return StreamingResponse(
        sse_manager.subscribe(run_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ════════════════════════════════════════════
# 3. 预置模板
# ════════════════════════════════════════════

@router.get("/api/agent-management/pipeline/presets")
def list_presets(
    current_user: Optional[dict] = Depends(get_current_user),
):
    """列出预置管道模板。"""
    presets = PipelinePresetModel.list()
    return _ok(data=presets)


@router.post("/api/agent-management/pipeline/presets", status_code=201)
def create_preset(
    data: dict,
    current_user: Optional[dict] = Depends(get_current_user),
):
    """保存管道为预置模板。"""
    name = data.get("name", "")
    description = data.get("description", "")
    agents = data.get("agents", [])
    if not name or not agents:
        _err(400, "name and agents are required")
    preset = PipelinePresetModel.create({
        "name": name,
        "description": description,
        "agents": agents,
    })
    return _ok(data=preset)


@router.delete("/api/agent-management/pipeline/presets/{preset_id}")
def delete_preset(
    preset_id: int,
    current_user: Optional[dict] = Depends(get_current_user),
):
    """删除预置模板。"""
    success = PipelinePresetModel.delete(preset_id)
    if not success:
        _err(404, f"Preset '{preset_id}' not found")
    return _ok(message=f"Preset '{preset_id}' deleted")


# ════════════════════════════════════════════
# 4. 缓存管理
# ════════════════════════════════════════════

@router.get("/api/agent-management/cache/stats")
def get_cache_stats(
    current_user: Optional[dict] = Depends(get_current_user),
):
    """查看缓存统计。"""
    return _ok(data=cache_manager.stats())


@router.post("/api/agent-management/cache/invalidate")
def invalidate_cache(
    data: dict,
    current_user: Optional[dict] = Depends(get_current_user),
):
    """失效缓存。"""
    agent_name = data.get("agent_name")  # 可选：None = 全量失效
    count = cache_manager.invalidate(agent_name)
    return _ok(data={"invalidated": count})
