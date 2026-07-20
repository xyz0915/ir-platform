"""test_playbook_engine — 验证"调查剧本"引擎真实查询本地库 / 真实调用大模型.

测试策略：
- query 步骤：直接对本地真实数据库执行，断言返回的 output 为 list，
  且其长度与数据库实际行数一致（证明不是写死/伪造的数据）。
- llm 步骤：分别验证「无激活大模型配置（安全降级）」与「有配置且真实调用」
  两种情况下都返回字符串且不抛异常。真实调用通过 mock AiService.call_llm 完成，
  避免对外部 LLM 服务产生依赖。
"""

import asyncio
from unittest.mock import patch

from app.schemas.ai_advanced import PlaybookStep
from app.services.playbook_engine import PlaybookEngine


def run(coro):
    """在独立事件循环中运行协程（每个测试互不干扰）."""
    return asyncio.run(coro)


def _db_scalar(sql: str, params: tuple = ()) -> int:
    """读取本地真实数据库标量值，用于与引擎输出做一致性校验."""
    import sqlite3
    import app.config as cfg
    conn = sqlite3.connect(cfg.settings.DB_PATH)
    try:
        return conn.execute(sql, params).fetchone()[0]
    finally:
        conn.close()


def _expected_count(table: str, limit: int, where: str = "", params: tuple = ()) -> int:
    """真实库中的总行数，并受 limit 上限约束（模拟引擎的 LIMIT 行为）."""
    sql = f"SELECT COUNT(*) FROM {table}" + (f" WHERE {where}" if where else "")
    raw = _db_scalar(sql, params)
    return min(raw, limit)


def make_running_engine(steps: list) -> PlaybookEngine:
    """构造一个处于 running 状态、步骤列表已就绪的引擎实例."""
    engine = PlaybookEngine()
    engine._steps = steps
    engine._status = engine._status.model_copy(update={
        "status": "running",
        "total_steps": len(steps),
        "current_step": 0,
        "step_results": [],
    })
    return engine


# ----------------------------------------------------------------------
# query 步骤：真实查询本地库
# ----------------------------------------------------------------------

def test_query_abnormal_processes_returns_real_rows():
    engine = make_running_engine([
        PlaybookStep(id="s1", name="异常进程", type="query",
                     params={"query_type": "abnormal_processes", "limit": 20}),
    ])
    result, step_type, _ = run(engine.execute_step())
    assert step_type == "query"
    assert isinstance(result.output, list)
    expected = _expected_count("abnormal_processes", 20)
    assert len(result.output) == expected
    if expected > 0:
        assert isinstance(result.output[0], dict)
    assert result.summary  # 含人类可读摘要
    assert result.completed_at  # 已填充完成时间
    assert result.step_id == "s1"


def test_query_network_connections_returns_real_rows():
    engine = make_running_engine([
        PlaybookStep(id="s1", name="网络连接", type="query",
                     params={"query_type": "network_connections", "limit": 20}),
    ])
    result, step_type, _ = run(engine.execute_step())
    assert step_type == "query"
    assert isinstance(result.output, list)
    expected = _expected_count("network_connections", 20)
    assert len(result.output) == expected


def test_query_logs_successful_logon_returns_real_rows():
    engine = make_running_engine([
        PlaybookStep(id="s1", name="登录日志", type="query",
                     params={"query_type": "logs", "event_type": "successful_logon", "limit": 50}),
    ])
    result, step_type, _ = run(engine.execute_step())
    assert step_type == "query"
    assert isinstance(result.output, list)
    expected = _expected_count(
        "normalized_logs", 50, where="event_type=?", params=("successful_logon",),
    )
    assert len(result.output) == expected
    # 确认走的是含该 event_type 的真实日志表
    assert "normalized_logs" in result.summary


def test_query_alerts_returns_list_and_matches_db():
    engine = make_running_engine([
        PlaybookStep(id="s1", name="告警", type="query",
                     params={"query_type": "alerts", "severity": "high", "limit": 20}),
    ])
    result, step_type, _ = run(engine.execute_step())
    assert step_type == "query"
    assert isinstance(result.output, list)  # 不强制非空（取决于库内数据）
    expected = _expected_count("alerts", 20, where="severity=?", params=("high",))
    assert len(result.output) == expected


def test_query_file_hashes_returns_list():
    engine = make_running_engine([
        PlaybookStep(id="s1", name="文件哈希", type="query",
                     params={"query_type": "file_hashes", "limit": 20}),
    ])
    result, step_type, _ = run(engine.execute_step())
    assert step_type == "query"
    assert isinstance(result.output, list)


