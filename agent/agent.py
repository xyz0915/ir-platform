#!/usr/bin/env python3
"""个人应急响应平台 — Agent 采集端主入口.

Usage:
    python agent.py                                    # 一次性采集（默认）
    python agent.py --daemon                           # 常驻监控模式
    python agent.py --daemon --server http://host:8000 # 常驻+推送至平台
    python agent.py --collect processes,network        # 仅采集指定模块
    python agent.py --output result.json               # 指定输出路径
"""

import argparse
import json
import logging
import os
import signal
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path
from typing import Optional

from collectors.base_collector import BaseCollector
from utils.platform import get_timestamp, is_windows, is_linux
from utils.output import build_output, write_output, print_summary

logger = logging.getLogger(__name__)

AGENT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(AGENT_DIR))

# ── 采集器注册表 ──
COLLECTOR_MAP = {
    "system_info": "collectors.system_info.SystemInfoCollector",
    "users": "collectors.users.UsersCollector",
    "processes": "collectors.processes.ProcessesCollector",
    "services": "collectors.services.ServicesCollector",
    "startup_items": "collectors.startup_items.StartupItemsCollector",
    "network": "collectors.network.NetworkCollector",
    "files": "collectors.files.FilesCollector",
    "registry": "collectors.registry.RegistryCollector",
    "logs": "collectors.logs.LogsCollector",
    "security": "collectors.security.SecurityCollector",
    "browser": "collectors.browser.BrowserCollector",
    "usb": "collectors.usb.UsbCollector",
    "remote_control": "collectors.remote_control.RemoteControlCollector",
    "persistence": "collectors.persistence.PersistenceCollector",
    "ioc": "collectors.ioc.IocCollector",
    "timeline": "collectors.timeline.TimelineCollector",
    "webshells": "collectors.webshell.WebShellCollector",
    "memory_shells": "collectors.memory.MemoryShellCollector",
    "linux_baseline": "collectors.linux.LinuxBaselineCollector",
    "process_events": "collectors.process_events.ProcessEventsCollector",
}

_LIST_COLLECTORS: set = {
    "users", "processes", "network", "registry", "files",
    "persistence", "ioc", "timeline", "webshells",
    "memory_shells", "process_events",
}

# ── 增量事件采样器（常驻模式用） ──
_DAEMON_COLLECT_INTERVALS = {
    "process_events": 5,      # 进程事件：每 5s 采集一次
    "network": 30,            # 网络连接：每 30s 采集一次
    "files": 10,              # 文件变更：每 10s 采集一次
    "logs": 60,               # 日志事件：每 60s 采集一次
}

_DAEMON_HEARTBEAT_INTERVAL = 30  # 心跳间隔（秒）
_DAEMON_PUSH_BATCH_SIZE = 50      # 批量推送条数上限
_DAEMON_TRIAGE_POLL_INTERVAL = 30  # 动态取证任务轮询间隔（秒，命令通道方案 A）
_daemon_running = True


def load_collector(name: str, log_days: int = 7) -> BaseCollector:
    """动态加载采集器实例."""
    module_path, class_name = COLLECTOR_MAP[name].rsplit(".", 1)
    module = __import__(module_path, fromlist=[class_name])
    cls = getattr(module, class_name)
    return cls(log_days=log_days)


def run_collectors(collect_names: list, log_days: int = 7, health=None) -> dict:
    """依次执行指定采集器."""
    results = {}
    for name in collect_names:
        if name not in COLLECTOR_MAP:
            logger.warning("Unknown collector: %s, skipping", name)
            continue
        logger.info("Running collector: %s", name)
        try:
            collector = load_collector(name, log_days=log_days)
            if not collector.is_supported():
                logger.warning("Collector %s not supported on this platform", name)
                results[name] = {"error": "not supported", "collector": name}
                continue
            result = collector.collect()
            results[name] = result
            logger.info("Collector %s completed", name)
        except Exception as exc:
            logger.exception("Collector %s failed: %s", name, exc)
            if name in _LIST_COLLECTORS:
                results[name] = []
            else:
                results[name] = {"error": str(exc), "collector": name}
    return results


