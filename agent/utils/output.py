"""JSON 输出格式化工具."""

import json
import logging
from pathlib import Path
from typing import Any, Optional

from utils.platform import normalize_timestamp
from collectors.resource_budget import MAX_REPORT_BYTES

logger = logging.getLogger(__name__)


def _build_timeline(raw_results: dict) -> list:
    """从所有采集器结果构建时间线（延迟导入避免循环依赖）."""
    try:
        from collectors.timeline import TimelineCollector
        return TimelineCollector().build_from_results(raw_results)
    except Exception as exc:
        logger.warning("Timeline construction failed: %s", exc)
        return []

# Agent 输出 JSON 的固定顶层 key（22个）
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
    "process_events",
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

    # 在所有采集器结果就绪后，构建时间线（覆盖 timeline 采集器的空 collect 结果）
    raw_results["timeline"] = _build_timeline(raw_results)

    # 注入采集健康状态（任务③）
    if collection_health is not None:
        output["collection_health"] = collection_health

    # 映射采集器结果到输出 key（原有 16 个采集器 key + process_events + 4 个新增顶层 key）
    original_keys = OUTPUT_KEYS[1:18]  # system_info ~ process_events (17 keys)
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
    # process_events 已通过 OUTPUT_KEYS 纳入一次性 JSON 输出；daemon 管线的
    # 增量推送走独立 /process-events REST 端点，两者不冲突。
    for fusion_key in ["webshells", "memory_shells", "linux_baseline"]:
        result = raw_results.get(fusion_key)
        if result is not None and not (isinstance(result, dict) and "error" in result):
            output[fusion_key] = result
        elif fusion_key not in output:
            output[fusion_key] = []

    # 跨采集器去重：按 dedup_key 合并同源条目（先到先保留）
    _deduplicate(output)

    # 统一时间标准化（Phase 1：先处理 timeline 作为试点）
    for key in ["timeline"]:
        items = output.get(key, [])
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict) and "timestamp" in item:
                    item["timestamp"] = normalize_timestamp(item["timestamp"], source=key)

    # 资源预算闭环：超 MAX_REPORT_BYTES 时按优先级丢弃最重载荷
    _enforce_report_budget(output)
    return output


def _deduplicate(output: dict) -> None:
    """跨采集器去重：按 ``dedup_key`` 合并同源条目（先到先保留）.

    处理顺序与 ``OUTPUT_KEYS`` 遍历顺序一致（services → startup_items → registry → persistence），
    同 ``dedup_key`` 的第一个条目保留，后续重复条目丢弃。字段最全的采集器（services / startup_items）
    在遍历中先出现，因此自动保留。

    同时做**字段名归一化**：不同采集器对同一数据的字段命名不同（如 ``value`` / ``command``），
    归一化后两个字段名在保留条目中同时存在，保证下游按任意名字均可读取。
    """
    # ── Phase 1: 收集第一个出现的 dedup_key ──
    first_seen: dict[str, tuple[str, Optional[str], int]] = {}
    # (output_key, sub_key_or_None, index_in_list)

    # 遍历顺序 = OUTPUT_KEYS 采集器顺序（先到先保留）
    overlap_regions = [
        ("services", None),
        ("startup_items", None),
        ("registry", "run_keys"),
        ("registry", "services"),
        ("registry", "scheduled_tasks"),
        ("persistence", "run_keys"),
        ("persistence", "services"),
        ("persistence", "scheduled_tasks"),
    ]

    for output_key, sub_key in overlap_regions:
        parent = output.get(output_key)
        if sub_key:
            if not isinstance(parent, dict):
                continue
            entries = parent.get(sub_key, [])
        else:
            entries = parent
        if not isinstance(entries, list):
            continue
        for i, entry in enumerate(entries):
            if not isinstance(entry, dict):
                continue
            dk = entry.get("dedup_key")
            if dk and dk not in first_seen:
                first_seen[dk] = (output_key, sub_key, i)

    if not first_seen:
        return  # 无 dedup_key → 无需去重

    # ── Phase 2: 删除重复条目 + 字段名归一化 ──
    # 字段名别名映射：target_field → [source_field, ...]
    # 尽量多的别名链，确保任意源字段都能填补所有目标字段
    FIELD_ALIASES: dict[str, list[str]] = {
        "command": ["value", "binary_path", "image_path"],
        "value": ["command", "binary_path", "image_path"],
        "binary_path": ["image_path", "command", "value"],
        "image_path": ["binary_path", "command", "value"],
    }

    for output_key, sub_key in overlap_regions:
        parent = output.get(output_key)
        if sub_key:
            if not isinstance(parent, dict):
                continue
            entries = parent.get(sub_key, [])
        else:
            entries = parent
        if not isinstance(entries, list):
            continue

        new_entries: list[dict] = []
        for i, entry in enumerate(entries):
            if not isinstance(entry, dict):
                new_entries.append(entry)
                continue
            dk = entry.get("dedup_key")
            if dk and dk in first_seen:
                first_info = first_seen[dk]
                is_first = (
                    first_info[0] == output_key
                    and first_info[1] == sub_key
                    and first_info[2] == i
                )
                if not is_first:
                    logger.debug(
                        "dedup: %s from %s/%s removed (dup of %s/%s)",
                        dk, output_key, sub_key or "-",
                        first_info[0], first_info[1] or "-",
                    )
                    continue  # 丢弃重复条目

            # 字段名归一化：为保留的条目补充别名字段
            for target, sources in FIELD_ALIASES.items():
                if target in entry:
                    continue  # 已有，无需补充
                for src in sources:
                    if src in entry:
                        entry[target] = entry[src]
                        break

            new_entries.append(entry)

        if sub_key:
            parent[sub_key] = new_entries
        else:
            output[output_key] = new_entries

    logger.info(
        "dedup: kept %d unique entries (dedup_key count)",
        len(first_seen),
    )


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