def test_query_extract_ips_returns_list():
    engine = make_running_engine([
        PlaybookStep(id="s1", name="来源IP", type="query",
                     params={"query_type": "extract_ips"}),
    ])
    result, step_type, _ = run(engine.execute_step())
    assert step_type == "query"
    assert isinstance(result.output, list)


def test_query_unknown_type_does_not_raise():
    engine = make_running_engine([
        PlaybookStep(id="s1", name="未知", type="query",
                     params={"query_type": "no_such_type"}),
    ])
    result, step_type, _ = run(engine.execute_step())
    assert step_type == "query"
    assert isinstance(result.output, list)
    assert result.output == []  # 未支持类型优雅返回空，不崩溃
    assert "未支持" in result.summary


# ----------------------------------------------------------------------
# llm 步骤：真实调用 / 安全降级
# ----------------------------------------------------------------------

def test_llm_without_profile_returns_degraded_string():
    engine = make_running_engine([
        PlaybookStep(id="s1", name="分析", type="llm",
                     params={"prompt": "分析以下日志是否存在暴力破解"}),
    ])
    with patch("app.services.playbook_engine.AiConfigProfile.get_active", return_value=None):
        result, step_type, _ = run(engine.execute_step())
    assert step_type == "llm"
    assert isinstance(result.output, str)
    assert result.output  # 非空
    assert "未配置大模型" in result.output
    assert result.status == "completed"


def test_llm_with_profile_calls_real_llm():
    engine = make_running_engine([
        PlaybookStep(id="s1", name="分析", type="llm",
                     params={"prompt": "分析异常进程"}),
    ])
    fake_profile = {
        "api_base_url": "http://fake.local", "api_key": "encrypted",
        "model_name": "gpt-4o", "max_tokens": 1500, "temperature": 0.3,
        "system_prompt": "",
    }
    fake_llm = {"choices": [{"message": {"content": "分析结论：存在可疑进程创建链。"}}]}
    with patch("app.services.playbook_engine.AiConfigProfile.get_active", return_value=fake_profile), \
         patch("app.services.playbook_engine.AiService.decrypt_api_key", return_value="plain"), \
         patch("app.services.playbook_engine.AiService.call_llm", return_value=fake_llm):
        result, step_type, _ = run(engine.execute_step())
    assert step_type == "llm"
    assert isinstance(result.output, str)
    assert "分析结论" in result.output
    assert result.status == "completed"


def test_llm_injects_dependency_context():
    """llm 步应将 depends_on 前序步骤的真实产出摘要拼入 prompt."""
    engine = make_running_engine([
        PlaybookStep(id="st1", name="查进程", type="query",
                     params={"query_type": "abnormal_processes", "limit": 5}),
        PlaybookStep(id="st2", name="分析", type="llm",
                     params={"prompt": "请分析"}, depends_on=["st1"]),
    ])
    fake_profile = {
        "api_base_url": "http://fake.local", "api_key": "encrypted",
        "model_name": "gpt-4o", "max_tokens": 1500, "temperature": 0.3,
        "system_prompt": "",
    }
    captured = {}

    async def fake_call(**kwargs):
        captured.update(kwargs)
        return {"choices": [{"message": {"content": "ok"}}]}

    with patch("app.services.playbook_engine.AiConfigProfile.get_active", return_value=fake_profile), \
         patch("app.services.playbook_engine.AiService.decrypt_api_key", return_value="plain"), \
         patch("app.services.playbook_engine.AiService.call_llm", side_effect=fake_call):
        run(engine.execute_step())          # 执行 query 步
        result, _, _ = run(engine.execute_step())  # 执行 llm 步

    assert isinstance(result.output, str)
    # 前序步骤 st1 的真实产出摘要应被注入 user_prompt
    assert "st1" in captured.get("user_prompt", "")


def test_llm_call_failure_degrades_gracefully():
    """大模型调用抛异常时，llm 步降级为字符串而非崩溃."""
    engine = make_running_engine([
        PlaybookStep(id="s1", name="分析", type="llm",
                     params={"prompt": "分析网络连接"}),
    ])
    fake_profile = {
        "api_base_url": "http://fake.local", "api_key": "encrypted",
        "model_name": "gpt-4o", "max_tokens": 1500, "temperature": 0.3,
        "system_prompt": "",
    }
    with patch("app.services.playbook_engine.AiConfigProfile.get_active", return_value=fake_profile), \
         patch("app.services.playbook_engine.AiService.decrypt_api_key", return_value="plain"), \
         patch("app.services.playbook_engine.AiService.call_llm", side_effect=RuntimeError("boom")):
        result, step_type, _ = run(engine.execute_step())
    assert step_type == "llm"
    assert isinstance(result.output, str)
    assert "大模型调用失败" in result.output
    assert result.status == "completed"
