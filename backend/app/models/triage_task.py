"""TriageTask 数据模型 — 动态取证任务（应急动态取证方案 Phase 2）.

平台下发取证任务给指定主机的常驻 daemon，daemon 按需定向采集后回传结果，
结果落库到对应专用表（file_hashes / network_connections / process_events），标记 source='triage'。
"""

import json
import logging

from app.database import get_connection

logger = logging.getLogger(__name__)


class TriageTask:
    """动态取证任务模型."""

    @staticmethod
    def create(host_id: int, scope: list) -> int:
        """创建取证任务（pending 状态）.

        Args:
            host_id: 主机 ID.
            scope: 取证项列表，元素来自 {"file_hashes","network","process_subtree"}.

        Returns:
            新任务 id.
        """
        with get_connection() as conn:
            cur = conn.execute(
                "INSERT INTO triage_tasks (host_id, scope, status) VALUES (?, ?, 'pending')",
                [host_id, json.dumps(scope)],
            )
            return int(cur.lastrowid)

    @staticmethod
    def get_pending(host_id: int) -> dict | None:
        """取主机最旧的一条 pending 任务并置为 running（daemon 轮询用）.

        先回收超时未回传的 running 任务（D-4），避免任务永久卡死。

        Returns:
            任务 dict（scope 已反序列化，status 为最新 'running'）；无 pending 返回 None.
        """
        # D-4 服务端兜底：先回收本机超时未回传的 running 任务
        TriageTask.recover_stale()
        with get_connection() as conn:
            row = conn.execute(
                "SELECT id FROM triage_tasks WHERE host_id=? AND status='pending' "
                "ORDER BY id LIMIT 1",
                [host_id],
            ).fetchone()
            if not row:
                return None
            conn.execute(
                "UPDATE triage_tasks SET status='running', started_at=datetime('now') WHERE id=?",
                [row["id"]],
            )
            # D-0 修复：重新查询返回最新状态（避免返回 UPDATE 前的旧 status）
            task = dict(
                conn.execute(
                    "SELECT * FROM triage_tasks WHERE id=?", [row["id"]]
                ).fetchone()
            )
            try:
                task["scope"] = json.loads(task["scope"]) if task["scope"] else []
            except (json.JSONDecodeError, TypeError):
                task["scope"] = []
            return task

    @staticmethod
    def recover_stale(timeout_minutes: int = 10) -> int:
        """回收超时未回传的 running 任务（D-4 服务端兜底）.

        daemon 拉取任务后若失联/崩溃/回传持续失败，任务会永久停留在 running。
        本方法将 started_at 距今超过 ``timeout_minutes`` 的 running 任务标记为 failed，
        并写入 error 说明，前端进度即会关闭"进行中"状态。

        Args:
            timeout_minutes: 超时阈值（分钟），默认 10.

        Returns:
            被回收的任务数.
        """
        with get_connection() as conn:
            cur = conn.execute(
                "UPDATE triage_tasks SET status='failed', "
                "error=?, finished_at=datetime('now') "
                "WHERE status='running' AND started_at IS NOT NULL "
                "AND started_at < datetime('now', ?)",
                [
                    "timeout: daemon 未在 %d 分钟内回传结果" % timeout_minutes,
                    "-%d minutes" % timeout_minutes,
                ],
            )
            return cur.rowcount

    @staticmethod
    def list_by_host(host_id: int) -> list:
        """列出主机的全部取证任务（按 id 倒序）."""
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM triage_tasks WHERE host_id=? ORDER BY id DESC",
                [host_id],
            ).fetchall()
            out = []
            for r in rows:
                d = dict(r)
                try:
                    d["scope"] = json.loads(d["scope"]) if d["scope"] else []
                except (json.JSONDecodeError, TypeError):
                    d["scope"] = []
                try:
                    d["summary"] = json.loads(d["summary"]) if d["summary"] else None
                except (json.JSONDecodeError, TypeError):
                    d["summary"] = None
                out.append(d)
            return out

    @staticmethod
    def complete(task_id: int, summary: dict | None = None, error: str | None = None) -> None:
        """标记任务完成/失败并写入汇总."""
        status_val = "failed" if error else "done"
        with get_connection() as conn:
            conn.execute(
                "UPDATE triage_tasks SET status=?, summary=?, error=?, finished_at=datetime('now') "
                "WHERE id=?",
                [
                    status_val,
                    json.dumps(summary, ensure_ascii=False) if summary else None,
                    error,
                    task_id,
                ],
            )
