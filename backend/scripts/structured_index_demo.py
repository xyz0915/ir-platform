"""原型：在 agent_imports 上建结构化索引的效果演示.

对比 FTS5 全文检索 vs 结构化字段检索的差异。
"""
import json
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import get_connection


def show_fts_search(keyword: str):
    """FTS5 全文检索（当前 log_search 的方式）。"""
    start = time.time()
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT ai.id, ai.collector_type, ai.host_id, snippet(agent_imports_fts, 0, '<b>', '</b>', '...', 40) as snippet
            FROM agent_imports ai
            JOIN agent_imports_fts fts ON fts.rowid = ai.id
            WHERE agent_imports_fts MATCH ?
            ORDER BY ai.imported_at DESC
            LIMIT 10
            """,
            (keyword,),
        ).fetchall()
    elapsed = (time.time() - start) * 1000
    print(f"\n  🔍 FTS5 搜索 '{keyword}' ({elapsed:.0f}ms):")
    if not rows:
        print(f"    无结果")
        return
    for r in rows:
        snippet = r["snippet"][:80] if r["snippet"] else "(无摘要)"
        print(f"    #{r['id']:>3d}  type={r['collector_type']:12s}  host={r['host_id']}")
        print(f"      匹配片段: {snippet}")


def show_structured_search(table_data: list[dict], field: str, value: str, label: str):
    """模拟结构化字段检索."""
    start = time.time()
    hits = [d for d in table_data if value.lower() in str(d.get(field, "")).lower()]
    elapsed = (time.time() - start) * 1000
    print(f"\n  📊 结构化搜索 '{label}' ({elapsed:.0f}ms):")
    if not hits:
        print(f"    无结果")
        return
    # 按 source 分组统计
    from collections import Counter
    sources = Counter(d.get("_source", "") for d in hits)
    print(f"    命中 {len(hits)} 条, 来源: {dict(sources)}")
    for h in hits[:5]:
        if h["_source"] == "processes":
            print(f"    PID={h.get('pid')}  name={h.get('name')}  cmd={str(h.get('command_line',''))[:40]}")
        elif h["_source"] == "network":
            print(f"    {h.get('protocol')}  {h.get('local_addr')}:{h.get('local_port')} → {h.get('remote_addr')}:{h.get('remote_port')}  [{h.get('state')}]")
        elif h["_source"] == "services":
            print(f"    服务 {h.get('name')}  path={str(h.get('path','') or h.get('binary_path',''))[:40]}")
        elif h["_source"] == "startup":
            print(f"    启动项 {h.get('name')}  cmd={str(h.get('command',''))[:40]}")
        else:
            print(f"    {json.dumps(h, ensure_ascii=False)[:80]}")


def extract_all_structured(host_id: int = 13) -> list[dict]:
    """从 agent_imports.raw_json 中提取所有结构化字段。"""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, collector_type, raw_json FROM agent_imports WHERE host_id=?",
            (host_id,),
        ).fetchall()

    all_items = []
    for r in rows:
        try:
            data = json.loads(r["raw_json"])
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(data, list):
            if isinstance(data, dict):
                data = [data]
            else:
                continue
        for item in data:
            if not isinstance(item, dict):
                continue
            item["_import_id"] = r["id"]
            item["_source"] = r["collector_type"]
            all_items.append(item)

    print(f"\n📦 host {host_id} 的 agent_imports 中共 {len(rows)} 条导入记录")
    print(f"   解析出 {len(all_items)} 条结构化数据项")
    
    from collections import Counter
    sources = Counter(d["_source"] for d in all_items)
    print(f"   来源分布: {dict(sources)}")
    
    return all_items


if __name__ == "__main__":
    print("=" * 65)
    print("  agent_imports 结构化索引效果演示")
    print("=" * 65)

    # 1. 提取所有结构化数据
    all_data = extract_all_structured(host_id=13)
    
    # 2. 对比搜索
    print("\n" + "=" * 65)
    print("  🔬 搜索对比: FTS5 vs 结构化字段检索")
    print("=" * 65)
    
    # 测试搜索1: System (PID 4)
    print("\n━━━━━━━━━━━ 搜索: PID 4 的 System 进程 ━━━━━━━━━━━")
    show_fts_search("System")
    show_structured_search(all_data, "name", "System", "name=System (精确匹配进程名)")
    
    # 测试搜索2: svchost.exe
    print("\n━━━━━━━━━━━ 搜索: svchost.exe ━━━━━━━━━━━")
    show_fts_search("svchost")
    show_structured_search(all_data, "name", "svchost", "name=svchost (进程名字段)")
    
    # 测试搜索3: TCP 连接
    print("\n━━━━━━━━━━━ 搜索: TCP 连接 ━━━━━━━━━━━")
    show_fts_search("TCP")
    show_structured_search(all_data, "protocol", "TCP", "protocol=TCP (协议字段精确匹配)")
    
    # 测试搜索4: 注册表
    print("\n━━━━━━━━━━━ 搜索: CurrentVersion\Run ━━━━━━━━━━━")
    show_fts_search("CurrentVersion")
    show_structured_search(all_data, "key_path", "CurrentVersion", "key_path=CurrentVersion (注册表路径字段)")

    # 3. 综合统计
    print("\n" + "=" * 65)
    print("  📈 结构化索引覆盖的字段维度")
    print("=" * 65)
    
    # 看所有可能的字段
    all_keys = set()
    for d in all_data:
        all_keys.update(d.keys())
    internal = {"_import_id", "_source"}
    data_keys = sorted(all_keys - internal)
    print(f"\n可检索字段 ({len(data_keys)} 个):")
    for k in data_keys:
        # 统计非空率
        non_null = sum(1 for d in all_data if d.get(k) not in (None, "", [], {}))
        pct = non_null / len(all_data) * 100 if all_data else 0
        print(f"  {k:25s}  非空率 {pct:5.1f}% ({non_null}/{len(all_data)})")