def parse_args() -> argparse.Namespace:
    """解析命令行参数."""
    parser = argparse.ArgumentParser(
        description="个人应急响应平台 Agent — 系统信息采集工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--output", "-o", default=None,
                        help="输出 JSON 文件路径（默认：{hostname}_{timestamp}.json）")
    parser.add_argument("--collect", "-c", default="all",
                        help="指定采集类别，逗号分隔，默认 all")
    parser.add_argument("--verbose", "-v", action="store_true", help="显示详细日志")
    parser.add_argument("--log-file", default=None, help="Agent 运行日志文件路径")
    parser.add_argument("--log-days", type=int, default=7,
                        help="采集最近 N 天的系统日志（默认 7 天）")
    # ── 常驻模式参数 ──
    parser.add_argument("--daemon", action="store_true", help="常驻监控模式")
    parser.add_argument("--server", default=None,
                        help="平台服务器地址（常驻模式下推送事件，如 http://host:8000）")
    parser.add_argument("--token", default=None,
                        help="平台认证 Token（常驻模式下使用）")
    parser.add_argument("--daemon-id", default=None,
                        help="常驻模式主机标识（不指定则自动注册）")
    return parser.parse_args()


class _TokenInvalidError(Exception):
    """agent token 无效或已重置（平台返回 401/403）."""


def _bootstrap(server: str, token: str, metadata: dict) -> Optional[int]:
    """Agent 自举注册：用 token 向平台换取 host_id.

    POST {server}/api/agents/bootstrap，Authorization: Bearer <token>，
    请求体含 hostname/os_type/agent_version 等元数据，15s 超时（与 _push_events 同风格）。

    Returns:
        host_id（int）.

    Raises:
        _TokenInvalidError: 平台返回 401/403（token 无效或已重置）.
        Exception: 网络/服务端其它失败.
    """
    url = f"{server.rstrip('/')}/api/agents/bootstrap"
    payload = {
        "hostname": metadata.get("hostname"),
        "os_type": metadata.get("platform"),
        "agent_version": metadata.get("agent_version"),
        "collectors": [],
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data,
                                  headers={"Content-Type": "application/json"})
    req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read().decode())
            host_id = (body or {}).get("data", {}).get("host_id")
            return int(host_id) if host_id else None
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise _TokenInvalidError(e.code)
        logger.error("Bootstrap HTTP %d: %s", e.code, e.read().decode()[:200])
        raise


