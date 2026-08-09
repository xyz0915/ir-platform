"""ProcessEvent 数据模型 — 进程实时事件表（process_events）的 CRUD.

T15：与周期性快照并行的新事件流管道。Agent 端推送的进程生/灭、远线程注入、
ETW/AMSI 旁路等事件先落库到 process_events，再由 process_event_consumer 归一化为
ProcessInfo 风格 dict，复用 RuleEngine 评估（与快照检测共用同一套行为模式）。
"""

import json
import logging
from typing import Any, Optional

from app.database import get_connection

logger = logging.getLogger(__name__)


class ProcessEvent:
    """进程实时事件数据模型."""

    @staticmethod
    def create(
        host_id: int,
        event_type: str,
        pid: Optional[int] = None,
        ppid: Optional[int] = None,
        process_name: Optional[str] = None,
        process_path: Optional[str] = None,
        command_line: Optional[str] = None,
        parent_name: Optional[str] = None,
        session: Optional[int] = None,
        start_time: Optional[str] = None,
        event_time: Optional[str] = None,
        detail: Optional[Any] = None,
        collected_at: Optional[str] = None,
        source: Optional[str] = None,
    ) -> int:
        """写入单条进程事件.

        Args:
            host_id: 主机 ID.
            event_type: 事件类型（process_start/process_exit/remote_thread/etw/amsi ...）.
            pid/ppid: 进程/父进程 ID.
            process_name/process_path/command_line/parent_name: 进程基础信息.
            session: 会话 ID（跨会话检测）.
            start_time: 进程启动时间.
            event_time: 事件时间戳.
            detail: 事件细化数据（dict/list，自动 JSON 序列化；可承载 memory_sections/
                etw_events/remote_thread_events 等）.
            collected_at: 采集时间.
            source: 事件来源（process_events=常驻 daemon / triage=动态取证 等），用于溯源.

        Returns:
            新插入行的主键 id.
        """
        if detail is not None and not isinstance(detail, str):
            try:
                detail = json.dumps(detail, ensure_ascii=False)
            except (TypeError, ValueError):
                detail = str(detail)
        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO process_events
                    (host_id, event_type, pid, ppid, process_name, process_path,
                     command_line, parent_name, session, start_time, event_time,
                     detail, collected_at, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    host_id, event_type, pid, ppid, process_name, process_path,
                    command_line, parent_name, session, start_time, event_time,
                    detail, collected_at, source,
                ),
            )
            return int(cursor.lastrowid)

    @staticmethod
    def batch_create(host_id: int, events: list) -> int:
        """批量写入进程事件.

        Args:
            host_id: 主机 ID.
            events: 事件列表，每项可为 dict（含 event_type/pid/...字段）或已展开的参数。

        Returns:
            插入的记录数.
        """
        if not events:
            return 0
        count = 0
        for ev in events:
            if not isinstance(ev, dict):
                continue
            ProcessEvent.create(
                host_id=host_id,
                event_type=ev.get("event_type", "unknown"),
                pid=ev.get("pid"),
                ppid=ev.get("ppid"),
                process_name=ev.get("process_name") or ev.get("name"),
                process_path=ev.get("process_path") or ev.get("path"),
                command_line=ev.get("command_line"),
                parent_name=ev.get("parent_name"),
                session=ev.get("session"),
                start_time=ev.get("start_time"),
                event_time=ev.get("event_time") or ev.get("timestamp"),
                detail=ev.get("detail"),
                collected_at=ev.get("collected_at"),
                source=ev.get("source"),
            )
            count += 1
        return count

    @staticmethod
    def list_by_host(host_id: int) -> list:
        """获取主机的全部进程事件."""
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM process_events WHERE host_id = ? ORDER BY id",
                (host_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    @staticmethod
    def list_by_host_and_type(host_id: int, event_type: str) -> list:
        """按主机 + 事件类型筛选."""
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM process_events WHERE host_id = ? AND event_type = ? ORDER BY id",
                (host_id, event_type),
            ).fetchall()
            return [dict(r) for r in rows]

    @staticmethod
    def list_process_starts(host_id: int) -> list:
        """获取主机的进程启动事件（归一化检测的主数据源）."""
        return ProcessEvent.list_by_host_and_type(host_id, "process_start")
