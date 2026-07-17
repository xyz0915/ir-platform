"""存量规则匹配回填 — 仅作用于 Windows 应急案例 (hosts 28/29).

等价于 app/api/events.py 的 POST /api/events/batch-match-rules 端点逻辑：
对存量事件重新执行 match_event() 并写回 matched_rules 列。
仅更新 matched_rules，不改变其它列；范围严格限定 host_id IN (28,29)。
"""
import json
from app.database import get_connection
from app.services.rule_matcher import match_event

HOST_IDS = (28, 29)

with get_connection() as conn:
    rows = conn.execute(
        "SELECT id, event_type, severity, evidence, host_id "
        "FROM security_events WHERE host_id IN (?, ?)",
        HOST_IDS,
    ).fetchall()

    processed = 0
    matched = 0
    for r in rows:
        ev = r["evidence"]
        ev = json.loads(ev) if isinstance(ev, str) else (ev or {})
        ed = {
            "id": r["id"],
            "event_type": r["event_type"],
            "severity": r["severity"],
            "evidence": ev,
            "host_id": r["host_id"],
        }
        res = match_event(ed)
        conn.execute(
            "UPDATE security_events SET matched_rules = ? WHERE id = ?",
            (json.dumps(res, ensure_ascii=False), r["id"]),
        )
        processed += 1
        if res:
            matched += 1
    conn.commit()
    print(f"backfill done: processed={processed}, matched={matched}")
