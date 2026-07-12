"""进程事件流采集器（融合 §2.3 / §三.1，Mode B 事件流）.

Windows ETW 优先（可降级为进程快照）、Linux auditd/eBPF 优先（可降级）。
产出事件流按资源预算批量 flush（每 5s 或满 500 条）到 /process-events
（服务端端点已建；Agent 侧负责产出事件结构，由传输层上报）。

事件 schema 对齐方案 §2.3：event_type / pid / ppid / process_name / process_path /
command_line / parent_name / session / start_time / event_time / detail。
detail 可承载 memory_sections / etw_events / remote_thread_events / session。

无 macOS 分支（与主决策一致）；降级路径安全隔离，绝不抛异常拖垮 Agent。
"""

import logging
import time
from typing import List, Optional

from collectors.base_collector import BaseCollector
from collectors.resource_budget import (
    EVENT_FLUSH_INTERVAL_SEC,
    EVENT_FLUSH_BATCH_SIZE,
)
from utils.platform import is_windows, is_linux, get_timestamp

logger = logging.getLogger(__name__)


class EventRingBuffer:
    """事件环形缓冲（资源预算：每 5s 或满 500 条 flush 一次）.

    用于 ETW / auditd 高频事件流的批量上报，避免 HTTP 洪流。
    """

    def __init__(
        self,
        max_batch: int = EVENT_FLUSH_BATCH_SIZE,
        interval_sec: int = EVENT_FLUSH_INTERVAL_SEC,
    ) -> None:
        self.max_batch = max_batch
        self.interval_sec = interval_sec
        self._events: List[dict] = []
        self._last_flush = time.time()

    def add(self, event: dict) -> None:
        """追加一条事件."""
        if isinstance(event, dict):
            self._events.append(event)

    def should_flush(self, now: Optional[float] = None) -> bool:
        """是否达到 flush 条件（满批或超时）。"""
        if not self._events:
            return False
        now = now or time.time()
        return (
            len(self._events) >= self.max_batch
            or (now - self._last_flush) >= self.interval_sec
        )

    def drain(self) -> List[dict]:
        """取出当前批次（最多 max_batch 条）并重置计时."""
        batch, self._events = self._events[: self.max_batch], self._events[self.max_batch:]
        self._last_flush = time.time()
        return batch

    def __len__(self) -> int:
        return len(self._events)


class ProcessEventsCollector(BaseCollector):
    """进程事件流采集器."""

    name = "process_events"
    platform = ["windows", "linux"]

    def collect(self) -> List[dict]:
        """采集进程事件流.

        Returns:
            按资源预算 flush 的事件批次（process_start 等）。无事件或降级失败时返回空列表。
        """
        try:
            if is_windows():
                events = self._collect_windows()
            elif is_linux():
                events = self._collect_linux()
            else:
                return []
        except Exception as exc:
            logger.warning("进程事件采集失败: %s", exc)
            return []

        if not events:
            return []

        # 资源预算：批量 flush（5s / 500 条）
        rb = EventRingBuffer()
        for e in events:
            rb.add(e)
        batch = rb.drain()
        logger.info("进程事件采集 %d 条，flush %d 条", len(events), len(batch))
        return batch

    # ── 平台采集（ETW / auditd 优先，降级快照）─────────────────
    def _collect_windows(self) -> List[dict]:
        """Windows：ETW 优先，降级为进程快照."""
        # ETW Consumer Session 需 Admin/SeDebug 权限且全局仅 1 个/provider，
        # 与 Sysmon 可能冲突；此处优先尝试，失败则降级为快照。
        try:
            events = self._collect_etw()
            if events:
                return events
        except Exception as exc:
            logger.info("ETW 采集不可用（降级为进程快照）: %s", exc)
        return self._snapshot_events()

    def _collect_linux(self) -> List[dict]:
        """Linux：auditd/eBPF 优先，降级为进程快照."""
        try:
            events = self._collect_auditd()
            if events:
                return events
        except Exception as exc:
            logger.info("auditd/eBPF 采集不可用（降级为进程快照）: %s", exc)
        return self._snapshot_events()

    def _collect_etw(self) -> List[dict]:
        """ETW 事件采集（占位：需特权会话；当前返回空走降级路径）.

        真实实现应独占式订阅指定 provider 并消费进程生/灭、远线程、AMSI/ETW 旁路
        事件。环境受限时返回空列表，由调用方降级为进程快照。
        """
        # TODO(P2): 接入 ETW Consumer Session（需 Admin/SeDebug，处理与 Sysmon 共存）
        return []

    def _collect_auditd(self) -> List[dict]:
        """auditd/eBPF 事件采集（占位：需 CAP_AUDIT/CAP_BPF；当前返回空走降级路径）.

        真实实现应读取 auditd 规则（execve/mmap/mprotect/ptrace）或 eBPF 注入检测，
        产出 process_start / remote_thread 事件。环境受限时返回空列表降级。
        """
        # TODO(P2): 接入 auditd/eBPF 事件管线
        return []

    # ── 快照降级路径（始终可用）────────────────────────────────
    def _snapshot_events(self) -> List[dict]:
        """从当前进程快照生成 process_start 事件（降级路径，始终可用）.

        Returns:
            process_start 事件列表，schema 对齐 §2.3。
        """
        events: List[dict] = []
        try:
            from collectors.processes import ProcessesCollector
            processes = ProcessesCollector().safe_collect()
            if not isinstance(processes, list):
                return events
            now = get_timestamp()
            for proc in processes:
                if not isinstance(proc, dict):
                    continue
                pid = proc.get("pid")
                if pid is None:
                    continue
                detail: dict = {}
                # 透传富化字段，供事件流规则（#1/#2/#4/#5/#6）命中
                ms = proc.get("memory_sections")
                if isinstance(ms, list) and ms:
                    detail["memory_sections"] = ms
                session = proc.get("session")
                if session is not None:
                    detail["session"] = session
                events.append({
                    "event_type": "process_start",
                    "pid": pid,
                    "ppid": proc.get("ppid"),
                    "process_name": proc.get("name"),
                    "process_path": proc.get("path"),
                    "command_line": proc.get("command_line"),
                    "parent_name": proc.get("parent_name"),
                    "session": session,
                    "start_time": proc.get("start_time"),
                    "event_time": now,
                    "detail": detail,
                })
        except Exception as exc:
            logger.warning("进程快照事件生成失败: %s", exc)
        return events
