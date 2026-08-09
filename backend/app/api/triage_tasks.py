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

from fastapi import APIRouter, Depends
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
    """daemon 侧：回传取证结果，落库到专用表（source='triage'）。"""
    assert_host_binding(agent, host_id)
    written = {"file_hashes": 0, "network_connections": 0, "process_events": 0}

    if body.file_hashes:
        written["file_hashes"] = _insert_file_hashes(host_id, body.file_hashes)
    if body.network_connections:
        written["network_connections"] = _insert_network(host_id, body.network_connections)
    if body.process_events:
        # process_events 复用现有模型，标记 source='triage'
        events = [{**e, "source": "triage"} for e in body.process_events]
        written["process_events"] = ProcessEvent.batch_create(host_id, events)

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
