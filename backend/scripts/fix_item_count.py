"""补全所有 agent_imports 表的 item_count 字段.

历史上导入的数据中 item_count 字段全部是 1（写入时未计算），
本脚本重新解析 raw_json 并回填 item_count。
"""
import sys
sys.path.insert(0, '.')

import json
from app.database import get_connection


def fix_all_item_count() -> dict:
    """回填所有 agent_imports 的 item_count 字段.

    Returns:
        { "updated": int, "total": int, "errors": int }
    """
    errors = 0
    with get_connection() as conn:
        # 找出 item_count 缺失或不正确的记录
        rows = conn.execute("""
            SELECT id, raw_json, item_count
            FROM agent_imports
            WHERE raw_json IS NOT NULL
        """).fetchall()

        updated = 0
        total = len(rows)
        for r in rows:
            try:
                parsed = json.loads(r['raw_json'])
                if isinstance(parsed, list):
                    cnt = len(parsed)
                elif isinstance(parsed, dict):
                    cnt = 1
                else:
                    cnt = 1
            except Exception as exc:
                errors += 1
                continue

            if r['item_count'] != cnt:
                conn.execute(
                    "UPDATE agent_imports SET item_count=? WHERE id=?",
                    [cnt, r['id']],
                )
                updated += 1

        conn.commit()

    return {"updated": updated, "total": total, "errors": errors}


if __name__ == "__main__":
    result = fix_all_item_count()
    print(f"回填完成: 更新 {result['updated']}/{result['total']} 条，错误 {result['errors']} 条")
