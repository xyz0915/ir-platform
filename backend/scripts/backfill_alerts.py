"""Backfill: 将已有分析结果的规则命中同步到告警中心."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("backfill_alerts")

from app.database import get_connection
from app.models.alert import Alert

def backfill():
    total = 0
    with get_connection() as conn:
        # 1. abnormal_processes（规则命中主表）
        rows = conn.execute("""
            SELECT id, host_id, severity, rule_name, process_name, reason, command_line, process_path, pid
            FROM abnormal_processes
            WHERE severity IN ('critical', 'high')
            ORDER BY id
        """).fetchall()
        logger.info("abnormal_processes to sync: %d", len(rows))

        for r in rows:
            d = dict(r)
            title = d.get("reason") or f"[分析发现] {d.get('process_name', '')}"
            alert_id, is_new = Alert.create_or_aggregate(
                host_id=d["host_id"],
                rule_name=d.get("rule_name", "ANALYSIS-HIGH"),
                severity=d["severity"],
                title=title,
                detail=d.get("command_line", "")[:500],
                source_pid=d.get("pid"),
                source_process=d.get("process_name"),
                source_path=d.get("process_path"),
                rule_label="分析发现-高风险",
            )
            if alert_id:
                total += 1

        # 2. suspicious_connections
        rows = conn.execute("""
            SELECT id, host_id, severity, rule_name, process_name, reason, remote_address, remote_port
            FROM suspicious_connections
            WHERE severity IN ('critical', 'high')
            ORDER BY id
        """).fetchall()
        logger.info("suspicious_connections to sync: %d", len(rows))
        for r in rows:
            d = dict(r)
            title = d.get("reason") or f"[外连告警] {d.get('process_name', '')} → {d.get('remote_address', '')}"
            alert_id, is_new = Alert.create_or_aggregate(
                host_id=d["host_id"],
                rule_name=d.get("rule_name", "CONNECTION-HIGH"),
                severity=d["severity"],
                title=title,
                detail=f"remote: {d.get('remote_address', '')}:{d.get('remote_port', '')}",
                source_process=d.get("process_name"),
                rule_label="分析发现-可疑外连",
            )
            if alert_id:
                total += 1

        # 3. suspicious_startup_items（列: name, command, location, reason, rule_name, severity）
        rows = conn.execute("""
            SELECT id, host_id, severity, rule_name, name as item_name, reason, command as item_path
            FROM suspicious_startup_items
            WHERE severity IN ('critical', 'high')
            ORDER BY id
        """).fetchall()
        logger.info("suspicious_startup_items to sync: %d", len(rows))
        for r in rows:
            d = dict(r)
            title = d.get("reason") or f"[启动项告警] {d.get('item_name', '')}"
            alert_id, is_new = Alert.create_or_aggregate(
                host_id=d["host_id"],
                rule_name=d.get("rule_name", "STARTUP-HIGH"),
                severity=d["severity"],
                title=title,
                detail=d.get("item_path", "")[:500],
                source_process=d.get("item_name"),
                rule_label="分析发现-可疑启动项",
            )
            if alert_id:
                total += 1

        # 4. ioc_hits
        rows = conn.execute("""
            SELECT id, host_id, severity, ioc_type, ioc_value, matched_in, context
            FROM ioc_hits
            WHERE severity IN ('critical', 'high')
            ORDER BY id
        """).fetchall()
        logger.info("ioc_hits to sync: %d", len(rows))
        for r in rows:
            d = dict(r)
            title = d.get("context") or f"[IOC 命中] {d.get('ioc_type', '')}: {d.get('ioc_value', '')}"
            alert_id, is_new = Alert.create_or_aggregate(
                host_id=d["host_id"],
                rule_name=d.get("matched_in", "IOC-HIGH"),
                severity=d["severity"],
                title=title,
                detail=f"type: {d.get('ioc_type', '')}, value: {d.get('ioc_value', '')}",
                rule_label="分析发现-IOC命中",
            )
            if alert_id:
                total += 1

    logger.info("✅ Backfill complete: %d alerts created/aggregated", total)
    return total

if __name__ == "__main__":
    total = backfill()
    print(f"Backfill result: {total} alerts")
