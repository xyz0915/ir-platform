"""JSON 输出格式化工具."""

import json
import logging
from pathlib import Path
from typing import Any, Optional

from collectors.resource_budget import MAX_REPORT_BYTES

logger = logging.getLogger(__name__)

# Agent 输出 JSON 的固定顶层 key（21个）
OUTPUT_KEYS = [
    "metadata",
    "system_info",
    "users",
    "processes",
    "services",
    "startup_items",
    "network",
    "files",
    "registry",
    "logs",
    "security",
    "browser",
    "usb",
    "remote_control",
    "persistence",
    "ioc",
    "timeline",
    "network_connections",
    "file_hashes",
    "wmi_subscriptions",
    "registry_keys",
]


def build_output(metadata: dict, raw_results: dict, collection_health: Optional[dict] = None) -> dict:
    """组装符合 Schema 的 Agent JSON 输出.

    Args:
        metadata: 元数据字典.
        raw_results: 各采集器结果字典 {collector_name: result}.
        collection_health: 可选采集健康状态（任务③），作为顶层字段注入.

    Returns:
        完整的 Agent JSON 数据字典.
    """
    output = {"metadata": metadata}

    # 注入采集健康状态（任务③）
    if collection_health is not None:
        output["collection_health"] = collection_health

    # 映射采集器结果到输出 key（原有 16 个采集器 key + 4 个新增顶层 key）
    original_keys = OUTPUT_KEYS[1:17]  # system_info ~ timeline (16 keys)
    for key in original_keys:
        result = raw_results.get(key)
        if result is None:
            # 设置默认值
            if key in ("system_info", "network", "files", "registry", "logs",
                        "security", "browser", "usb", "remote_control",
                        "persistence", "ioc"):
                output[key] = {}
            else:
                output[key] = []
        elif isinstance(result, dict) and "error" in result:
            # 采集失败，返回空结构
            logger.warning("Collector %s had error: %s", key, result.get("error"))
            if key in ("system_info", "network", "files", "registry", "logs",
                        "security", "browser", "usb", "remote_control",
                        "persistence", "ioc"):
                output[key] = {}
            else:
                output[key] = []
        else:
            # 对于 network/files/registry/persistence 采集器，提取其内部的 4 个新顶层 key
            output[key] = result
            # 从采集器内部提取平台所需顶层字段
            if isinstance(result, dict):
                for new_key in ["network_connections", "file_hashes",
                                "wmi_subscriptions", "registry_keys"]:
                    if new_key in result:
                        if new_key not in output:
                            output[new_key] = result[new_key]

    # 确保 4 个新顶层 key 始终存在
    for new_key in ["network_connections", "file_hashes",
                    "wmi_subscriptions", "registry_keys"]:
        if new_key not in output:
            output[new_key] = []

    # 融合扩充（A §三.1）：聚合 webshells / memory_shells / linux_baseline 顶层键。
    # 仅聚合顶层键（与既有采集器同风格）；process_events 走独立 /process-events
    # 事件管线，不并入 /import 输出。
    for fusion_key in ["webshells", "memory_shells", "linux_baseline"]:
        result = raw_results.get(fusion_key)
        if result is not None and not (isinstance(result, dict) and "error" in result):
            output[fusion_key] = result
        elif fusion_key not in output:
            output[fusion_key] = []

    # 资源预算闭环：超 MAX_REPORT_BYTES 时按优先级丢弃最重载荷
    _enforce_report_budget(output)
    return output


def _enforce_report_budget(output: dict) -> None:
    """估算序列化体积，超 MAX_REPORT_BYTES 时按优先级丢弃最重载荷.

    丢弃顺序（逐级，每级后重新估算，回到预算内即停）：
      1. ``processes[].memory_sections``（置空，保留键）
      2. ``process_events``（置空，保留键）
      3. ``linux_baseline``（置空，保留键）
      4. ``webshells`` / ``memory_shells`` 明细 → 仅留摘要（count + truncated 标记）

    所有丢弃均 ``logger.info`` 记录；超限本身 ``logger.warning``。
    顶层键一律保留（可置空），向后兼容。
    """
    def _serialized_bytes() -> int:
        return len(json.dumps(output, ensure_ascii=False, default=str).encode("utf-8"))

    if _serialized_bytes() <= MAX_REPORT_BYTES:
        return

    logger.warning(
        "Agent report exceeds budget (%d bytes > %d); trimming heavy payloads",
        _serialized_bytes(), MAX_REPORT_BYTES,
    )

    # 1. processes[].memory_sections
    procs = output.get("processes")
    if isinstance(procs, list):
        dropped = 0
        for p in procs:
            if isinstance(p, dict) and p.get("memory_sections"):
                p["memory_sections"] = []
                dropped += 1
        if dropped:
            logger.info("budget trim: cleared memory_sections from %d process(es)", dropped)

    if _serialized_bytes() <= MAX_REPORT_BYTES:
        return

    # 2. process_events
    pe = output.get("process_events")
    if pe:
        n = len(pe) if isinstance(pe, list) else 1
        output["process_events"] = [] if isinstance(pe, list) else {}
        logger.info("budget trim: cleared process_events (%d entry/ies)", n)

    if _serialized_bytes() <= MAX_REPORT_BYTES:
        return

    # 3. linux_baseline
    lb = output.get("linux_baseline")
    if lb:
        output["linux_baseline"] = {}
        logger.info("budget trim: cleared linux_baseline")

    if _serialized_bytes() <= MAX_REPORT_BYTES:
        return

    # 4. webshells / memory_shells 明细 → 仅留摘要
    for k in ("webshells", "memory_shells"):
        val = output.get(k)
        if isinstance(val, list) and val:
            n = len(val)
            output[k] = [{"_summary": True, "count": n, "truncated": True}]
            logger.info("budget trim: truncated %s detail to summary (was %d entries)", k, n)

    if _serialized_bytes() > MAX_REPORT_BYTES:
        logger.warning(
            "report still over budget after trimming: %d bytes", _serialized_bytes()
        )


def write_output(data: dict, output_path: str) -> None:
    """写入 JSON 输出文件.

    Args:
        data: 完整的 Agent JSON 数据.
        output_path: 输出文件路径.
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info("Output written to: %s", path)


def print_summary(data: dict) -> None:
    """控制台打印采集摘要.

    Args:
        data: 完整的 Agent JSON 数据.
    """
    print("\n" + "=" * 60)
    print("  IR Platform Agent — 采集摘要")
    print("=" * 60)

    metadata = data.get("metadata", {})
    print(f"  主机名:     {metadata.get('hostname', 'N/A')}")
    print(f"  平台:       {metadata.get('platform', 'N/A')}")
    print(f"  采集时间:   {metadata.get('collection_time', 'N/A')}")
    print(f"  Agent版本:  {metadata.get('agent_version', 'N/A')}")
    print("-" * 60)

    for key in OUTPUT_KEYS[1:]:
        val = data.get(key)
        if isinstance(val, list):
            count = len(val)
            print(f"  {key:20s}: {count:6d} 条")
        elif isinstance(val, dict):
            total = sum(
                len(v) for v in val.values() if isinstance(v, list)
            )
            print(f"  {key:20s}: {total:6d} 项")
        else:
            print(f"  {key:20s}: N/A")

    print("=" * 60 + "\n")
