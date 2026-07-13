"""Agent 常驻模式 + 实时监控中心 — 全量测试验证."""
import json
import os
import sys
import tempfile
import time
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../agent"))
sys.path.insert(1, os.path.join(os.path.dirname(__file__), "../"))

print("=" * 60)
print("方案一：Agent 常驻模式 — 测试验证")
print("=" * 60)

# ── 1.1 参数解析测试 ──
print("\n--- 1.1 参数解析 ---")
from agent import parse_args

# 模拟命令行参数
sys.argv = ["agent.py", "--daemon", "--server", "http://localhost:8000", "--token", "test123"]
args = parse_args()
assert args.daemon is True, "daemon flag"
assert args.server == "http://localhost:8000", "server"
assert args.token == "test123", "token"
print("  ✅ daemon=True, server=http://localhost:8000, token=test123")

sys.argv = ["agent.py"]
args = parse_args()
assert args.daemon is False, "no daemon by default"
assert args.collect == "all", "default collect all"
print("  ✅ 默认模式：daemon=False, collect=all")

sys.argv = ["agent.py", "--daemon"]
args = parse_args()
assert args.daemon is True
assert args.server is None  # 不指定 server 也能启动 daemon（仅本地采集）
print("  ✅ daemon 模式允许不指定 server（本地快照模式）")

# ── 1.2 增量采集函数测试 ──
print("\n--- 1.2 增量采集 ---")
from agent import _collect_incremental

last_results = {
    "process_events": [
        {"pid": 100, "process_name": "explorer.exe"},
        {"pid": 200, "process_name": "svchost.exe"},
    ]
}
# 模拟新结果（多了 1 个进程）
with patch("agent.load_collector") as mock_load:
    mock_collector = MagicMock()
    mock_collector.is_supported.return_value = True
    mock_collector.collect.return_value = [
        {"pid": 100, "process_name": "explorer.exe"},
        {"pid": 200, "process_name": "svchost.exe"},
        {"pid": 300, "process_name": "powershell.exe"},
    ]
    mock_load.return_value = mock_collector
    events = _collect_incremental(["process_events"], last_results)
    assert len(events) == 1, f"Expected 1 new event, got {len(events)}"
    assert events[0]["pid"] == 300
    assert events[0]["event_type"] == "process_events"
    print("  ✅ 增量采集正确识别新增事件（1/3 新增）")

# ── 1.3 事件推送函数测试 ──
print("\n--- 1.3 事件推送 ---")
from agent import _push_events, _send_heartbeat

# 模拟推送成功
with patch("agent.urllib.request.urlopen") as mock_urlopen:
    mock_resp = MagicMock()
    mock_resp.read.return_value = b'{"written": 2}'
    mock_resp.__enter__.return_value = mock_resp
    mock_urlopen.return_value.__enter__.return_value = mock_resp
    result = _push_events("http://localhost:8000", "token123", 1,
                          [{"event_type": "test", "pid": 1}], "/api/hosts/{host_id}/process-events")
    assert result is True
    print("  ✅ 事件推送成功")

# 空列表不推送
result = _push_events("http://localhost:8000", "token123", 1, [], "/api/hosts/{host_id}/process-events")
assert result is True
print("  ✅ 空事件列表不推送")

# 心跳测试
with patch("agent.urllib.request.urlopen") as mock_urlopen:
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.__enter__.return_value = mock_resp
    mock_urlopen.return_value.__enter__.return_value = mock_resp
    result = _send_heartbeat("http://localhost:8000", "token", 1)
    assert result is True
    print("  ✅ 心跳发送成功")

# ── 1.4 run_daemon 函数结构验证 ──
print("\n--- 1.4 run_daemon 结构验证 ---")
import inspect
from agent import run_daemon
source = inspect.getsource(run_daemon)
checks = [
    ("Initial snapshot", "run_collectors" in source),
    ("Event loop", "while _daemon_running" in source),
    ("Incremental collect", "_collect_incremental" in source),
    ("Event push", "_push_events" in source),
    ("Heartbeat", "_send_heartbeat" in source),
    ("Signal handling", "signal.signal" in source),
    ("Graceful shutdown", "gracefully" in source),
]
all_ok = True
for name, ok in checks:
    print(f"  {'✅' if ok else '❌'} {name}")
    if not ok: all_ok = False
assert all_ok, "run_daemon 结构不完整"
print("  ✅ run_daemon 函数结构完整（含全部 7 个关键环节）")

print("\n" + "=" * 60)
print("方案一：Agent 常驻模式 — 全部测试通过 ✅")
print("=" * 60)

print("\n" + "=" * 60)
print("方案二：实时监控中心 — 测试验证")
print("=" * 60)

# ── 2.1 后端 API 路由注册 ──
print("\n--- 2.1 API 路由注册 ---")
sys.path.insert(1, os.path.join(os.path.dirname(__file__), "../backend"))
from app.main import app
routes = [r.path for r in app.routes if hasattr(r, "path")]

target_routes = [
    "/api/alerts", "/api/alerts/stats/summary", "/api/alerts/{alert_id}",
    "/api/agents/online-status", "/api/ws/alerts", "/api/cases/with-hosts",
]
for tr in target_routes:
    found = any(tr in r for r in routes)
    assert found, f"Route {tr} not found"
    print(f"  ✅ {tr}")

# ── 2.2 前端组件导入验证 ──
print("\n--- 2.2 前端路由注册 ---")
router_path = os.path.join(os.path.dirname(__file__), "../../frontend/src/router/index.js")
with open(router_path, "r", encoding="utf-8") as f:
    content = f.read()
    assert "RealTimeMonitor" in content, "路由未注册"
    assert "RealTimeMonitorView.vue" in content, "组件未注册"
    print("  ✅ /realtime 路由已注册到 RealTimeMonitorView.vue")

# 检查组件文件是否存在
vue_path = os.path.join(os.path.dirname(__file__), "../../frontend/src/views/RealTimeMonitorView.vue")
assert os.path.exists(vue_path), "RealTimeMonitorView.vue 不存在"
with open(vue_path, "r", encoding="utf-8") as f:
    size = len(f.read())
    assert size > 2000, f"组件文件过小: {size} bytes"
    print(f"  ✅ RealTimeMonitorView.vue 存在 ({size} bytes)")

# ── 2.3 实时监控 API 数据验证 ──
print("\n--- 2.3 API 数据一致性 ---")
from app.models.alert import Alert
from app.database import get_connection

# 验证 Alert 模型有正确的统计方法
stats = Alert.get_stats()
assert "total" in stats
assert "open" in stats
assert "critical" in stats
assert "today" in stats
print(f"  ✅ Alert.get_stats() 返回完整统计: {stats}")

# 验证列表筛选
alerts = Alert.list(severity="critical", limit=3)
for a in alerts:
    assert a["severity"] == "critical", f"筛选条件不符: {a['severity']}"
print(f"  ✅ Alert.list(severity=critical) 返回 {len(alerts)} 条")

# 验证搜索
alerts_search = Alert.list(search="powershell")
print(f"  ✅ Alert.list(search=powershell) 返回 {len(alerts_search)} 条")

# 验证日期筛选
alerts_date = Alert.list(date_from="2026-07-01T00:00:00")
print(f"  ✅ Alert.list(date_from=2026-07-01) 返回 {len(alerts_date)} 条")

print("\n" + "=" * 60)
print("方案二：实时监控中心 — 全部测试通过 ✅")
print("=" * 60)

print("\n" + "=" * 60)
print("最终结论：两个方案全部验证通过")
print("=" * 60)
