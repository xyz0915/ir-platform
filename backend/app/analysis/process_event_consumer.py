"""进程实时事件消费器（T15）— 与快照检测并行的事件流管道.

职责：
1. ingest        : 将 Agent 端推送的进程事件落库到 process_events 表。
2. normalize     : 将事件归一化为 ProcessInfo 风格 dict（去重 + 字段提升 +
                   快照重叠标记 seen_in_events / seen_in_snapshot）。
3. evaluate      : 复用 RuleEngine + AnomalyDetector 对归一化进程做行为评估，
                   与快照检测共用同一套行为模式（内存注入 / ETW 旁路 / 跨会话 /
                   注入窗口 / 快照间消失等）。

所有依赖 Agent 端高级采集（memory_sections / etw_events / remote_thread_events /
session）的规则在对应字段缺失时由各自 _match_* 优雅降级返回 False，绝不抛异常。
"""

import json
import logging
from typing import Any, Optional

from app.analysis.anomaly_detector import AnomalyDetector
from app.models.process_event import ProcessEvent
from app.rules.rule_engine import RuleEngine

logger = logging.getLogger(__name__)

# 从事件 detail（JSON）中提升的已知高级字段（缺失则忽略，规则自行降级）
_DETAIL_PROMOTE_KEYS = (
    "memory_sections",
    "etw_events",
    "remote_thread_events",
    "session",
)


class ProcessEventConsumer:
    """进程事件消费器."""

    @staticmethod
    def ingest(host_id: int, events: list) -> int:
        """摄取并落库进程事件.

        Args:
            host_id: 主机 ID.
            events: 原始事件列表（dict 列表，字段见 ProcessEvent.create）.

        Returns:
            写入的记录数.
        """
        return ProcessEvent.batch_create(host_id, events or [])

    @staticmethod
    def _parse_detail(detail: Any) -> dict:
        """解析事件 detail（可能为 JSON 字符串或已结构化对象）。"""
        if detail is None:
            return {}
        if isinstance(detail, dict):
            return detail
        if isinstance(detail, str):
            try:
                parsed = json.loads(detail)
                return parsed if isinstance(parsed, dict) else {}
            except (json.JSONDecodeError, TypeError):
                return {}
        return {}

    @staticmethod
    def normalize(host_id: int, snapshot_processes: Optional[list] = None) -> list:
        """将主机进程事件归一化为 ProcessInfo 风格 dict 列表.

        去重键：(pid, start_time|event_time)。同一进程的多条事件合并：
        - 基础字段取首条；
        - detail 中的高级字段（memory_sections / etw_events / remote_thread_events）
          提升为顶层字段，供规则直接命中；
        - 标注 seen_in_events=True；若提供快照进程，则按 pid 重叠标注
          seen_in_snapshot（用于 vanished_process 规则：仅在快照中明确缺失时为 False）。

        Args:
            host_id: 主机 ID.
            snapshot_processes: 同期快照进程列表（可选，用于重叠判定）。

        Returns:
            归一化进程 dict 列表（均为 ProcessInfo 兼容字段 + 可选扩展字段）。
        """
        events = ProcessEvent.list_process_starts(host_id)
        if not events:
            return []

        snapshot_pids: Optional[set] = None
        if snapshot_processes is not None:
            snapshot_pids = {
                p.get("pid") for p in snapshot_processes
                if isinstance(p, dict) and p.get("pid") is not None
            }

        merged: dict = {}
        for ev in events:
            if not isinstance(ev, dict):
                continue
            pid = ev.get("pid")
            start_time = ev.get("start_time") or ev.get("event_time") or ""
            key = (pid, start_time)
            detail = ProcessEventConsumer._parse_detail(ev.get("detail"))

            if key not in merged:
                proc = {
                    "pid": pid,
                    "ppid": ev.get("ppid"),
                    "name": ev.get("process_name"),
                    "path": ev.get("process_path"),
                    "command_line": ev.get("command_line"),
                    "parent_name": ev.get("parent_name"),
                    "start_time": start_time,
                    "seen_in_events": True,
                }
                session = ev.get("session")
                if session is not None:
                    proc["session"] = session
                # 提升 detail 中的高级字段（缺失不报错）
                for k in _DETAIL_PROMOTE_KEYS:
                    if k in detail and detail[k] is not None:
                        proc[k] = detail[k]
                if snapshot_pids is not None:
                    proc["seen_in_snapshot"] = pid in snapshot_pids
                merged[key] = proc
            else:
                # 后续事件仅补充尚未存在的扩展字段（如 ETW/远线程事件晚到）
                proc = merged[key]
                for k in _DETAIL_PROMOTE_KEYS:
                    if k in detail and detail[k] is not None and k not in proc:
                        proc[k] = detail[k]

        return list(merged.values())

    @staticmethod
    def evaluate(
        host_id: int,
        rules: list,
        snapshot_processes: Optional[list] = None,
    ) -> list:
        """对主机进程事件执行行为规则评估（与快照检测并行）.

        Args:
            host_id: 主机 ID.
            rules: 全量规则列表（内部按 process/behavior/execution 类别筛选）.
            snapshot_processes: 同期快照进程（可选，用于 vanished_process 重叠判定）.

        Returns:
            异常事件进程列表（结构同 AnomalyDetector._apply_accumulated_scoring 输出）.
        """
        normalized = ProcessEventConsumer.normalize(host_id, snapshot_processes)
        if not normalized:
            return []

        process_rules = [
            r for r in (rules or [])
            if r.get("category") in ("process", "behavior", "execution")
        ]
        if not process_rules:
            return []

        # 构建 process_map / ancestor_map（复用 anomaly_detector 的回溯逻辑）
        pid_to_proc: dict = {}
        for proc in normalized:
            if isinstance(proc, dict) and proc.get("pid") is not None:
                pid_to_proc[proc["pid"]] = proc

        ancestor_map: dict = {}
        for proc in normalized:
            if not isinstance(proc, dict):
                continue
            pid = proc.get("pid")
            if pid is None:
                continue
            chain: list = []
            cur = proc.get("ppid")
            seen: set = set()
            depth = 0
            while (
                cur is not None
                and cur not in (0, 1, 4)
                and cur not in seen
                and depth < 10
            ):
                seen.add(cur)
                chain.append(cur)
                parent = pid_to_proc.get(cur)
                if not parent:
                    break
                cur = parent.get("ppid")
                depth += 1
            ancestor_map[pid] = chain

        global_context = {
            "process_map": pid_to_proc,
            "all_items": normalized,
            "ancestor_map": ancestor_map,
            "iocs_by_type": RuleEngine._load_iocs_by_type(),
        }

        matches = RuleEngine.evaluate(normalized, process_rules, global_context=global_context)
        return AnomalyDetector._apply_accumulated_scoring(
            matches, global_context=global_context
        )
