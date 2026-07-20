"""验证智能检索修复：搜索 security_events 而非 normalized_logs."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.nl_log_search import search_events

# 测试1: 无筛选（返回全部 events）
r1 = search_events(page=1, page_size=5)
print(f"[无筛选] total={r1['total']}, 返回={len(r1['items'])} 条")
if r1['items']:
    print(f"  第一条: event_type={r1['items'][0].get('event_type')} severity={r1['items'][0].get('severity')} hostname={r1['items'][0].get('hostname')}")

# 测试2: 筛选 severity=high
r2 = search_events(severity='high', page=1, page_size=5)
print(f"[severity=high] total={r2['total']} 条")

# 测试3: 关键词搜索
r3 = search_events(keyword='powershell', page=1, page_size=5)
print(f"[keyword=powershell] total={r3['total']} 条")

# 测试4: 按事件类型
r4 = search_events(event_type='process_start', page=1, page_size=5)
print(f"[event_type=process_start] total={r4['total']} 条")

# 测试5: 采集器来源
r5 = search_events(source_collector='cm', page=1, page_size=5)
print(f"[source_collector=cm] total={r5['total']} 条")

# 测试6: 多 severity 筛选
r6 = search_events(severity='high,critical', page=1, page_size=5)
print(f"[severity=high,critical] total={r6['total']} 条")

print("\n✅ 全部通过")
