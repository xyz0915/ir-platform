"""数据迁移脚本：将 agent_imports 表中的历史原始数据归一化为 SecurityEvent.

读取 agent_imports 表中 event_created=0 的记录，解析 raw_json 数组，
为每条记录添加 event_type（基于 collector_type），
以及其他必填字段（host_id, source_collector, severity, timestamp），
然后调用 event_normalizer.normalize_batch + bulk_insert 写入 security_events 表。

Usage:
    cd backend
    python scripts/migrate_agent_imports_to_events.py
"""

import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# 将 backend 目录加入 sys.path，使得 app 包可导入
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("migrate_agent_imports")

# ---------------------------------------------------------------------------
#  collector_type → event_type 映射
# ---------------------------------------------------------------------------
COLLECTOR_TO_EVENT_TYPE: dict[str, str] = {
    "processes": "process_start",
    "network_connections": "network_outbound",
    "registry_keys": "registry_modify",
    "file_hashes": "file_create",
    "persistence_items": "persistence_register",
    "startup_items": "persistence_register",
    "wmi_subscriptions": "wmi_subscribe",
    "services": "service_operation",
    "users": "user_login",
    "network_interfaces": "network_listen",
}

# ---------------------------------------------------------------------------
#  字段名映射：osquery 原始字段名 → 映射器期望的字段名
# ---------------------------------------------------------------------------
FIELD_MAPPINGS: dict[str, dict[str, str]] = {
    "processes": {
        "name": "process_name",
        "path": "process_path",
    },
    "network_connections": {
        "local_addr": "local_address",
        "remote_addr": "remote_address",
    },
    "users": {
        "username": "user_name",
    },
}

# ---------------------------------------------------------------------------
#  时间戳字段：各 collector_type 的原始数据中哪个字段可作 timestamp
# ---------------------------------------------------------------------------
TIMESTAMP_FIELDS: dict[str, str] = {
    "processes": "start_time",
    "network_connections": "collected_at",
    "registry_keys": "collected_at",
    "file_hashes": "collected_at",
    "startup_items": "",          # 无原生时间戳 → 使用 imported_at
    "wmi_subscriptions": "collected_at",
    "services": "",               # 无原生时间戳 → 使用 imported_at
    "users": "last_logon",
}


def _apply_field_mapping(item: dict, collector_type: str) -> dict:
    """将 osquery 原始字段名映射为映射器期望的字段名（原地修改并返回）. """
    mapping = FIELD_MAPPINGS.get(collector_type, {})
    for old_key, new_key in mapping.items():
        if old_key in item and new_key not in item:
            item[new_key] = item.pop(old_key)
    return item


def _resolve_timestamp(item: dict, collector_type: str, imported_at: str) -> str:
    """从 item 中解析时间戳，兜底使用 imported_at. """
    ts_field = TIMESTAMP_FIELDS.get(collector_type, "")
    if ts_field:
        ts = item.get(ts_field)
        if ts:
            return ts
    # 兜底
    return imported_at


