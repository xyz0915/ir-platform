"""AI异步任务模型 — ai_tasks 表 CRUD 操作."""

import logging
from typing import Any, Optional

from app.database import get_connection
from app.shared.ai_constants import TaskStatus

logger = logging.getLogger(__name__)


class AiTask:
    """AI异步分析任务模型.

    管理AI分析任务的异步执行状态，支持进度跟踪和取消操作.
    """

    @staticmethod
    def create(
        host_id: int,
        profile_id: Optional[int] = None,
        masked_mode: int = 0,
    ) -> dict:
        """创建新的AI分析任务.

        Args:
            host_id: 主机ID.
            profile_id: 使用的AI配置Profile ID（None 则使用激活配置）.
            masked_mode: 是否启用脱敏（0=否, 1=是）.

        Returns:
            创建的任务字典.
        """
        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO ai_tasks
                (host_id, profile_id, status, progress, progress_message, masked_mode)
                VALUES (?, ?, ?, 0, '任务已提交，等待执行...', ?)
                """,
                (host_id, profile_id, TaskStatus.PENDING.value, masked_mode),
            )
            task_id = cursor.lastrowid
        return AiTask.get_by_id(task_id)

    @staticmethod
    def get_by_id(task_id: int) -> Optional[dict]:
        """根据ID获取任务详情."""
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM ai_tasks WHERE id = ?", (task_id,)
            ).fetchone()
            return dict(row) if row else None

    @staticmethod
    def get_by_host(host_id: int, limit: int = 1) -> list[dict]:
        """获取主机的AI分析任务列表（默认返回最新一条）."""
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM ai_tasks WHERE host_id = ? ORDER BY created_at DESC LIMIT ?",
                (host_id, limit),
            ).fetchall()
            return [dict(row) for row in rows]

    @staticmethod
    def get_latest_by_host(host_id: int) -> Optional[dict]:
        """获取主机最新的一条AI分析任务."""
        tasks = AiTask.get_by_host(host_id, limit=1)
        return tasks[0] if tasks else None

    @staticmethod
    def get_running_by_host(host_id: int) -> Optional[dict]:
        """检查主机是否有正在运行的AI分析任务."""
        with get_connection() as conn:
            row = conn.execute(
                """SELECT * FROM ai_tasks
                   WHERE host_id = ? AND status IN (?, ?)
                   ORDER BY created_at DESC LIMIT 1""",
                (host_id, TaskStatus.PENDING.value, TaskStatus.RUNNING.value),
            ).fetchone()
            return dict(row) if row else None

    @staticmethod
    def update_status(
        task_id: int,
        status: str,
        progress: Optional[int] = None,
        progress_message: Optional[str] = None,
        report_id: Optional[int] = None,
        error_message: Optional[str] = None,
    ) -> Optional[dict]:
        """更新任务状态.

        Args:
            task_id: 任务ID.
            status: 新状态（pending/running/completed/failed/cancelled）.
            progress: 进度百分比（0-100）.
            progress_message: 进度描述.
            report_id: 关联的报告ID.
            error_message: 错误信息.

        Returns:
            更新后的任务字典.
        """
        updates = ["status = ?", "updated_at = datetime('now')"]
        params: list[Any] = [status]

        if progress is not None:
            updates.append("progress = ?")
            params.append(progress)
        if progress_message is not None:
            updates.append("progress_message = ?")
            params.append(progress_message)
        if report_id is not None:
            updates.append("report_id = ?")
            params.append(report_id)
        if error_message is not None:
            updates.append("error_message = ?")
            params.append(error_message)

        # 状态变更时的附加时间戳
        if status == TaskStatus.RUNNING.value:
            updates.append("started_at = datetime('now')")
        if status in (TaskStatus.COMPLETED.value, TaskStatus.FAILED.value, TaskStatus.CANCELLED.value):
            updates.append("completed_at = datetime('now')")

        params.append(task_id)

        with get_connection() as conn:
            conn.execute(
                f"UPDATE ai_tasks SET {', '.join(updates)} WHERE id = ?",
                params,
            )
        return AiTask.get_by_id(task_id)

    @staticmethod
    def cancel(task_id: int) -> Optional[dict]:
        """取消指定的AI分析任务.

        Args:
            task_id: 任务ID.

        Returns:
            更新后的任务字典.

        Raises:
            ValueError: 任务不存在或不可取消.
        """
        task = AiTask.get_by_id(task_id)
        if task is None:
            raise ValueError("任务不存在")
        if task["status"] not in (TaskStatus.PENDING.value, TaskStatus.RUNNING.value):
            raise ValueError(f"任务状态为 {task['status']}，无法取消")

        return AiTask.update_status(
            task_id=task_id,
            status=TaskStatus.CANCELLED.value,
            progress=task.get("progress", 0),
            progress_message="任务已被用户取消",
        )

    @staticmethod
    def list_pending(limit: int = 10) -> list[dict]:
        """列出等待执行的任务（按创建时间升序）."""
        with get_connection() as conn:
            rows = conn.execute(
                """SELECT * FROM ai_tasks
                   WHERE status = ?
                   ORDER BY created_at ASC LIMIT ?""",
                (TaskStatus.PENDING.value, limit),
            ).fetchall()
            return [dict(row) for row in rows]
