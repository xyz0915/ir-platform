#!/usr/bin/env python3
"""个人应急响应平台 — Agent 采集端主入口.

Usage:
    python agent.py --output /path/to/output.json
    python agent.py --output result.json --collect system_info,processes,network
    python agent.py --collect all  # 默认采集全部
    python agent.py --output result.json --log-file agent.log --log-days 3

在目标主机上运行，采集系统信息并输出统一格式的 JSON 文件.
"""

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

# 将当前目录加入 sys.path，确保 collectors 可导入
AGENT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(AGENT_DIR))

from collectors.base_collector import BaseCollector
from utils.platform import get_timestamp, is_windows, is_linux
from utils.output import build_output, write_output, print_summary

logger = logging.getLogger(__name__)

# 采集器映射表
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
    # ── 融合扩充（A §三.1，只增不改；ProcessesCollector 就地增强，不新增 key）──
    "webshells": "collectors.webshell.WebShellCollector",
    "memory_shells": "collectors.memory.MemoryShellCollector",
    "linux_baseline": "collectors.linux.LinuxBaselineCollector",
    "process_events": "collectors.process_events.ProcessEventsCollector",
}


def load_collector(name: str, log_days: int = 7) -> BaseCollector:
    """动态加载采集器实例.

    Args:
        name: 采集器名称（如 system_info）.
        log_days: 采集最近 N 天的数据.

    Returns:
        BaseCollector 实例.

    Raises:
        ImportError: 模块导入失败.
        AttributeError: 类未找到.
    """
    module_path, class_name = COLLECTOR_MAP[name].rsplit(".", 1)
    module = __import__(module_path, fromlist=[class_name])
    cls = getattr(module, class_name)
    return cls(log_days=log_days)


# 返回 list 的采集器名集合：异常时降级为空 list（而非 {"error":...}），
# 便于下游统一按 list 处理。linux_baseline 返回 dict，不纳入。
_LIST_COLLECTORS: set = {
    "users", "processes", "network", "registry", "files",
    "persistence", "ioc", "timeline", "webshells",
    "memory_shells", "process_events",
}


def run_collectors(collect_names: list, log_days: int = 7, health=None) -> dict:
    """依次执行指定采集器.

    Args:
        collect_names: 要执行的采集器名称列表.
        log_days: 采集最近 N 天的数据，传递给各采集器.
        health: 可选 CollectorHealth 累加器；传入时逐个记录采集器状态/数量/告警，
            不传时行为与历史一致（向后兼容，既有调用方零影响）。

    Returns:
        各采集器结果的字典 {collector_name: result}.
    """
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
            if health is not None:
                count = len(result) if isinstance(result, list) else 0
                warnings = []
                if name == "processes" and isinstance(result, list) and len(result) == 0:
                    status = "degraded"
                    warnings = ["进程列表为空，可能影响关联分析"]
                else:
                    status = "ok"
                health.record(name, status, count, warnings)
        except Exception as exc:
            logger.exception("Collector %s failed: %s", name, exc)
            if name in _LIST_COLLECTORS:
                # list 型采集器异常 → 降级为空结构（下游统一按 list 处理）
                results[name] = []
            else:
                results[name] = {"error": str(exc), "collector": name}
            if health is not None:
                health.record(name, "failed", 0, [str(exc)])
    return results


def parse_args() -> argparse.Namespace:
    """解析命令行参数.

    Returns:
        解析后的参数对象.
    """
    parser = argparse.ArgumentParser(
        description="个人应急响应平台 Agent — 系统信息采集工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--output",
        "-o",
        default=None,
        help="输出 JSON 文件路径（默认：{hostname}_{timestamp}.json）",
    )
    parser.add_argument(
        "--collect",
        "-c",
        default="all",
        help="指定采集类别，逗号分隔（如 system_info,processes,network），默认 all",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="显示详细日志",
    )
    parser.add_argument(
        "--log-file",
        default=None,
        help="Agent 运行日志文件路径（同时输出到控制台和文件）",
    )
    parser.add_argument(
        "--log-days",
        type=int,
        default=7,
        help="采集最近N天的系统日志（默认7天）",
    )
    return parser.parse_args()


def check_privileges() -> None:
    """检查运行权限，提示需要管理员/root权限."""
    if is_windows():
        try:
            import ctypes
            if not ctypes.windll.shell32.IsUserAnAdmin():
                logger.warning("建议以管理员权限运行 Agent，否则部分采集功能受限")
        except Exception:
            pass
    elif is_linux():
        import os
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

    # 如果指定了 --log-file，同时输出到文件
    if args.log_file:
        file_handler = logging.FileHandler(args.log_file, encoding="utf-8")
        file_handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        logging.getLogger().addHandler(file_handler)
        logger.info("Agent log file enabled: %s", args.log_file)

    logger.info("=== IR Platform Agent Starting ===")
    logger.info("Log days filter: %d day(s)", args.log_days)
    check_privileges()

    # 确定要执行的采集器
    if args.collect == "all":
        collect_names = list(COLLECTOR_MAP.keys())
    else:
        collect_names = [c.strip() for c in args.collect.split(",") if c.strip()]

    logger.info("Collectors to run: %s", ", ".join(collect_names))

    # 执行采集（传递 log_days 参数）
    raw_results = run_collectors(collect_names, log_days=args.log_days)

    # 构建元数据
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

    # 组装输出
    output_data = build_output(metadata, raw_results)

    # 确定输出路径
    if args.output:
        output_path = args.output
    else:
        hostname = metadata["hostname"]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = f"{hostname}_{timestamp}.json"

    # 写入文件
    write_output(output_data, output_path)
    print_summary(output_data)

    logger.info("=== Agent completed. Output: %s ===", output_path)


if __name__ == "__main__":
    main()