def _migrate_batch(rows: list[dict]) -> dict:
    """处理一批 agent_imports 记录.

    Returns:
        {
            "processed": 处理的 agent_imports 数,
            "skipped_already": 跳过（已生成事件）数,
            "normalized_failures": 归一化失败返回 None 数,
            "inserted": 成功写入 security_events 数,
        }
    """
    # 延迟导入，避免脚本 import 时 app 依赖未就绪
    from app.database import get_connection
    from app.services.event_normalizer import normalize_batch, bulk_insert

    processed = 0
    skipped_already = 0
    normalized_failures = 0
    inserted = 0

    for row in rows:
        # 跳过已生成事件的记录
        if row.get("event_created", 0) == 1:
            skipped_already += 1
            continue

        collector_type = row["collector_type"]
        collector_name = row.get("collector_name", "")
        host_id = row["host_id"]
        import_id = row["id"]
        imported_at = row.get("imported_at", datetime.now(timezone.utc).isoformat())

        event_type = COLLECTOR_TO_EVENT_TYPE.get(collector_type)
        if event_type is None:
            logger.warning(
                "import_id=%d collector_type=%s 无对应的 event_type 映射，跳过",
                import_id, collector_type,
            )
            normalized_failures += 1
            continue

        # 解析 raw_json
        try:
            raw_items = json.loads(row["raw_json"])
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning("import_id=%d raw_json 解析失败: %s", import_id, exc)
            normalized_failures += 1
            continue

        if not isinstance(raw_items, list):
            logger.warning("import_id=%d raw_json 不是数组，跳过", import_id)
            normalized_failures += 1
            continue

        # 为每条 item 添加必填字段
        normalized_inputs: list[dict] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue

            # 字段名映射
            item = _apply_field_mapping(item, collector_type)

            # 时间戳
            timestamp = _resolve_timestamp(item, collector_type, imported_at)

            enriched = {
                "event_type": event_type,
                "host_id": host_id,
                "source_collector": collector_name,
                "severity": "medium",
                "timestamp": timestamp,
                **item,  # 保留所有原始字段（映射后的）
            }
            normalized_inputs.append(enriched)

        if not normalized_inputs:
            normalized_failures += 1
            continue

        # 归一化
        events = normalize_batch(normalized_inputs)
        fail_count = len(normalized_inputs) - len(events)
        normalized_failures += fail_count

        if events:
            # 批量写入
            ins, skp = bulk_insert(events)
            inserted += ins

        # 更新 agent_imports 标记
        event_ids = [e.id for e in events] if events else []
        # 写入 event_id（取第一个事件的 ID 做关联标记；多条则存 JSON 数组）
        event_id_str = json.dumps(event_ids, ensure_ascii=False) if len(event_ids) > 1 else (event_ids[0] if event_ids else None)
        with get_connection() as conn:
            conn.execute(
                "UPDATE agent_imports SET event_created = 1, event_id = ? WHERE id = ?",
                (event_id_str, import_id),
            )

        processed += 1

    return {
        "processed": processed,
        "skipped_already": skipped_already,
        "normalized_failures": normalized_failures,
        "inserted": inserted,
    }


def main():
    """主入口：读取 agent_imports → 批量迁移 → 输出统计. """
    from app.database import get_connection

    start_ts = time.time()

    # 读取所有 agent_imports 行（按 id 升序，保持可复现）
    with get_connection() as conn:
        cursor = conn.execute(
            "SELECT id, host_id, collector_type, collector_name, "
            "       raw_json, item_count, imported_at, event_id, event_created "
            "FROM agent_imports ORDER BY id"
        )
        all_rows = [dict(r) for r in cursor.fetchall()]

    total = len(all_rows)
    logger.info("共读取 %d 条 agent_imports 记录", total)

    if total == 0:
        logger.info("没有需要处理的记录，退出")
        return

    # 迁移全部数据
    result = _migrate_batch(all_rows)

    elapsed = time.time() - start_ts

    # 查询迁移后的 security_events 总数
    with get_connection() as conn:
        se_count = conn.execute("SELECT COUNT(*) as c FROM security_events").fetchone()["c"]
        # 检查是否有 attack_stage 字段不为空的记录
        with_stage = conn.execute(
            "SELECT COUNT(*) as c FROM security_events WHERE attack_stage IS NOT NULL AND attack_stage != ''"
        ).fetchone()["c"]

    # ── 输出报告 ──
    logger.info("=" * 60)
    logger.info("迁移完成！耗时: %.2f 秒", elapsed)
    logger.info("-" * 60)
    logger.info("处理的 agent_imports 总数:    %d", total)
    logger.info("跳过（已生成事件）:           %d", result["skipped_already"])
    logger.info("实际处理的记录数:             %d", result["processed"])
    logger.info("归一化失败（返回 None）数:    %d", result["normalized_failures"])
    logger.info("成功写入 security_events 数:  %d", result["inserted"])
    logger.info("-" * 60)
    logger.info("security_events 表最终行数:   %d", se_count)
    logger.info("有 attack_stage 的记录数:     %d", with_stage)
    logger.info("=" * 60)

    # ── 报告摘要（JSON 格式，便于解析） ──
    report = {
        "total_agent_imports": total,
        "skipped_already_created": result["skipped_already"],
        "processed": result["processed"],
        "normalized_failures": result["normalized_failures"],
        "inserted_into_security_events": result["inserted"],
        "security_events_final_count": se_count,
        "with_attack_stage": with_stage,
        "elapsed_seconds": round(elapsed, 2),
    }
    print()
    print(json.dumps(report, ensure_ascii=False, indent=2))

    # 如果有失败记录，给出提示
    if result["normalized_failures"] > 0:
        logger.warning("有 %d 条记录归一化失败，详情请看上方 WARNING 日志", result["normalized_failures"])


if __name__ == "__main__":
    main()
