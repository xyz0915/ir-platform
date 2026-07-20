"""test_service_mapper.py — 服务事件字段映射单元测试.

覆盖场景：
1. 新版 Agent：7 字段完整
2. 旧版 Agent：5 字段 + account
3. 最少字段：仅有 name
4. 摘要生成：有 path → 提取 exe 名
5. 摘要生成：无 path → 显示服务名
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.event_normalizer import PersistenceMapper
from app.services.event_enrichment import build_event_summary

mapper = PersistenceMapper()


# ===================================================================
#  Agent 新版数据（path 字段）
# ===================================================================
def test_new_agent_path_field():
    """新版 Agent：path 字段 → evidence.path 正确."""
    raw = {
        "name": "FakeUpdateSvc",
        "display_name": "Windows Update Helper Service",
        "path": r"C:\Windows\Temp\svch0st.exe",
        "start_type": "auto",
        "status": "running",
        "user": "LocalSystem",
        "description": "伪装更新",
        "host_id": 1,
        "event_type": "service_operation",
        "timestamp": "2026-07-20T10:00:00",
    }
    result = mapper.map(raw)
    assert result is not None
    ev = result["evidence"]
    assert ev["name"] == "FakeUpdateSvc"
    assert ev["path"] == r"C:\Windows\Temp\svch0st.exe"
    assert ev["display_name"] == "Windows Update Helper Service"
    assert ev["start_type"] == "auto"
    assert ev["status"] == "running"
    assert ev["user"] == "LocalSystem"
    assert ev["description"] == "伪装更新"


# ===================================================================
#  Agent 新版数据（binary_path 字段 — 实际采集格式）
# ===================================================================
def test_new_agent_binary_path_field():
    """新版 Agent：binary_path → evidence.path 正确映射."""
    raw = {
        "name": "Spooler",
        "display_name": "Print Spooler",
        "status": "running",
        "start_type": "auto",
        "binary_path": r"C:\Windows\System32\spoolsv.exe",
        "account": "LocalSystem",
        "host_id": 1,
        "event_type": "service_operation",
        "timestamp": "2026-07-20T10:00:00",
    }
    result = mapper.map(raw)
    assert result is not None
    ev = result["evidence"]
    assert ev["name"] == "Spooler"
    assert ev["path"] == r"C:\Windows\System32\spoolsv.exe"  # binary_path → path
    assert ev["user"] == "LocalSystem"  # account 兜底生效


# ===================================================================
#  persistence.services 交叉补全
# ===================================================================
def test_persistence_crossref_path():
    """无 path/binary_path，但有 _persist_path（从 persistence.services.command 注入）→ path 取 _persist_path."""
    raw = {
        "name": "AeLookupSvc",
        "display_name": "Application Experience",
        "status": "stopped",
        "start_type": "manual",
        "account": "localSystem",
        "_persist_path": r"\SystemRoot\System32\svchost.exe -k netsvcs",
        "host_id": 1,
        "event_type": "service_operation",
    }
    result = mapper.map(raw)
    assert result is not None
    ev = result["evidence"]
    assert ev["name"] == "AeLookupSvc"
    assert ev["path"] == r"\SystemRoot\System32\svchost.exe -k netsvcs"


def test_persistence_crossref_not_found():
    """无 _persist_path → path 依旧 None."""
    raw = {
        "name": "UnknownSvc",
        "display_name": "Unknown",
        "status": "stopped",
        "start_type": "manual",
        "host_id": 1,
        "event_type": "service_operation",
    }
    result = mapper.map(raw)
    assert result is not None
    ev = result["evidence"]
    assert ev["name"] == "UnknownSvc"
    assert ev["path"] is None


def test_persistence_crossref_existing_path_wins():
    """同时有 path 和 _persist_path → path 优先（原始字段优先）."""
    raw = {
        "name": "TestSvc",
        "path": r"C:\Program Files\test.exe",
        "_persist_path": r"\SystemRoot\System32\test.exe",
        "host_id": 1,
        "event_type": "service_operation",
    }
    result = mapper.map(raw)
    assert result is not None
    ev = result["evidence"]
    assert ev["path"] == r"C:\Program Files\test.exe"  # path 比 _persist_path 优先级高


# ===================================================================
#  旧版 Agent（无 path，用 account 代替 user）
# ===================================================================
def test_old_agent_account_fallback():
    """旧版 Agent：account→user 兼容."""
    raw = {
        "name": "AeLookupSvc",
        "display_name": "Application Experience",
        "status": "stopped",
        "start_type": "manual",
        "account": "localSystem",
        "host_id": 1,
        "event_type": "service_operation",
        "timestamp": "2026-07-20T10:00:00",
    }
    result = mapper.map(raw)
    assert result is not None
    ev = result["evidence"]
    assert ev["name"] == "AeLookupSvc"
    assert ev["path"] is None  # 旧版无 path/binary_path
    assert ev["user"] == "localSystem"  # account 兜底生效


# ===================================================================
#  最少字段
# ===================================================================
def test_minimal_fields():
    """仅有 name → 其他字段 None."""
    raw = {
        "name": "OnlyNameSvc",
        "host_id": 1,
        "event_type": "service_operation",
        "timestamp": "2026-07-20T10:00:00",
    }
    result = mapper.map(raw)
    assert result is not None
    ev = result["evidence"]
    assert ev["name"] == "OnlyNameSvc"
    assert ev["path"] is None
    assert ev["user"] is None


# ===================================================================
#  摘要生成
# ===================================================================
def test_summary_with_path():
    """有 path → 摘要包含 exe 名."""
    event = {
        "event_type": "service_operation",
        "evidence": json.dumps({
            "name": "Spooler",
            "path": r"C:\Windows\System32\spoolsv.exe",
        }),
    }
    summary = build_event_summary(event)
    assert "服务" in summary
    assert "spoolsv.exe" in summary
    assert "Spooler" in summary


def test_summary_without_path():
    """无 path → 摘要只显示服务名."""
    event = {
        "event_type": "service_operation",
        "evidence": json.dumps({
            "name": "TestSvc",
        }),
    }
    summary = build_event_summary(event)
    assert "服务 TestSvc" in summary


def test_summary_empty_evidence():
    """evidence 为空字典 → 不会崩溃."""
    event = {
        "event_type": "service_operation",
        "evidence": json.dumps({}),
    }
    summary = build_event_summary(event)
    assert summary


# ===================================================================
#  持久化相关（不改动）
# ===================================================================
def test_persistence_register_unchanged():
    """persistence_register 摘要保持原样."""
    event = {
        "event_type": "persistence_register",
        "evidence": json.dumps({"name": "RunOnce"}),
    }
    summary = build_event_summary(event)
    assert "注册持久化项" in summary
    assert "RunOnce" in summary


if __name__ == "__main__":
    # 手动运行
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"  ✅ {name}")