def _push_events(server: str, token: str, host_id: int, events: list,
                 endpoint: str = "/api/hosts/{host_id}/process-events") -> bool:
    """推送事件列表到平台."""
    if not events:
        return True
    url = f"{server.rstrip('/')}{endpoint.format(host_id=host_id)}"
    data = json.dumps(events).encode("utf-8")
    req = urllib.request.Request(url, data=data,
                                  headers={"Content-Type": "application/json"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read().decode())
            logger.debug("Pushed %d events, response: %s", len(events), body.get("written", 0))
            return True
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            logger.error("token 无效或已重置，请在前端主机 Agent 页重新生成 Token (HTTP %d)", e.code)
        else:
            logger.warning("Push events HTTP %d: %s", e.code, e.read().decode()[:200])
    except Exception as e:
        logger.warning("Push events failed (network): %s", e)
    return False


def _send_heartbeat(server: str, token: str, host_id: int) -> bool:
    """发送心跳."""
    url = f"{server.rstrip('/')}/api/hosts/{host_id}/heartbeat"
    data = json.dumps({"agent_id": f"agent-{host_id}", "timestamp": datetime.now().isoformat()}).encode()
    req = urllib.request.Request(url, data=data,
                                  headers={"Content-Type": "application/json"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            logger.error("token 无效或已重置，请在前端主机 Agent 页重新生成 Token (HTTP %d)", e.code)
        else:
            logger.warning("Heartbeat HTTP %d: %s", e.code, e.read().decode()[:200])
        return False
    except Exception as e:
        logger.warning("Heartbeat failed (network): %s", e)
        return False


def _fetch_triage_task(server: str, token: str, host_id: int) -> Optional[dict]:
    """轮询平台待执行的动态取证任务（命令通道方案 A）."""
    url = f"{server.rstrip('/')}/api/hosts/{host_id}/triage-tasks/pending"
    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode())
            data = (body or {}).get("data")
            return data if isinstance(data, dict) else None
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            logger.error("token 无效或已重置，请在前端主机 Agent 页重新生成 Token (HTTP %d)", e.code)
        else:
            logger.debug("Fetch triage task HTTP %d", e.code)
    except Exception as e:
        logger.debug("Fetch triage task failed (network): %s", e)
    return None


def _report_triage_result(server: str, token: str, host_id: int, task_id: int,
                           result: dict, summary: dict, error: str = None) -> bool:
    """回传动态取证结果到平台（落库到专用表，source='triage'）."""
    url = f"{server.rstrip('/')}/api/hosts/{host_id}/triage-tasks/{task_id}/result"
    payload = {
        "file_hashes": result.get("file_hashes", []),
        "network_connections": result.get("network_connections", []),
        "process_events": result.get("process_events", []),
        "summary": summary,
        "error": error,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status == 200
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            logger.error("token 无效或已重置，请在前端主机 Agent 页重新生成 Token (HTTP %d)", e.code)
        else:
            logger.warning("Report triage result HTTP %d: %s", e.code, e.read().decode()[:200])
    except Exception as e:
        logger.warning("Report triage result failed (network): %s", e)
    return False


def _maybe_run_triage(server: str, token: str, host_id: int) -> None:
    """拉取并执行一条待处理动态取证任务."""
    task = _fetch_triage_task(server, token, host_id)
    if not task:
        return
    task_id = task.get("id")
    try:
        from collectors.triage import TriageCollector
        result = TriageCollector.collect_triage(task.get("scope") or [])
        summary = {k: len(v) for k, v in result.items() if isinstance(v, list)}
        ok = _report_triage_result(server, token, host_id, task_id, result, summary)
        if not ok:
            # D-4：网络/服务瞬时异常时重试 1 次；仍失败则交由服务端超时回收（recover_stale）兜底
            logger.warning("动态取证结果回传失败 task=%d，重试 1 次", task_id)
            ok = _report_triage_result(server, token, host_id, task_id, result, summary)
        if ok:
            logger.info("动态取证完成 task=%d summary=%s", task_id, summary)
        else:
            logger.warning("动态取证结果回传仍失败 task=%d，等待服务端超时回收", task_id)
    except Exception as exc:
        logger.warning("动态取证执行失败 task=%d: %s", task_id, exc)
        _report_triage_result(server, token, host_id, task_id,
                               {"file_hashes": [], "network_connections": [], "process_events": []},
                               None, error=str(exc))


def _collect_incremental(collect_names: list, last_results: dict) -> list:
    """增量采集，返回新增事件列表."""
    events = []
    for name in collect_names:
        if name not in COLLECTOR_MAP:
            continue
        try:
            collector = load_collector(name)
            if not collector.is_supported():
                continue
            result = collector.collect()
            if isinstance(result, list):
                # 简单去重：仅推送新增的（用 id/pid 去重）
                old_ids = {(e.get("pid"), e.get("process_name", ""))
                          for e in (last_results.get(name) or []) if isinstance(e, dict)}
                for item in result:
                    if isinstance(item, dict):
                        key = (item.get("pid"), item.get("process_name", ""))
                        if key not in old_ids:
                            # 保留原始 event_type（如 process_start），仅用 source 记录采集器名，
                            # 避免覆盖后 process_events 表失去 process_start 类型导致归一化/根因捞不到
                            item["source"] = name
                            events.append(item)
                last_results[name] = result
        except Exception as exc:
            logger.debug("Incremental collect %s failed: %s", name, exc)
    return events


def run_daemon(args: argparse.Namespace) -> None:
    """常驻模式主循环."""
    global _daemon_running

    server = args.server or "http://localhost:8000"
    logger.info("=== Agent Daemon Mode Starting ===")
    logger.info("Server: %s", server)

    # 1. 采集初始快照（全量）
    logger.info("Phase 1: Initial snapshot collection...")
    collect_names = list(COLLECTOR_MAP.keys())
    snapshot = run_collectors(collect_names, log_days=args.log_days)

    # 2. 构建主机元数据
    hostname = (snapshot.get("system_info", {}) or {}).get("hostname", "unknown") if isinstance(snapshot.get("system_info"), dict) else "unknown"
    metadata = {
        "agent_version": "1.0.0",
        "collection_time": get_timestamp(),
        "platform": "windows" if is_windows() else ("linux" if is_linux() else "unknown"),
        "hostname": hostname,
        "operator": "daemon",
    }

    # 3. 输出初始快照到文件（保留现场）
    output_data = build_output(metadata, snapshot)
    snapshot_path = f"{hostname}_snapshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    write_output(output_data, snapshot_path)
    logger.info("Snapshot saved: %s", snapshot_path)

    # 4. 取 host_id：显式 --daemon-id 直接使用；否则有 --token 时自举认领
    host_id = int(args.daemon_id) if args.daemon_id and args.daemon_id.isdigit() else 0
    if host_id == 0:
        if args.token:
            logger.info("host_id not provided, bootstrapping with token...")
            try:
                host_id = _bootstrap(server, args.token, metadata)
            except _TokenInvalidError:
                logger.error("token 无效或已重置，请在前端主机 Agent 页重新生成 Token")
                sys.exit(2)
            except Exception:
                logger.error("Bootstrap failed: 无法连接平台 %s，fail-fast 退出", server)
                sys.exit(1)
            if not host_id:
                logger.error("Bootstrap failed: 平台未返回有效 host_id")
                sys.exit(1)
            logger.info("Daemon running with host_id=%d, pushing to %s", host_id, server)
        else:
            logger.info("缺少 --token 或 --daemon-id，无法接入平台，进入 snapshot-only 模式 (no push)")
    else:
        logger.info("Daemon running with host_id=%d, pushing to %s", host_id, server)

    # 5. 信号处理
    def _signal_handler(sig, frame):
        global _daemon_running
        logger.info("Received signal %s, shutting down...", sig)
        _daemon_running = False

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    # 6. 增量采集循环
    last_collect_time = {name: 0 for name in _DAEMON_COLLECT_INTERVALS}
    last_heartbeat_time = time.time()
    last_triage_poll_time = 0  # 立即首轮即尝试拉取待执行取证任务
    last_results = snapshot
    event_buffer = []

    logger.info("Entering event loop (press Ctrl+C to stop)...")
    while _daemon_running:
        now = time.time()

        # 增量采集（复用 _collect_incremental 函数）
        incremental_names = [n for n, interval in _DAEMON_COLLECT_INTERVALS.items()
                            if now - last_collect_time.get(n, 0) >= interval]
        if incremental_names:
            new_events = _collect_incremental(incremental_names, last_results)
            for evt in new_events:
                event_buffer.append(evt)
            for n in incremental_names:
                last_collect_time[n] = now

        # 批量推送
        if host_id > 0 and event_buffer:
            batch = event_buffer[:_DAEMON_PUSH_BATCH_SIZE]
            if _push_events(server, args.token, host_id, batch):
                event_buffer = event_buffer[_DAEMON_PUSH_BATCH_SIZE:]
            else:
                # 推送失败 → 保留，下次重试
                logger.debug("Push failed, %d events pending", len(event_buffer))

        # 心跳
        if host_id > 0 and now - last_heartbeat_time >= _DAEMON_HEARTBEAT_INTERVAL:
            _send_heartbeat(server, args.token, host_id)
            last_heartbeat_time = now

        # 动态取证任务轮询（命令通道方案 A：每 30s 拉取 pending 任务并执行）
        if host_id > 0 and now - last_triage_poll_time >= _DAEMON_TRIAGE_POLL_INTERVAL:
            _maybe_run_triage(server, args.token, host_id)
            last_triage_poll_time = now

        time.sleep(1)

    # 7. 清理退出
    logger.info("Flushing %d remaining events...", len(event_buffer))
    while event_buffer:
        batch = event_buffer[:_DAEMON_PUSH_BATCH_SIZE]
        if _push_events(server, args.token, host_id, batch):
            event_buffer = event_buffer[_DAEMON_PUSH_BATCH_SIZE:]
        else:
            break
    logger.info("Agent daemon stopped gracefully")


def check_privileges() -> None:
    """检查运行权限."""
    if is_windows():
        try:
            import ctypes
            if not ctypes.windll.shell32.IsUserAnAdmin():
                logger.warning("建议以管理员权限运行 Agent，否则部分采集功能受限")
        except Exception:
            pass
    elif is_linux():
        if os.geteuid() != 0:
            logger.warning("建议以 root 权限运行 Agent，否则部分采集功能受限")


def main() -> None:
    """Agent 主入口函数."""
    args = parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if args.log_file:
        file_handler = logging.FileHandler(args.log_file, encoding="utf-8")
        file_handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        logging.getLogger().addHandler(file_handler)

    # ── 常驻模式 ──
    if args.daemon:
        run_daemon(args)
        return

    # ── 一次性采集模式（原有逻辑） ──
    logger.info("=== IR Platform Agent Starting ===")
    logger.info("Log days filter: %d day(s)", args.log_days)
    check_privileges()

    if args.collect == "all":
        collect_names = list(COLLECTOR_MAP.keys())
    else:
        collect_names = [c.strip() for c in args.collect.split(",") if c.strip()]

    logger.info("Collectors to run: %s", ", ".join(collect_names))
    raw_results = run_collectors(collect_names, log_days=args.log_days)

    metadata = {
        "agent_version": "1.0.0",
        "collection_time": get_timestamp(),
        "platform": "windows" if is_windows() else ("linux" if is_linux() else "unknown"),
        "hostname": raw_results.get("system_info", {}).get("hostname", "unknown")
        if isinstance(raw_results.get("system_info"), dict)
        else "unknown",
        "operator": "agent",
        "log_days": args.log_days,
    }

    output_data = build_output(metadata, raw_results)

    if args.output:
        output_path = args.output
    else:
        hostname = metadata["hostname"]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = f"{hostname}_{timestamp}.json"

    write_output(output_data, output_path)
    print_summary(output_data)
    logger.info("=== Agent completed. Output: %s ===", output_path)


if __name__ == "__main__":
    main()
