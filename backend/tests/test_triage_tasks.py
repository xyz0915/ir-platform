"""动态取证 TriageTask 模型层缺陷修复测试（审计 D-0 / D-4）.

覆盖：
- D-0：get_pending 返回最新 status='running'（不再返回 UPDATE 前旧值）
- D-4：recover_stale 回收超时 running 任务（标记 failed + error 说明）；新鲜任务不回收

测试隔离：重定向 settings.DB_PATH 到临时库并 init_db()，不污染运行库。
"""

import os
import tempfile

import app.config as _cfg
import app.database as _db

# 在导入任何模型前重定向数据库路径，使用临时库
_TMP_DB = os.path.join(tempfile.gettempdir(), "ir_test_triage_model.db")
if os.path.exists(_TMP_DB):
    os.remove(_TMP_DB)
_cfg.settings.DB_PATH = _TMP_DB
_db.init_db()

from app.database import get_connection  # noqa: E402
from app.models.triage_task import TriageTask  # noqa: E402


def _seed_host() -> int:
    with get_connection() as conn:
        # 清空相关表：规避 case_number UNIQUE 约束与跨用例状态污染
        for t in ("triage_tasks", "hosts", "cases"):
            conn.execute(f"DELETE FROM {t}")
        cur = conn.execute(
            "INSERT INTO cases (name, case_number, description, status, priority) "
            "VALUES ('TRIAGE-TEST', 'T-001', '测试案件', 'open', 'low')"
        )
        case_id = int(cur.lastrowid)
        cur = conn.execute(
            "INSERT INTO hosts (case_id, hostname, ip_address, os_type, status, collection_time) "
            "VALUES (?, 'triage-test-host', '10.0.0.9', 'linux', 'imported', '2026-08-12 08:00:00')",
            [case_id],
        )
        return int(cur.lastrowid)


def _set_running_ago(task_id: int, minutes_ago: int) -> None:
    """直接把任务置 running 并把 started_at 回拨 N 分钟（模拟 daemon 拉取后失联）."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE triage_tasks SET status='running', "
            "started_at=datetime('now', ?) WHERE id=?",
            [f"-{minutes_ago} minutes", task_id],
        )


def test_get_pending_returns_latest_running_status():
    """D-0：get_pending 返回的任务 status 应为 'running'（与实际落库一致）."""
    host_id = _seed_host()
    task_id = TriageTask.create(host_id, ["file_hashes"])
    task = TriageTask.get_pending(host_id)
    assert task is not None
    assert task["id"] == task_id
    assert task["status"] == "running"          # 接口返回最新状态
    assert task["scope"] == ["file_hashes"]
    # 落库状态一致
    with get_connection() as conn:
        db_status = conn.execute(
            "SELECT status, started_at FROM triage_tasks WHERE id=?", [task_id]
        ).fetchone()
    assert db_status["status"] == "running"
    assert db_status["started_at"] is not None  # started_at 已写入
    # 再次轮询：无 pending
    assert TriageTask.get_pending(host_id) is None


def test_recover_stale_marks_timeout_failed():
    """D-4：超过超时阈值的 running 任务被回收为 failed（error 含 timeout）."""
    host_id = _seed_host()
    task_id = TriageTask.create(host_id, ["network"])
    _set_running_ago(task_id, minutes_ago=20)  # 20 分钟前拉取，远超 10 分钟阈值

    recovered = TriageTask.recover_stale(timeout_minutes=10)
    assert recovered >= 1

    with get_connection() as conn:
        row = conn.execute(
            "SELECT status, error, finished_at FROM triage_tasks WHERE id=?", [task_id]
        ).fetchone()
    assert row["status"] == "failed"
    assert "timeout" in (row["error"] or "")
    assert row["finished_at"] is not None


def test_recover_stale_skips_fresh_running():
    """D-4 反向：刚拉取（started_at 为当前）的 running 任务不被误回收."""
    host_id = _seed_host()
    task_id = TriageTask.create(host_id, ["process_subtree"])
    TriageTask.get_pending(host_id)  # 置 running，started_at=now

    recovered = TriageTask.recover_stale(timeout_minutes=10)
    assert recovered == 0

    with get_connection() as conn:
        row = conn.execute(
            "SELECT status FROM triage_tasks WHERE id=?", [task_id]
        ).fetchone()
    assert row["status"] == "running"


def test_recover_stale_pending_untouched():
    """D-4：pending 任务不受回收影响（只处理 running）."""
    host_id = _seed_host()
    TriageTask.create(host_id, ["file_hashes"])  # 保持 pending
    recovered = TriageTask.recover_stale(timeout_minutes=10)
    assert recovered == 0
