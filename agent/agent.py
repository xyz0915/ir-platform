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
import json
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from datetime import datetime
from pathlib import Path
from typing import Optional

# 将当前目录加入 sys.path，确保 collectors 可导入
AGENT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(AGENT_DIR))

from collectors.base_collector import BaseCollector
from utils.platform import get_timestamp, is_windows, is_linux
from utils.output import build_output, write_output, print_summary
from utils._health import CollectorHealth
from utils.diff import compute_diff, load_baseline, save_baseline

logger = logging.getLogger(__name__)

# 每个采集器的最大执行时间（秒）—超时即降级（任务③）
COLLECTOR_TIMEOUT = 30

# 列表型采集器（其余默认按字典型处理）
_LIST_COLLECTORS = {
    "users", "processes", "services", "startup_items", "timeline",
    "network_connections", "file_hashes", "wmi_subscriptions", "registry_keys",
}


def _empty_result(name: str):
    """返回某采集器失败/跳过后用于降级的空结构."""
    return [] if name in _LIST_COLLECTORS else {}


def _count_items(name: str, result) -> int:
    """统计采集到的结果条目数（用于 collection_health.count）."""
    if isinstance(result, list):
        return len(result)
    if isinstance(result, dict):
        total = 0
        for v in result.values():
            if isinstance(v, list):
                total += len(v)
        return total if total else len(result)
    return 0

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


def _run_one(name: str, log_days: int):
    """在子线程中执行单个采集器（带平台支持检查）.

    Returns:
        (result, err) — err 为 None 表示成功；"not supported" 表示平台不支持。
    """
    collector = load_collector(name, log_days=log_days)
    if not collector.is_supported():
        return None, "not supported"
    return collector.collect(), None


def run_collectors(
    collect_names: list,
    log_days: int = 7,
    health: Optional[CollectorHealth] = None,
) -> dict:
    """依次执行指定采集器（任务③：每采集器超时+重试+降级 + 健康记录）.

    - 每个采集器在独立线程中执行，超时 COLLECTOR_TIMEOUT(30s) 即降级；
    - 首次失败/超时后降级重试 1 次；
    - 仍失败则返回空结构（不中断整体），并在 collection_health 中标记；
    - 进程采集为空时记录「进程列表为空」告警并降级为 degraded。

    Args:
        collect_names: 要执行的采集器名称列表.
        log_days: 采集最近 N 天的数据.
        health: 可选 CollectorHealth 累加器，记录每采集器健康状态.

    Returns:
        各采集器结果的字典 {collector_name: result}.
    """
    results = {}
    for name in collect_names:
        if name not in COLLECTOR_MAP:
            logger.warning("Unknown collector: %s, skipping", name)
            continue
        logger.info("Running collector: %s", name)
        status = "ok"
        warnings: list[str] = []
        result = None
        err: Optional[str] = None

        # 首次执行（带超时）
        try:
            with ThreadPoolExecutor(max_workers=1) as ex:
                future = ex.submit(_run_one, name, log_days)
                try:
                    result, err = future.result(timeout=COLLECTOR_TIMEOUT)
                except FuturesTimeout:
                    err = f"采集超时（>{COLLECTOR_TIMEOUT}s）"
        except Exception as exc:  # noqa: BLE001
            err = str(exc)

        # 失败/超时 → 降级重试 1 次
        if err is not None and err != "not supported":
            logger.warning("Collector %s 首次执行失败: %s，尝试降级重试", name, err)
            try:
                with ThreadPoolExecutor(max_workers=1) as ex:
                    future = ex.submit(_run_one, name, log_days)
                    try:
                        result, err = future.result(timeout=COLLECTOR_TIMEOUT)
                    except FuturesTimeout:
                        err = f"重试仍超时（>{COLLECTOR_TIMEOUT}s）"
            except Exception as exc:  # noqa: BLE001
                err = str(exc)
            if err is not None:
                warnings.append(f"{name} 采集失败：{err}，已降级返回空结果")
                status = "failed"
                result = _empty_result(name)
            else:
                warnings.append(f"{name} 首次失败（{err}）但重试成功")
                status = "degraded"

        if err == "not supported":
            logger.warning("Collector %s not supported on this platform", name)
            results[name] = {"error": "not supported", "collector": name}
            if health:
                health.record(name, "skipped", 0, [f"{name} 当前平台不支持"])
            continue

        # 统计数量 + 进程空告警
        if result is not None and not (isinstance(result, dict) and "error" in result):
            count = _count_items(name, result)
            if name == "processes" and count == 0:
                warnings.append("进程列表为空，可能影响关联分析")
                if status == "ok":
                    status = "degraded"
            results[name] = result
        else:
            # 异常分支（极少触发，保险）
            if status == "ok":
                status = "failed"
            if not warnings:
                warnings.append(f"{name} 采集异常，已降级返回空结果")
            result = _empty_result(name)
            results[name] = result

        if health:
            health.record(name, status, _count_items(name, result), warnings)
        logger.info("Collector %s done (status=%s, count=%d)", name, status,
                    _count_items(name, result))
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
    parser.add_argument(
        "--save-baseline",
        default=None,
        help="将当前采集结果保存为 baseline JSON（差分比对基线）",
    )
    parser.add_argument(
        "--diff",
        default=None,
        help="与指定 baseline JSON 比对，仅输出新增/变更部分",
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

    # 执行采集（传递 log_days 参数，并记录采集健康状态）
    health = CollectorHealth()
    raw_results = run_collectors(collect_names, log_days=args.log_days, health=health)

    # --save-baseline：落盘当前 raw_results 作为基线
    if args.save_baseline:
        save_baseline(raw_results, args.save_baseline)
        logger.info("Baseline written: %s", args.save_baseline)

    # 构建元数据
    metadata = {
        "agent_version": "1.1.0",
        "collection_time": get_timestamp(),
        "platform": "windows" if is_windows() else ("linux" if is_linux() else "unknown"),
        "hostname": raw_results.get("system_info", {}).get("hostname", "unknown")
        if isinstance(raw_results.get("system_info"), dict)
        else "unknown",
        "operator": "agent",
        "log_days": args.log_days,
    }

    # 生成采集健康状态
    collection_health = health.build(metadata["collection_time"])
    if collection_health["warnings"]:
        for w in collection_health["warnings"]:
            logger.warning("采集健康告警: %s", w)
    logger.info("采集健康摘要: %s", collection_health["summary"])

    # --diff：与 baseline 比对，仅输出新增/变更
    if args.diff:
        baseline = load_baseline(args.diff)
        if baseline is None:
            logger.warning("--diff 指定的 baseline 不可用，回退输出全量结果")
            output_data = build_output(metadata, raw_results, collection_health)
        else:
            diff_result = compute_diff(baseline, raw_results)
            output_data = {
                "metadata": {**metadata, "diff_mode": True, "baseline": args.diff},
                "diff": diff_result,
                "collection_health": collection_health,
            }
    else:
        # 组装输出（注入 collection_health）
        output_data = build_output(metadata, raw_results, collection_health)

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
