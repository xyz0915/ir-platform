"""Backfill: 将已有 Agent JSON 中的日志范式化入库."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import json
import logging
from pathlib import Path
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("backfill_logs")

from app.database import get_connection
from app.analysis.log_normalizer import LogNormalizer
from app.models.normalized_log import NormalizedLog


def backfill():
    with get_connection() as conn:
        hosts = conn.execute(
            "SELECT id, hostname, raw_json_path FROM hosts WHERE raw_json_path IS NOT NULL AND raw_json_path != ''"
        ).fetchall()

    total = 0
    host_count = 0
    for host in hosts:
        h_id, hostname, json_path = host["id"], host["hostname"], host["raw_json_path"]
        p = Path(json_path)
        if not p.exists():
            logger.warning("JSON not found for host %d: %s", h_id, json_path)
            continue
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            logs = data.get("logs", {})
            if not logs:
                continue
            normalized = LogNormalizer.normalize_host_logs(logs, h_id, hostname)
            if normalized:
                count = NormalizedLog.batch_create(normalized)
                total += count
                host_count += 1
                logger.info("Host %s (%d): %d log entries", hostname, h_id, count)
        except Exception as e:
            logger.error("Failed to process host %d: %s", h_id, e)

    logger.info("✅ Backfill complete: %d hosts, %d log entries", host_count, total)
    return total


if __name__ == "__main__":
    total = backfill()
    print(f"Backfill result: {total} log entries")
