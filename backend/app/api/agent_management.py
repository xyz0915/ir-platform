"""智能体管理 Phase 2 — REST API 端点。"""

import datetime
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.models.agent_definition import AgentDefinitionModel, PipelinePresetModel
from app.models.agent_run import NodeRunRepository
from app.services.agents.agent_definition import AgentDefinition
from app.services.agents.agent_registry import AgentRegistry
from app.services.agents.cache_manager import cache_manager
from app.services.agents.execution_mode import build_agent_warning
from app.services.agents.hitl_manager import hitl_manager
from app.services.agents.pipeline_engine import pipeline_engine
from app.services.auth_service import get_current_user
from app.services.sse_manager import sse_manager

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Helper ──
def _ok(data=None, message="ok", warning=None):
    """标准成功响应格式（P2：可选顶层 warning，向后兼容）。

    Args:
        data: 响应数据。
        message: 成功消息。
        warning: 可选顶层 warning 文案；None/空串时不返回该字段，
            既有消费方只读 code/data/message 不受影响。
    """
    resp = {"code": 0, "data": data, "message": message}
    if warning:
        resp["warning"] = warning
    return resp


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
    """注册新 Agent。

    请求体为自由字典（非 Pydantic 模型），可包含以下字段：
      - 既有: name, display_name, type, description, data_sources(list[str]),
              depends_on(list[str]), prompt_template, config(dict),
              enabled(bool), hitl(bool)
      - 🔴 Fix A 新增: tools(list[str], 关联工具 tool_id 列表),
                        model_profile(str, 关联模型档案 profile_id)
    响应 data = AgentDefinition.to_dict()，会回显 tools / model_profile
    （旧库记录回读分别为 [] 与 ''）。
    """
    registry = AgentRegistry()
    try:
        agent_def = AgentDefinition.from_dict(data)
        result = registry.register(agent_def)
        warning = build_agent_warning(result.name, result.tools, result.model_profile)
        return _ok(data=result.to_dict(), warning=warning)
    except ValueError as e:
        _err(409, str(e))


@router.put("/api/agent-management/agents/{name}")
def update_agent(
    name: str,
    data: dict,
    current_user: Optional[dict] = Depends(get_current_user),
):
    """更新 Agent 配置。

    请求体为自由字典，字段同 create_agent（含 Fix A 新增的 tools / model_profile）。
    响应 data = AgentDefinition.to_dict()，回显全部字段（含 tools / model_profile）。
    """
    registry = AgentRegistry()
    try:
        result = registry.update(name, data)
        warning = build_agent_warning(result.name, result.tools, result.model_profile)
        return _ok(data=result.to_dict(), warning=warning)
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


# ══════════════════════════════════════════
# 2.1 单节点调试 / 分支模拟（Phase 3 / KC-1 / BRANCH-01）
# ══════════════════════════════════════════

def compute_branch_paths(node_name, branches, chosen_branch, connections):
    """BFS 计算所选分支的下游 active / pruned 节点与边（纯图计算，不查 DB）。

    Args:
        node_name: 分支节点名称。
        branches: [{label, target}] 分支列表。
        chosen_branch: 所选手分支 label（None → 取 branches[0]）。
        connections: 画布全部连线 [{sourceId, targetId}]。

    Returns:
        { node_name, chosen_branch, chosen_target,
          active_nodes, pruned_nodes, pruned_edges, downstream_active_count }
    """
    adj: dict = {}
    for c in (connections or []):
        s = c.get("sourceId") or c.get("source")
        t = c.get("targetId") or c.get("target")
        if s and t:
            adj.setdefault(s, []).append(t)

    def _bfs(start):
        seen = set()
        if not start:
            return seen
        q = [start]
        while q:
            cur = q.pop(0)
            if cur in seen:
                continue
            seen.add(cur)
            for nxt in adj.get(cur, []):
                if nxt not in seen:
                    q.append(nxt)
        return seen

    chosen_target = None
    options = []
    for b in (branches or []):
        label = b.get("label")
        target = b.get("target")
        options.append({"label": label, "target": target})
        if label == chosen_branch:
            chosen_target = target

    active = _bfs(chosen_target)

    pruned_targets = [
        b.get("target") for b in (branches or [])
        if b.get("label") != chosen_branch and b.get("target")
    ]
    pruned_nodes = set()
    for pt in pruned_targets:
        pruned_nodes |= _bfs(pt)
    pruned_nodes -= active

    pruned_edges = [
        {
            "sourceId": (c.get("sourceId") or c.get("source")),
            "targetId": (c.get("targetId") or c.get("target")),
        }
        for c in (connections or [])
        if (c.get("sourceId") or c.get("source")) in pruned_nodes
    ]

    return {
        "node_name": node_name,
        "chosen_branch": chosen_branch,
        "chosen_target": chosen_target,
        "active_nodes": sorted(active),
        "pruned_nodes": sorted(pruned_nodes),
        "pruned_edges": pruned_edges,
        "downstream_active_count": len(active),
    }


