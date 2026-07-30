"""AI 审计中心优化改造测试套件（T05-1 ~ T05-4）.

测试范围:
    T05-1: AuditService 写入验证 — endpoint/intent/audit_log_id 正确落库
    T05-2: TokenStatsService 分组验证 — group_by endpoint/model, by_endpoint 汇总
    T05-4: DB 端到端验证 — DDL 新列存在性

测试策略:
    - 每个测试类使用独立临时 SQLite 库（tempfile），绝不碰生产库。
    - setup_method 重新初始化全量建表，保证测试完全隔离。
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.config import settings
from app.database import init_db, get_connection
from app.services.audit_service import AuditService
from app.services.token_stats_service import TokenStatsService


# ══════════════════════════════════════════════════════════════════
# 公共 Fixture：每个测试方法使用独立临时库
# ══════════════════════════════════════════════════════════════════


@pytest.fixture(autouse=True)
def _isolated_db():
    """每个测试前创建独立临时 SQLite 库，测试后自动清理."""
    with tempfile.TemporaryDirectory() as tmpdir:
        saved_db_path = settings.DB_PATH
        saved_data_dir = settings.DATA_DIR
        saved_upload_dir = settings.UPLOAD_DIR

        settings.DB_PATH = str(Path(tmpdir) / "test_audit_opt.db")
        settings.DATA_DIR = tmpdir
        settings.UPLOAD_DIR = str(Path(tmpdir) / "imports")

        Path(settings.DATA_DIR).mkdir(parents=True, exist_ok=True)
        Path(settings.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)

        # 用真实 init_db 建全量表（包含新列的 DDL）
        init_db()

        yield

        # 还原配置
        settings.DB_PATH = saved_db_path
        settings.DATA_DIR = saved_data_dir
        settings.UPLOAD_DIR = saved_upload_dir


def _get_columns(table: str) -> set[str]:
    """返回指定表的全部列名."""
    with get_connection() as conn:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        return {r["name"] for r in rows}


def _insert_audit_rows():
    """插入多条不同端点和模型的审计日志，供查询/统计使用."""
    AuditService.log_call(
        host_id=1, host_name="host-a", model_name="gpt-4o",
        status="success", prompt_tokens=100, completion_tokens=50,
        total_tokens=150, latency_ms=500,
        endpoint="analysis", intent="host_analysis",
    )
    AuditService.log_call(
        host_id=1, host_name="host-a", model_name="gpt-4o",
        status="success", prompt_tokens=200, completion_tokens=100,
        total_tokens=300, latency_ms=800,
        endpoint="analysis", intent="host_analysis",
    )
    AuditService.log_call(
        host_id=2, host_name="host-b", model_name="claude-3",
        status="success", prompt_tokens=300, completion_tokens=150,
        total_tokens=450, latency_ms=1200,
        endpoint="chat", intent="follow_up",
    )
    AuditService.log_call(
        host_id=2, host_name="host-b", model_name="claude-3",
        status="failed", prompt_tokens=50, completion_tokens=0,
        total_tokens=50, latency_ms=30000,
        endpoint="chat", intent="follow_up",
        error_message="Timeout",
    )
    AuditService.log_call(
        host_id=3, host_name="host-c", model_name="gpt-4o",
        status="success", prompt_tokens=400, completion_tokens=200,
        total_tokens=600, latency_ms=900,
        endpoint="noise_reduce", intent="ai_noise_reduce",
        prompt="test prompt content for keyword search",
        response="test response with keyword",
    )


# ══════════════════════════════════════════════════════════════════
# T05-1: AuditService 写入验证
# ══════════════════════════════════════════════════════════════════


class TestAuditServiceNewColumns:
    """验证 endpoint / intent / audit_log_id 正确落库."""

    def test_log_call_saves_endpoint_and_intent(self):
        """a) 传入 endpoint/intent 时正确落库."""
        AuditService.log_call(
            host_id=1, host_name="h1", model_name="m1", status="success",
            endpoint="analysis", intent="host_analysis",
        )
        with get_connection() as conn:
            row = conn.execute(
                "SELECT endpoint, intent FROM ai_audit_log"
            ).fetchone()
        assert row["endpoint"] == "analysis"
        assert row["intent"] == "host_analysis"

    def test_log_call_saves_audit_log_id(self):
        """a) 传入 audit_log_id 时正确落库."""
        AuditService.log_call(
            host_id=1, host_name="h1", model_name="m1", status="success",
            audit_log_id=42,
        )
        with get_connection() as conn:
            row = conn.execute(
                "SELECT audit_log_id FROM ai_audit_log"
            ).fetchone()
        assert row["audit_log_id"] == 42

    def test_log_call_endpoint_default_none(self):
        """b) 不传 endpoint 时默认值为 None（向后兼容）."""
        AuditService.log_call(
            host_id=1, host_name="h1", model_name="m1", status="success",
        )
        with get_connection() as conn:
            row = conn.execute(
                "SELECT endpoint FROM ai_audit_log"
            ).fetchone()
        assert row["endpoint"] is None

    def test_log_call_intent_default_none(self):
        """b) 不传 intent 时默认值为 None（向后兼容）."""
        AuditService.log_call(
            host_id=1, host_name="h1", model_name="m1", status="success",
        )
        with get_connection() as conn:
            row = conn.execute(
                "SELECT intent FROM ai_audit_log"
            ).fetchone()
        assert row["intent"] is None

    def test_log_call_audit_log_id_default_none(self):
        """b) 不传 audit_log_id 时默认值为 None（向后兼容）."""
        AuditService.log_call(
            host_id=1, host_name="h1", model_name="m1", status="success",
        )
        with get_connection() as conn:
            row = conn.execute(
                "SELECT audit_log_id FROM ai_audit_log"
            ).fetchone()
        assert row["audit_log_id"] is None

    def test_log_call_all_new_columns_together(self):
        """同时传入三个新列，验证全部正确落库."""
        AuditService.log_call(
            host_id=1, host_name="h1", model_name="m1", status="success",
            endpoint="noise_reduce", intent="ai_noise_reduce",
            audit_log_id=99, prompt_tokens=100, total_tokens=200,
        )
        with get_connection() as conn:
            row = conn.execute(
                "SELECT endpoint, intent, audit_log_id FROM ai_audit_log"
            ).fetchone()
        assert row["endpoint"] == "noise_reduce"
        assert row["intent"] == "ai_noise_reduce"
        assert row["audit_log_id"] == 99


class TestAuditServiceQueryLogsNewFilters:
    """验证 query_logs() 新增的 7 个筛选条件."""

    def test_query_logs_filter_by_model_name(self):
        """c) 按 model_name 筛选."""
        _insert_audit_rows()
        result = AuditService.query_logs(model_name="gpt-4o")
        assert result["total"] == 3  # 3 条 gpt-4o
        for item in result["items"]:
            assert item["model_name"] == "gpt-4o"

    def test_query_logs_filter_by_endpoint(self):
        """d) 按 endpoint 筛选."""
        _insert_audit_rows()
        result = AuditService.query_logs(endpoint="chat")
        assert result["total"] == 2  # 2 条 chat
        for item in result["items"]:
            assert item["endpoint"] == "chat"

    def test_query_logs_filter_by_keyword_in_prompt(self):
        """e) 按 keyword 全文搜索 (命中 prompt)."""
        _insert_audit_rows()
        result = AuditService.query_logs(keyword="test prompt content")
        assert result["total"] >= 1
        for item in result["items"]:
            assert "test prompt content" in (item.get("prompt") or "")

    def test_query_logs_filter_by_keyword_in_response(self):
        """e) 按 keyword 全文搜索 (命中 response)."""
        _insert_audit_rows()
        result = AuditService.query_logs(keyword="test response with keyword")
        assert result["total"] >= 1
        for item in result["items"]:
            assert "test response with keyword" in (item.get("response") or "")

    def test_query_logs_filter_by_keyword_in_error(self):
        """e) 按 keyword 全文搜索 (命中 error_message)."""
        _insert_audit_rows()
        result = AuditService.query_logs(keyword="Timeout")
        assert result["total"] >= 1
        for item in result["items"]:
            assert "Timeout" in (item.get("error_message") or "")

    def test_query_logs_filter_by_keyword_no_match(self):
        """e) keyword 无匹配时返回空."""
        _insert_audit_rows()
        result = AuditService.query_logs(keyword="ZZZNOTFOUNDZZZ")
        assert result["total"] == 0
        assert result["items"] == []

    def test_query_logs_filter_by_start_time(self):
        """f) 按 start_time 筛选."""
        _insert_audit_rows()
        # 使用过去的时间确保全匹配
        result = AuditService.query_logs(start_time="2020-01-01")
        assert result["total"] >= 5

    def test_query_logs_filter_by_end_time(self):
        """f) 按 end_time 筛选."""
        _insert_audit_rows()
        # 使用未来的时间确保全匹配
        result = AuditService.query_logs(end_time="2099-12-31")
        assert result["total"] >= 5

    def test_query_logs_filter_by_min_tokens(self):
        """f) 按 min_tokens 筛选."""
        _insert_audit_rows()
        result = AuditService.query_logs(min_tokens=400)
        for item in result["items"]:
            assert item["total_tokens"] >= 400

    def test_query_logs_filter_by_max_tokens(self):
        """f) 按 max_tokens 筛选."""
        _insert_audit_rows()
        result = AuditService.query_logs(max_tokens=100)
        assert result["total"] >= 1  # 至少一条 total_tokens <= 100
        for item in result["items"]:
            assert item["total_tokens"] <= 100

    def test_query_logs_filter_by_time_range(self):
        """f) 同时按 start_time + end_time 筛选."""
        _insert_audit_rows()
        result = AuditService.query_logs(
            start_time="2020-01-01", end_time="2099-12-31"
        )
        assert result["total"] >= 5


# ══════════════════════════════════════════════════════════════════
# T05-2: TokenStatsService 分组验证
# ══════════════════════════════════════════════════════════════════


class TestTokenStatsGroupBy:
    """验证 TokenStatsService 分组功能."""

    def test_get_daily_stats_group_by_endpoint(self):
        """g) get_daily_stats(group_by='endpoint') 返回分组结果."""
        _insert_audit_rows()
        stats = TokenStatsService.get_daily_stats(days=365, group_by="endpoint")
        assert len(stats) >= 1
        # 检查字段结构
        for row in stats:
            assert "date" in row
            assert "endpoint" in row
            assert "total_tokens" in row
            assert "count" in row
        # 应该有分析端点
        endpoints = {r["endpoint"] for r in stats}
        assert "analysis" in endpoints
        assert "chat" in endpoints
        assert "noise_reduce" in endpoints

    def test_get_daily_stats_group_by_endpoint_values(self):
        """g) 验证 endpoint 分组统计值的正确性."""
        _insert_audit_rows()
        stats = TokenStatsService.get_daily_stats(days=365, group_by="endpoint")
        # analysis 共 2 条: 150+300=450 tokens, count=2
        analysis_rows = [r for r in stats if r["endpoint"] == "analysis"]
        if analysis_rows:
            row = analysis_rows[0]
            assert row["total_tokens"] >= 450
            assert row["count"] >= 2

    def test_get_daily_stats_group_by_model(self):
        """h) get_daily_stats(group_by='model') 返回分组结果."""
        _insert_audit_rows()
        stats = TokenStatsService.get_daily_stats(days=365, group_by="model")
        assert len(stats) >= 1
        for row in stats:
            assert "date" in row
            assert "model_name" in row
            assert "total_tokens" in row
            assert "count" in row
        models = {r["model_name"] for r in stats}
        assert "gpt-4o" in models
        assert "claude-3" in models

    def test_get_daily_stats_no_group_by(self):
        """无 group_by 时返回默认每日聚合."""
        _insert_audit_rows()
        stats = TokenStatsService.get_daily_stats(days=365)
        assert len(stats) >= 1
        for row in stats:
            assert "date" in row
            assert "total_tokens" in row
            assert "count" in row
            # 无分组时不应有 endpoint/model_name 字段
            assert "endpoint" not in row
            assert "model_name" not in row

    def test_get_summary_contains_by_endpoint(self):
        """i) get_summary() 返回的 by_endpoint 字段格式正确."""
        _insert_audit_rows()
        summary = TokenStatsService.get_summary()
        assert "by_endpoint" in summary
        assert isinstance(summary["by_endpoint"], list)
        for ep in summary["by_endpoint"]:
            assert "endpoint" in ep
            assert "total_tokens" in ep
            assert "total_calls" in ep
        # 应包含所有非空 endpoint
        endpoints_in_result = {ep["endpoint"] for ep in summary["by_endpoint"]}
        assert "analysis" in endpoints_in_result
        assert "chat" in endpoints_in_result
        assert "noise_reduce" in endpoints_in_result

    def test_get_summary_by_endpoint_empty_db(self):
        """空库时 by_endpoint 应为空列表."""
        summary = TokenStatsService.get_summary()
        assert "by_endpoint" in summary
        assert summary["by_endpoint"] == []

    def test_get_summary_other_fields(self):
        """get_summary() 的其他关键字段也应存在."""
        _insert_audit_rows()
        summary = TokenStatsService.get_summary()
        assert "total_tokens" in summary
        assert "total_calls" in summary
        assert "avg_latency_ms" in summary
        assert "success_rate" in summary
        assert "this_month_tokens" in summary
        assert "this_month_calls" in summary
        assert summary["total_calls"] == 5
        assert summary["success_rate"] > 0  # 至少有个成功


# ══════════════════════════════════════════════════════════════════
# T05-4: DB 端到端验证
# ══════════════════════════════════════════════════════════════════


class TestDdlSchema:
    """验证 DDL 包含新增列."""

    def test_ai_audit_log_has_endpoint_column(self):
        """验证 ai_audit_log 表包含 endpoint 列."""
        cols = _get_columns("ai_audit_log")
        assert "endpoint" in cols, "endpoint column missing in ai_audit_log"

    def test_ai_audit_log_has_intent_column(self):
        """验证 ai_audit_log 表包含 intent 列."""
        cols = _get_columns("ai_audit_log")
        assert "intent" in cols, "intent column missing in ai_audit_log"

    def test_ai_audit_log_has_audit_log_id_column(self):
        """验证 ai_audit_log 表包含 audit_log_id 列."""
        cols = _get_columns("ai_audit_log")
        assert "audit_log_id" in cols, "audit_log_id column missing in ai_audit_log"

    def test_ai_audit_log_has_all_standard_columns(self):
        """验证 ai_audit_log 表包含所有标准列."""
        cols = _get_columns("ai_audit_log")
        standard_cols = {
            "id", "host_id", "host_name", "profile_id", "profile_name",
            "model_name", "status", "prompt_tokens", "completion_tokens",
            "total_tokens", "latency_ms", "masked_mode", "prompt", "response",
            "error_message", "ip_address", "user_id", "created_at",
            "endpoint", "intent", "audit_log_id",
        }
        missing = standard_cols - cols
        assert not missing, f"Missing columns in ai_audit_log: {missing}"
