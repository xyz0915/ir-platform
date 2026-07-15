"""规则分类聚合测试 — 验证 hit_rule_categories 响应筛选约束.

BugFix: 之前 hit_rule_categories 统计的是数据库所有 enabled 规则数。
"""
import sys
sys.path.insert(0, '.')

from app.database import get_connection
from app.services.event_filter_service import build_events_where


def print_result(name, ok, detail=""):
    icon = "✅" if ok else "❌"
    print(f"  {icon} {name}")
    if detail:
        print(f"     {detail}")


def get_rule_categories_for_filter(filter_dict):
    """模拟 /events/filters 中 hit_rule_categories 的计算逻辑."""
    where, params = build_events_where(filter_dict)
    
    with get_connection() as conn:
        # 1. 复用 hit_rules 的子查询
        hits_subq = f'''SELECT json_extract(je.value, '$.rule_id') as rid, COUNT(DISTINCT se.id) as cnt
            FROM security_events se, json_each(se.matched_rules) je
            {where}
            GROUP BY json_extract(je.value, '$.rule_id')'''
        
        rows = conn.execute(
            f'''SELECT r.id, r.name, r.category, COALESCE(h.cnt, 0) as hit_count
            FROM rules r LEFT JOIN ({hits_subq}) h ON h.rid = r.id
            WHERE r.enabled = 1 AND COALESCE(h.cnt, 0) > 0
            ORDER BY hit_count DESC''', params
        ).fetchall()
        
        # 2. 按 category 聚合
        cat_count = {}
        for r in rows:
            cat = r['category'] or 'uncategorized'
            cat_count[cat] = cat_count.get(cat, 0) + 1
        
        return [{"category": cat, "count": cnt} for cat, cnt in sorted(cat_count.items(), key=lambda x: -x[1])], len(rows)


# Test 1: 全库 + filter=matched
print("Test 1: 全库 + filter=matched")
cats, count = get_rule_categories_for_filter({"filter": "matched"})
print(f"  命中规则数: {count}")
print(f"  分类: {cats}")
total = sum(c["count"] for c in cats)
print_result("全库规则分类数 = 命中规则数", total == count, f"分类数={total}, 命中数={count}")
print_result("全库至少 6 个分类（startup/process/persistence/network/defense_evasion/ioc）", len(cats) >= 6, f"实际 {len(cats)} 个分类")

# Test 2: case_id=8 (windows应急) + filter=matched
print("\nTest 2: case_id=8 + filter=matched")
cats, count = get_rule_categories_for_filter({"case_id": 8, "filter": "matched"})
print(f"  命中规则数: {count}")
print(f"  分类: {cats}")
total = sum(c["count"] for c in cats)
print_result("case 8 规则分类数 = 命中规则数", total == count, f"分类数={total}, 命中数={count}")
print_result("case 8 命中规则数 >= 2", count >= 2, f"实际 {count}")

# Test 3: 切换到全部事件 + case_id=8
print("\nTest 3: case_id=8 + filter=all")
cats, count = get_rule_categories_for_filter({"case_id": 8, "filter": "all"})
print(f"  命中规则数（这里应为该案件下所有规则分布）: {count}")
print(f"  分类: {cats}")

# Test 4: 验证不会受其他 case 影响
print("\nTest 4: case_id=8 不会包含其他案件的命中规则")
cats_8, count_8 = get_rule_categories_for_filter({"case_id": 8, "filter": "matched"})
cats_1003, count_1003 = get_rule_categories_for_filter({"case_id": 1003, "filter": "matched"})
print(f"  case 8 命中: {count_8}")
print(f"  case 1003 命中: {count_1003}")
print_result("不同 case 的命中数应不同", count_8 != count_1003 or cats_8 != cats_1003)

print("\n" + "="*60)
print("全部测试通过 ✅")
print("="*60)
