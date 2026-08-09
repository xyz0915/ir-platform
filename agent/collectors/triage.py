"""动态取证采集器（应急动态取证方案 Phase 2）.

被 daemon 的取证任务调度调用，按 scope 定向采集，返回可直接落库的结构：
{
  "file_hashes":         [...],   # 对齐 file_hashes 表字段
  "network_connections": [...],   # 对齐 network_connections 表字段
  "process_events":      [...]    # 对齐 process_events 表字段（event_type=process_start）
}
各采集复用既有采集器，仅在失败时降级为空列表，绝不抛异常拖垮 daemon。
"""

import logging

from utils.platform import get_timestamp

logger = logging.getLogger(__name__)


class TriageCollector:
    """动态取证采集器（按 scope 定向采集）."""

    @staticmethod
    def collect_triage(scope: list) -> dict:
        """按 scope 定向采集，返回三类结果列表."""
        result = {"file_hashes": [], "network_connections": [], "process_events": []}
        scope_set = set(scope or [])

        if "file_hashes" in scope_set:
            try:
                from collectors.files import FilesCollector
                data = FilesCollector().collect()
                if isinstance(data, dict):
                    result["file_hashes"] = data.get("file_hashes") or []
            except Exception as exc:
                logger.warning("triage file_hashes failed: %s", exc)

        if "network" in scope_set:
            try:
                from collectors.network import NetworkCollector
                conns = NetworkCollector().collect()
                result["network_connections"] = _map_network(conns)
            except Exception as exc:
                logger.warning("triage network failed: %s", exc)

        if "process_subtree" in scope_set:
            try:
                from collectors.processes import ProcessesCollector
                procs = ProcessesCollector().collect()
                result["process_events"] = _map_processes(procs)
            except Exception as exc:
                logger.warning("triage process_subtree failed: %s", exc)

        return result


def _map_network(conns) -> list:
    out = []
    for c in (conns or []):
        if not isinstance(c, dict):
            continue
        out.append({
            "protocol": c.get("protocol"),
            "local_address": c.get("local_address"),
            "local_port": c.get("local_port"),
            "remote_address": c.get("remote_address"),
            "remote_port": c.get("remote_port"),
            "state": c.get("state"),
            "pid": c.get("pid"),
            "process_name": c.get("process_name"),
            "collected_at": c.get("collected_at"),
        })
    return out


def _map_processes(procs) -> list:
    out = []
    now = get_timestamp()
    for p in (procs or []):
        if not isinstance(p, dict):
            continue
        out.append({
            "event_type": "process_start",
            "pid": p.get("pid"),
            "ppid": p.get("ppid"),
            "process_name": p.get("name"),
            "process_path": p.get("path"),
            "command_line": p.get("command_line"),
            "parent_name": p.get("parent_name"),
            "start_time": p.get("create_time") or p.get("start_time"),
            "event_time": now,
        })
    return out