@router.post("/api/agent-management/pipeline/node/run")
async def run_node_endpoint(
    data: dict,
    current_user: Optional[dict] = Depends(get_current_user),
):
    """单节点独立执行（真实 / 模拟）。

    请求见 02-design.md §3.1；失败结构化返回（status=failed + error），
    **不抛 500**（execute_node 内部已捕获，这里仅兜底网络/序列化异常）。
    """
    node_type = data.get("node_type")
    if not node_type:
        _err(400, "node_type is required")
    node_name = data.get("node_name") or node_type
    input_params = data.get("input_params") or {}
    context_vars = data.get("context_vars") or {}
    mode = data.get("mode") or "real"
    if mode not in ("real", "simulate"):
        mode = "real"
    try:
        result = await pipeline_engine.execute_node(
            node_type=node_type,
            node_name=node_name,
            input_params=input_params,
            context_vars=context_vars,
            mode=mode,
            user=current_user or {},
        )
    except Exception as exc:
        logger.exception("run_node_endpoint failed: %s", exc)
        return _ok(data={
            "status": "failed",
            "node_type": node_type,
            "node_name": node_name,
            "mode": mode,
            "error": str(exc),
            "output_text": "",
            "confidence": 0.0,
            "evidence": [],
            "run_id": None,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        })
    return _ok(data=result)


@router.post("/api/agent-management/pipeline/node/simulate-branch")
def simulate_branch_endpoint(
    data: dict,
    current_user: Optional[dict] = Depends(get_current_user),
):
    """分支模拟：纯图计算返回 active/pruned 下游，不执行节点。"""
    node_name = data.get("node_name")
    branches = data.get("branches") or []
    chosen_branch = data.get("chosen_branch") or (
        branches[0].get("label") if branches else None
    )
    connections = data.get("connections") or []
    try:
        result = compute_branch_paths(node_name, branches, chosen_branch, connections)
    except Exception as exc:
        logger.exception("simulate_branch_endpoint failed: %s", exc)
        _err(400, str(exc))
    return _ok(data=result)


@router.get("/api/agent-management/pipeline/node/runs")
def get_node_runs_endpoint(
    node_name: Optional[str] = Query(None),
    mode: Optional[str] = Query(None),
    limit: int = Query(20),
    current_user: Optional[dict] = Depends(get_current_user),
):
    """查询单节点调试历史（debug-<uuid> 前缀识别）。"""
    try:
        items = NodeRunRepository.list_debug_runs_by_node(node_name, mode, limit)
    except Exception as exc:
        logger.exception("get_node_runs_endpoint failed: %s", exc)
        _err(500, str(exc))
    return _ok(data={"items": items, "total": len(items)})


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
    # P1-3.2: SSE 重连时回放历史事件（已完成 stages 的状态）
    history = run.sse_events if run.sse_events else None
    return StreamingResponse(
        sse_manager.subscribe(run_id, history=history),
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
    """保存管道为预置模板。

    请求体为自由字典，除 name / description / agents 外，支持可选元数据：
      - category: 分类（取证 / 分析 / 处置 / 其他），缺省 'other'
      - tags:     标签数组（list[str]），缺省 []
      - status:   发布状态（draft / published），缺省 'draft'（A2 发布语义；
                  发布按钮以 status='published' 创建，非法值回退 draft）
    author 自动取当前登录用户名（未登录则为空字符串）。
    """
    name = data.get("name", "")
    description = data.get("description", "")
    agents = data.get("agents", [])
    category = data.get("category", "other")
    tags = data.get("tags", [])
    status = data.get("status", "draft")
    if status not in ("draft", "published"):
        status = "draft"
    author = ""
    if current_user:
        author = current_user.get("username", "") if isinstance(current_user, dict) else str(current_user)
    if not name or not agents:
        _err(400, "name and agents are required")
    # 唯一性预检：name 在 DB 层有 UNIQUE 约束，直接尝试 INSERT 会触发
    # sqlite3.IntegrityError 上浮为 500。这里提前查一次并返回友好 409。
    if PipelinePresetModel.get_by_name(name):
        _err(409, f"预设名称 '{name}' 已存在，请换一个名字")
    try:
        preset = PipelinePresetModel.create({
            "name": name,
            "description": description,
            "agents": agents,
            "author": author,
            "category": category,
            "tags": tags,
            "status": status,
        })
    except Exception as exc:
        # 兜底：极小概率下的竞态（预检通过但并发写入仍冲突），仍给出 409 而非 500
        msg = str(exc)
        if "UNIQUE constraint failed" in msg:
            _err(409, f"预设名称 '{name}' 已存在")
        raise
    return _ok(data=preset)


@router.post("/api/agent-management/pipeline/presets/{preset_id}/use")
def use_preset(
    preset_id: int,
    current_user: Optional[dict] = Depends(get_current_user),
):
    """记录一次预设加载使用（usage_count +1 并刷新 last_used_at）。

    前端在选择器确认加载某预设后调用，用于统计预设热度。
    """
    success = PipelinePresetModel.increment_usage(preset_id)
    if not success:
        _err(404, f"Preset '{preset_id}' not found")
    return _ok(message="recorded")


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
