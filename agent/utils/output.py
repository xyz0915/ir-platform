"""JSON 输出格式化工具."""

import json
import logging
from pathlib import Path
from typing import Any

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


def build_output(metadata: dict, raw_results: dict) -> dict:
    """组装符合 Schema 的 Agent JSON 输出.

    Args:
        metadata: 元数据字典.
        raw_results: 各采集器结果字典 {collector_name: result}.

    Returns:
        完整的 Agent JSON 数据字典.
    """
    output = {"metadata": metadata}

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

    return output


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
