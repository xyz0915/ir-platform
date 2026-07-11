"""验证审计日志和 Token 统计功能是否正常.

测试步骤:
1. 直接查询数据库确认数据存在
2. 通过 API 端点验证返回格式正确
3. 验证字段映射与前端期望一致
"""

import json
import os
import sqlite3
import sys
from datetime import datetime
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

BASE_URL = "http://localhost:8000"

# ── 工具函数 ────────────────────────────────────────────


def ok(msg: str) -> None:
    print(f"  ✓ {msg}")


def fail(msg: str) -> None:
    print(f"  ✗ {msg}")
    sys.exit(1)


# ── Step 1: 直接查询数据库 ──────────────────────────────

print("=" * 60)
print("Step 1: 数据库直查")
print("=" * 60)

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "ir_platform.db")
conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

# 1a: 检查表是否存在
tables = conn.execute(
    "SELECT name FROM sqlite_master WHERE type='table' AND name='ai_audit_log'"
).fetchall()
if tables:
    ok(f"ai_audit_log 表存在")
else:
    fail("ai_audit_log 表不存在")

# 1b: 检查数据条数
total = conn.execute("SELECT COUNT(*) as cnt FROM ai_audit_log").fetchone()["cnt"]
if total > 0:
    ok(f"ai_audit_log 共有 {total} 条记录")
else:
    fail("ai_audit_log 表中无数据")

# 1c: 检查最近记录的字段完整性
recent = conn.execute(
    "SELECT * FROM ai_audit_log ORDER BY id DESC LIMIT 1"
).fetchone()
recent_dict = dict(recent)
required_fields = [
    "id", "host_id", "host_name", "model_name", "status",
    "prompt_tokens", "completion_tokens", "total_tokens",
    "latency_ms", "created_at",
]
missing = [f for f in required_fields if recent_dict.get(f) is None]
if not missing:
    ok(f"最近记录字段完整: id={recent_dict['id']}, host={recent_dict['host_name']}, "
       f"tokens=({recent_dict['prompt_tokens']},{recent_dict['completion_tokens']},{recent_dict['total_tokens']})")
else:
    fail(f"最近记录缺少字段: {missing}")

# 1d: 检查 Token 统计聚合
stats = conn.execute("""
    SELECT
        DATE(created_at) as date,
        SUM(total_tokens) as total_tokens,
        COUNT(*) as count
    FROM ai_audit_log
    WHERE created_at >= date('now', '-30 days')
    GROUP BY DATE(created_at)
    ORDER BY date ASC
""").fetchall()
stats_list = [dict(r) for r in stats]
if stats_list:
    ok(f"Token 统计聚合正常，共 {len(stats_list)} 天有数据")
else:
    fail("Token 统计聚合无数据")

conn.close()

# ── Step 2: API 端点验证 ─────────────────────────────────

print()
print("=" * 60)
print("Step 2: API 端点验证")
print("=" * 60)

