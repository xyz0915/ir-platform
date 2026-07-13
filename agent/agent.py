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
        logger.warning("Push events HTTP %d: %s", e.code, e.read().decode()[:200])
    except Exception as e:
        logger.warning("Push events failed: %s", e)
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
    except Exception as e:
        logger.warning("Heartbeat failed: %s", e)
        return False


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
                            item["event_type"] = name
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

    # 4. 取 host_id（从平台注册获取或从参数读）
    host_id = int(args.daemon_id) if args.daemon_id and args.daemon_id.isdigit() else 0
    if host_id == 0:
        logger.info("host_id not provided, snapshot only mode (no push)")
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
