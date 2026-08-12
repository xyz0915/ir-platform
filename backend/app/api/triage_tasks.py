"""动态取证任务 API（应急动态取证方案 Phase 2）.

端点：
- POST /api/hosts/{host_id}/triage-tasks          平台下发取证任务（用户鉴权）
- GET  /api/hosts/{host_id}/triage-tasks          平台查询任务列表（用户鉴权）
- GET  /api/hosts/{host_id}/triage-tasks/pending  daemon 轮询待执行任务（agent token 鉴权 + host 绑定）
- POST /api/hosts/{host_id}/triage-tasks/{task_id}/result  daemon 回传取证结果（agent token 鉴权）

命令通道：方案 A（轮询）。daemon 每 ~30s 拉取 pending 任务，定向采集后回传。
取证结果落库到 file_hashes / network_connections / process_events，标记 source='triage'（追加，不删除快照存量）。
"""

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.database import get_connection
from app.models.triage_task import TriageTask
from app.models.process_event import ProcessEvent
from app.services.agent_auth import assert_host_binding, get_current_agent
from app.services.auth_service import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter()

ALLOWED_SCOPE = {"file_hashes", "network", "process_subtree"}
DEFAULT_SCOPE = ["file_hashes", "network", "process_subtree"]


class TriageTaskCreate(BaseModel):
    scope: list | None = None


class TriageResult(BaseModel):
    file_hashes: list = []
    network_connections: list = []
    process_events: list = []
    summary: dict | None = None
    error: str | None = None


@router.post("/hosts/{host_id}/triage-tasks")
def create_triage_task(host_id: int, body: TriageTaskCreate,
                       current_user: dict = Depends(get_current_user)):
    """平台侧：下发动态取证任务."""
    # D-1 修复：校验主机存在，不存在返回 404（避免外键约束异常暴露 500）
    with get_connection() as conn:
        host_exists = conn.execute(
            "SELECT 1 FROM hosts WHERE id=?", [host_id]
        ).fetchone()
    if not host_exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="主机不存在"
        )
    scope = [s for s in (body.scope or DEFAULT_SCOPE) if s in ALLOWED_SCOPE]
    if not scope:
        scope = DEFAULT_SCOPE
    task_id = TriageTask.create(host_id, scope)
    logger.info("下发动态取证任务 host=%d task=%d scope=%s", host_id, task_id, scope)
    return {"code": 0, "data": {"task_id": task_id, "scope": scope}, "message": "success"}


@router.get("/hosts/{host_id}/triage-tasks")
def list_triage_tasks(host_id: int, current_user: dict = Depends(get_current_user)):
    """平台侧：查询主机的取证任务列表."""
    return {"code": 0, "data": TriageTask.list_by_host(host_id), "message": "success"}


@router.get("/hosts/{host_id}/triage-tasks/pending")
def poll_pending_task(host_id: int, agent: dict = Depends(get_current_agent)):
    """daemon 侧：轮询待执行任务（置 running 后返回）."""
    assert_host_binding(agent, host_id)
    task = TriageTask.get_pending(host_id)
    if not task:
        return {"code": 0, "data": None, "message": "no pending task"}
    return {"code": 0, "data": task, "message": "success"}


@router.post("/hosts/{host_id}/triage-tasks/{task_id}/result")
def report_triage_result(host_id: int, task_id: int, body: TriageResult,
                         agent: dict = Depends(get_current_agent)):
    """daemon 侧：回传取证结果，落库到专用表（source='triage'）。

    - D-2 幂等保护：仅 running 状态任务允许回传（done/failed/pending 均拒绝，防重复写库）；
    - D-3 输入防御：process_events 非 dict 元素直接过滤；写库异常时兜底标记 failed，
      保证任务状态闭合（不再永久卡 running）。
    """
    assert_host_binding(agent, host_id)

    # D-2：校验任务存在且处于 running（daemon 经 get_pending 后才会持有 running 任务）
    with get_connection() as conn:
        row = conn.execute(
            "SELECT status FROM triage_tasks WHERE id=? AND host_id=?",
            [task_id, host_id],
        ).fetchone()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="取证任务不存在"
        )
    if row["status"] != "running":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"任务状态为 {row['status']}，仅 running 任务可回传结果",
        )

    written = {"file_hashes": 0, "network_connections": 0, "process_events": 0}
    try:
        if body.file_hashes:
            written["file_hashes"] = _insert_file_hashes(host_id, body.file_hashes)
        if body.network_connections:
            written["network_connections"] = _insert_network(host_id, body.network_connections)
        if body.process_events:
            # D-3 修复：过滤非 dict 元素，避免 {**e, ...} 抛 TypeError → 500
            events = [
                {**e, "source": "triage"}
                for e in body.process_events
                if isinstance(e, dict)
            ]
            written["process_events"] = ProcessEvent.batch_create(host_id, events)
    except Exception as exc:
        # D-3 兜底：写库异常时仍闭合任务状态（标记 failed），避免永久卡 running
        logger.exception("动态取证结果落库失败 host=%d task=%d", host_id, task_id)
        TriageTask.complete(task_id, None, error=f"result 落库失败: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"取证结果落库失败: {exc}",
        )

    TriageTask.complete(task_id, body.summary or written, error=body.error)
    logger.info("动态取证结果回传 host=%d task=%d written=%s error=%s",
                host_id, task_id, written, body.error)
    return {"code": 0, "data": {"written": written}, "message": "success"}


# ── 内部：追加写入（不 DELETE 存量，避免污染快照取证） ──────────────────
def _insert_file_hashes(host_id: int, items: list) -> int:
    count = 0
    with get_connection() as conn:
        for it in items:
            conn.execute(
                """
                INSERT INTO file_hashes
                    (host_id, file_path, file_name, sha256, is_signed, signer,
                     file_size, product_name, product_version, collected_at, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'triage')
                """,
                (
                    host_id,
                    it.get("file_path"),
                    it.get("file_name"),
                    it.get("sha256"),
                    1 if it.get("is_signed") else 0,
                    it.get("signer"),
                    it.get("file_size"),
                    it.get("product_name"),
                    it.get("product_version"),
                    it.get("collected_at"),
                ),
            )
            count += 1
    return count


def _insert_network(host_id: int, items: list) -> int:
    count = 0
    with get_connection() as conn:
        for it in items:
            conn.execute(
                """
                INSERT INTO network_connections
                    (host_id, protocol, local_addr, local_port, remote_addr,
                     remote_port, state, pid, process_name, collected_at, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'triage')
                """,
                (
                    host_id,
                    it.get("protocol"),
                    it.get("local_addr") or it.get("local_address"),
                    it.get("local_port"),
                    it.get("remote_addr") or it.get("remote_address"),
                    it.get("remote_port"),
                    it.get("state"),
                    it.get("pid"),
                    it.get("process_name"),
                    it.get("collected_at"),
                ),
            )
            count += 1
    return count