# 登录获取 token
try:
    req = Request(
        f"{BASE_URL}/api/auth/login",
        data=json.dumps({"username": "admin", "password": "admin123"}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    resp = urlopen(req, timeout=10)
    login_data = json.loads(resp.read())
    token = login_data.get("data", {}).get("token", "")
    if token:
        ok(f"登录成功，获取到 token")
    else:
        fail("登录返回无 token")
except Exception as e:
    fail(f"登录失败: {e}")

headers = {"Authorization": f"Bearer {token}"}

# 2a: 审计日志列表端点
try:
    req = Request(f"{BASE_URL}/api/ai/audit-logs?page=1&page_size=5", headers=headers)
    resp = urlopen(req, timeout=10)
    data = json.loads(resp.read())
    if data.get("code") == 0:
        items = data.get("data", {}).get("items", [])
        total = data.get("data", {}).get("total", 0)
        ok(f"GET /api/ai/audit-logs: code=0, total={total}, items={len(items)}")
        if items:
            # 验证前端需要的字段存在
            first = items[0]
            frontend_fields = ["id", "host_name", "model_name", "status", "total_tokens", "created_at", "latency_ms"]
            missing_f = [f for f in frontend_fields if f not in first]
            if not missing_f:
                ok(f"审计日志响应字段与前端预期一致: {frontend_fields}")
            else:
                fail(f"审计日志响应缺少字段: {missing_f}")
    else:
        fail(f"审计日志端点返回错误: code={data.get('code')}")
except Exception as e:
    fail(f"审计日志端点失败: {e}")

# 2b: Token 统计端点（时间序列）
try:
    req = Request(f"{BASE_URL}/api/ai/stats/tokens?days=30", headers=headers)
    resp = urlopen(req, timeout=10)
    data = json.loads(resp.read())
    if data.get("code") == 0:
        items = data.get("data", {}).get("items", [])
        ok(f"GET /api/ai/stats/tokens: code=0, items={len(items)}")
        if items:
            first = items[0]
            ts_fields = ["date", "total_tokens", "count"]
            missing_ts = [f for f in ts_fields if f not in first]
            if not missing_ts:
                ok(f"Token 统计时间序列字段完整: {ts_fields}")
            else:
                fail(f"Token 统计缺少字段: {missing_ts}")
    else:
        fail(f"Token 统计端点返回错误: code={data.get('code')}")
except Exception as e:
    fail(f"Token 统计端点失败: {e}")

# 2c: Token 汇总端点
try:
    req = Request(f"{BASE_URL}/api/ai/stats/summary", headers=headers)
    resp = urlopen(req, timeout=10)
    data = json.loads(resp.read())
    if data.get("code") == 0:
        summary = data.get("data", {})
        summary_fields = ["total_tokens", "total_calls", "avg_latency_ms", "success_rate", "this_month_tokens", "this_month_calls"]
        missing_s = [f for f in summary_fields if f not in summary]
        if not missing_s:
            ok(f"GET /api/ai/stats/summary: code=0, "
               f"total_tokens={summary['total_tokens']}, "
               f"total_calls={summary['total_calls']}, "
               f"this_month_tokens={summary['this_month_tokens']}")
        else:
            fail(f"汇总端点缺少字段: {missing_s}")
    else:
        fail(f"汇总端点返回错误: code={data.get('code')}")
except Exception as e:
    fail(f"汇总端点失败: {e}")

# ── Step 3: 写入回测 ─────────────────────────────────────

print()
print("=" * 60)
print("Step 3: 写入回测（插入 → 查询验证）")
print("=" * 60)

try:
    # 直接插入一条测试记录
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    test_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    cursor = conn.execute(
        """
        INSERT INTO ai_audit_log
        (host_id, host_name, model_name, status,
         prompt_tokens, completion_tokens, total_tokens, latency_ms, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (9999, "TEST-HOST-VERIFY", "test-model", "success", 100, 50, 150, 1000, test_time),
    )
    test_id = cursor.lastrowid
    conn.commit()
    ok(f"测试记录插入: id={test_id}")

    # 查询验证
    row = conn.execute("SELECT * FROM ai_audit_log WHERE id = ?", (test_id,)).fetchone()
    if row:
        d = dict(row)
        ok(f"查询验证: host={d['host_name']}, tokens={d['total_tokens']}, status={d['status']}")

    # 清理测试记录
    conn.execute("DELETE FROM ai_audit_log WHERE id = ?", (test_id,))
    conn.commit()
    ok("测试记录已清理")
    conn.close()
except Exception as e:
    fail(f"写入回测失败: {e}")

# ── 总结 ─────────────────────────────────────────────────

print()
print("=" * 60)
print("✅ 所有验证通过！后端数据读写和 API 端点正常工作。")
print("=" * 60)
print()
print("前端修复清单（AiView.vue）:")
print("  1. loadStats() 改为调用 getAiTokenSummary() 获取汇总数据")
print("  2. loadChartData() 改为调用 getAiTokenStats() 获取时间序列")
print("  3. 审计表格列 prop='tokens_used' → prop='total_tokens'")
print("  4. 审计详情 tokens_used → total_tokens")
print("  5. buildChartOption 兼容后端 count 字段")
print()
print("后端增强:")
print("  1. AiAuditLog.create() 增加详细日志")
print("  2. AuditService.log_call() 增加 ENTER/DONE 追踪日志")
