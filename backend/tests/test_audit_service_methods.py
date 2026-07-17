"""回归测试：AuditService 新增的 3 个静态方法 (log_call / query_logs / get_detail).

测试策略：
    - 使用独立临时 SQLite 库（tempfile.TemporaryDirectory），绝不碰生产库。
    - 每个测试方法独立调用 setup_method 初始化临时库，保证测试隔离。
    - 不依赖 log_call 返回值，通过直接查库验证落库正确性。

受测方法：
    - AuditService.log_call(**kwargs)      → 写入 ai_audit_log 表
    - AuditService.query_logs(...)          → 分页查询
    - AuditService.get_detail(log_id)       → 按 ID 查单条
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.config import settings                # noqa: E402
from app.database import init_db, get_connection  # noqa: E402
from app.services.audit_service import AuditService  # noqa: E402


# ai_audit_log 表列索引（基于 DDL 定义，0-indexed）
# 0:id  1:host_id  2:host_name  3:profile_id  4:profile_name
# 5:model_name  6:status  7:prompt_tokens  8:completion_tokens
# 9:total_tokens  10:latency_ms  11:masked_mode  12:prompt
# 13:response  14:error_message  15:ip_address  16:user_id  17:created_at


class TestAuditServiceMethods:
    """AuditService 新增方法回归测试套件."""

    @pytest.fixture(autouse=True)
    def _setup_teardown(self):
        """每个测试前创建独立临时库，测试后清理."""
        tmpdir_obj = tempfile.TemporaryDirectory()
        tmpdir = tmpdir_obj.name

        # 保存原始配置
        saved_db_path = settings.DB_PATH
        saved_data_dir = settings.DATA_DIR
        saved_upload_dir = settings.UPLOAD_DIR

        # 重定向到临时目录
        settings.DB_PATH = str(Path(tmpdir) / "test_audit.db")
        settings.DATA_DIR = tmpdir
        settings.UPLOAD_DIR = str(Path(tmpdir) / "imports")

        Path(settings.DATA_DIR).mkdir(parents=True, exist_ok=True)
        Path(settings.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)

        # 用真实 init_db 建全量表
        init_db()

        yield  # 测试执行

        # 还原配置
        settings.DB_PATH = saved_db_path
        settings.DATA_DIR = saved_data_dir
        settings.UPLOAD_DIR = saved_upload_dir
        tmpdir_obj.cleanup()

    # ── log_call 测试 ──────────────────────────────────────

    def test_log_call_with_minimal_params(self):
        """最小参数调用 log_call 应该成功写入."""
        AuditService.log_call(
            host_id=1,
            host_name="test-host",
            profile_id=1,
            model_name="deepseek-v4",
            status="success",
        )
        with get_connection() as conn:
            row = conn.execute("SELECT COUNT(*) FROM ai_audit_log").fetchone()
            assert row[0] == 1, "log_call should insert one row"
            detail = conn.execute("SELECT * FROM ai_audit_log").fetchone()
            assert detail[1] == 1           # host_id
            assert detail[2] == "test-host"  # host_name
            assert detail[6] == "success"    # status (column 6, NOT 5)

    def test_log_call_with_all_params(self):
        """全参数调用验证."""
        AuditService.log_call(
            host_id=1, host_name="h1", profile_id=1, profile_name="p1",
            model_name="model", status="success",
            prompt_tokens=100, completion_tokens=200, total_tokens=300,
            latency_ms=500, masked_mode=1,
            prompt="test prompt", response="test response",
            error_message="", ip_address="127.0.0.1", user_id=1,
        )
        with get_connection() as conn:
            row = conn.execute("SELECT * FROM ai_audit_log").fetchone()
            assert row[7] == 100    # prompt_tokens
            assert row[8] == 200    # completion_tokens
            assert row[9] == 300    # total_tokens
            assert row[10] == 500   # latency_ms
            assert row[11] == 1     # masked_mode
            assert row[12] == "test prompt"   # prompt
            assert row[13] == "test response"  # response
            assert row[15] == "127.0.0.1"      # ip_address
            assert row[16] == 1     # user_id

    def test_log_call_with_error(self):
        """status=failed 的用例验证."""
        AuditService.log_call(
            host_id=1, host_name="h1", model_name="m1",
            status="failed", error_message="Connection timeout",
        )
        with get_connection() as conn:
            row = conn.execute("SELECT * FROM ai_audit_log").fetchone()
            assert row[6] == "failed"                   # status
            assert row[14] == "Connection timeout"      # error_message

    def test_log_call_partial_params(self):
        """只传 host_id/host_name/model_name/status — 其余应为默认值."""
        AuditService.log_call(
            host_id=10, host_name="partial", model_name="gpt4", status="success",
        )
        with get_connection() as conn:
            row = conn.execute("SELECT * FROM ai_audit_log").fetchone()
            assert row[1] == 10           # host_id
            assert row[2] == "partial"     # host_name
            assert row[5] == "gpt4"        # model_name
            assert row[7] == 0             # prompt_tokens (default)
            assert row[8] == 0             # completion_tokens (default)
            assert row[9] == 0             # total_tokens (default)
            assert row[10] == 0            # latency_ms (default)
            assert row[11] == 0            # masked_mode (default)

    # ── query_logs 测试 ────────────────────────────────────

    def test_query_logs_empty(self):
        """空库查询应返回空列表."""
        result = AuditService.query_logs()
        assert result["items"] == []
        assert result["total"] == 0
        assert result["page"] == 1
        assert result["page_size"] == 20

    def test_query_logs_with_data(self):
        """写入多条后查询验证分页和过滤."""
        AuditService.log_call(host_id=1, host_name="h1", model_name="m1", status="success")
        AuditService.log_call(host_id=2, host_name="h2", model_name="m2", status="failed")
        AuditService.log_call(host_id=1, host_name="h1", model_name="m1", status="success")

        # 全量查询
        result = AuditService.query_logs()
        assert result["total"] == 3
        assert len(result["items"]) == 3

        # 按 host_id 过滤
        result = AuditService.query_logs(host_id=1)
        assert result["total"] == 2
        for item in result["items"]:
            assert item["host_id"] == 1

        # 按 status 过滤
        result = AuditService.query_logs(status="failed")
        assert result["total"] == 1
        assert result["items"][0]["status"] == "failed"

    def test_query_logs_pagination(self):
        """分页参数验证."""
        for i in range(5):
            AuditService.log_call(
                host_id=i + 1, host_name=f"h{i}", model_name="m1", status="success",
            )

        # page_size=2
        page1 = AuditService.query_logs(page=1, page_size=2)
        assert page1["page"] == 1
        assert page1["page_size"] == 2
        assert len(page1["items"]) == 2
        assert page1["total"] == 5

        page2 = AuditService.query_logs(page=2, page_size=2)
        assert len(page2["items"]) == 2

        page3 = AuditService.query_logs(page=3, page_size=2)
        assert len(page3["items"]) == 1

        # 各页 ID 不重叠
        ids_p1 = {item["id"] for item in page1["items"]}
        ids_p2 = {item["id"] for item in page2["items"]}
        ids_p3 = {item["id"] for item in page3["items"]}
        assert ids_p1.isdisjoint(ids_p2)
        assert ids_p1.isdisjoint(ids_p3)
        assert ids_p2.isdisjoint(ids_p3)

    # ── get_detail 测试 ────────────────────────────────────

    def test_get_detail_found(self):
        """按 ID 查询应返回正确记录."""
        AuditService.log_call(
            host_id=1, host_name="h1", profile_id=10,
            model_name="m1", status="success",
        )
        # 通过直接查库拿到插入的 id
        with get_connection() as conn:
            row = conn.execute("SELECT id FROM ai_audit_log").fetchone()
            inserted_id = row[0]

        result = AuditService.get_detail(inserted_id)
        assert result["id"] == inserted_id
        assert result["host_id"] == 1
        assert result["host_name"] == "h1"
        assert result["profile_id"] == 10

    def test_get_detail_not_found(self):
        """不存在的 log_id 应抛 ValueError."""
        with pytest.raises(ValueError, match="not found"):
            AuditService.get_detail(999)

    # ── 回归：原有 create_audit_log 不受影响 ──────────────

    def test_create_audit_log_still_works(self):
        """原有的 create_audit_log 方法不受影响."""
        AuditService.create_audit_log(
            user_id=1, username="admin", action_type="ai_analysis",
            detail="test audit",
        )
        with get_connection() as conn:
            row = conn.execute("SELECT COUNT(*) FROM audit_logs").fetchone()
            assert row[0] == 1
