#!/usr/bin/env python3
"""存量事件规则匹配回填脚本 — 支持分页处理与条件筛选.

对 security_events 表中已存在的事件执行规则匹配,
将命中的规则写入 matched_rules 字段, 每批 500 条分页处理以避免长时间事务.

用法:
    python scripts/backfill_matched_rules.py [--case-id N] [--host-id N] [--limit 5000]

可选参数:
    --case-id INT    限定只处理指定案件下的主机事件
    --host-id INT    限定只处理指定主机的事件
    --limit INT      最多处理多少条事件（默认 5000，设为 0 表示不限制）
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

# 添加项目根目录到 sys.path
_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("backfill")

# ── 每批处理条数 ──
PAGE_SIZE = 500


def build_where(case_id: int | None, host_id: int | None) -> tuple[str, list]:
    """根据筛选条件构建 WHERE 子句与参数列表."""
    conditions: list[str] = ["1=1"]
    sql_params: list = []

    if case_id is not None:
        conditions.append(
            "se.host_id IN (SELECT id FROM hosts WHERE case_id=?)"
        )
        sql_params.append(case_id)
    if host_id is not None:
        conditions.append("se.host_id = ?")
        sql_params.append(host_id)

    return " AND ".join(conditions), sql_params


def main():
    parser = argparse.ArgumentParser(description="存量事件规则匹配回填")
    parser.add_argument("--case-id", type=int, default=None, help="限定案件 ID")
    parser.add_argument("--host-id", type=int, default=None, help="限定主机 ID")
    parser.add_argument(
        "--limit", type=int, default=5000,
        help="最大处理条数（默认 5000，0 表示不限制）",
    )
    args = parser.parse_args()

    # 惰性导入，确保路径已设置
    from app.database import get_connection
    from app.services.rule_matcher import match_event

    where_clause, sql_params = build_where(args.case_id, args.host_id)

    start_ts = time.time()
    processed = 0
    matched_total = 0
    page = 0

    logger.info(
        "开始存量匹配回填（case_id=%s, host_id=%s, limit=%s, page_size=%d）...",
        args.case_id, args.host_id,
        args.limit if args.limit else "unlimited",
        PAGE_SIZE,
    )

    with get_connection() as conn:
        # 先获取总数，方便显示进度
        count_row = conn.execute(
            f"SELECT COUNT(*) FROM security_events se WHERE {where_clause}",
            sql_params,
        ).fetchone()
        total_available = count_row[0] if count_row else 0
        effective_limit = args.limit if args.limit else total_available
        logger.info("共有 %d 条待处理事件，本次最多处理 %d 条", total_available, effective_limit)

        while True:
            offset = page * PAGE_SIZE
            if args.limit and offset >= args.limit:
                logger.info("已达 limit 上限 (%d)，停止分页", args.limit)
                break

            rows = conn.execute(
                f"""
                SELECT se.id, se.event_type, se.severity, se.evidence, se.host_id
                FROM security_events se
                WHERE {where_clause}
                ORDER BY se.timestamp DESC
                LIMIT ? OFFSET ?
                """,
                sql_params + [PAGE_SIZE, offset],
            ).fetchall()

            if not rows:
                logger.info("无更多事件，分页结束")
                break

            batch_matched = 0
            for row in rows:
                if args.limit and processed >= args.limit:
                    break
                try:
                    event_dict = {
                        "id": row["id"],
                        "event_type": row["event_type"],
                        "severity": row["severity"],
                        "evidence": (
                            json.loads(row["evidence"])
                            if isinstance(row["evidence"], str)
                            else row["evidence"]
                        ),
                        "host_id": row["host_id"],
                    }
                    matched = match_event(event_dict)
                    matched_json = json.dumps(matched, ensure_ascii=False)
                    conn.execute(
                        "UPDATE security_events SET matched_rules = ? WHERE id = ?",
                        (matched_json, row["id"]),
                    )
                    if matched:
                        batch_matched += 1
                        matched_total += 1
                    processed += 1
                except Exception as exc:
                    logger.warning("回填异常 id=%s: %s", row["id"], exc)
                    processed += 1

            conn.commit()
            page += 1

            logger.info(
                "第 %d 批完成: processed=%d, matched_this_batch=%d, total_processed=%d/%d",
                page, len(rows), batch_matched, processed, min(effective_limit, total_available),
            )

            if args.limit and processed >= args.limit:
                break

        # 最终提交
        conn.commit()

    elapsed_ms = int((time.time() - start_ts) * 1000)
    logger.info(
        "回填完成: processed=%d, matched=%d, elapsed=%dms",
        processed, matched_total, elapsed_ms,
    )


if __name__ == "__main__":
    main()
