"""自然语言指挥台 v3.0 端到端测试.

测试范围:
  1. 后端 API 测试 (使用 TestClient)
     - GET /api/ai/generate-report → 200 + summary/sections/suggestions
     - GET /api/ai/query-stream → SSE query_end 含 exec_time_ms + results_count
  2. 回归测试: 6 种查询类型均正常
  3. 前端构建验证: vite build
  4. 人工验证步骤清单

运行方式:
    cd backend && venv/Scripts/python.exe -m pytest tests/test_ai_advanced_v3.py -v
    或
    cd backend && venv/Scripts/python.exe tests/test_ai_advanced_v3.py -v
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

# ============================================================
# Helpers
# ============================================================

TEST_DB_PATH = str(BACKEND_DIR / "data" / "test_ai_advanced_v3.db")


def parse_sse_events(text: str) -> list[dict]:
    """解析 SSE 文本为事件列表."""
    events = []
    for block in text.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        event_type = ""
        event_data = ""
        for line in block.split("\n"):
            if line.startswith("event: "):
                event_type = line[7:]
            elif line.startswith("data: "):
                event_data = line[6:]
        if event_data:
            try:
                events.append({
                    "event": event_type,
                    "data": json.loads(event_data),
                })
            except json.JSONDecodeError:
                pass
    return events


# ============================================================
# Test Suite
# ============================================================

class TestAiAdvancedV3(unittest.TestCase):
    """自然语言指挥台 v3.0 端到端测试."""

    @classmethod
    def setUpClass(cls):
        """设置测试环境 — 使用独立临时 DB."""
        db_path = Path(TEST_DB_PATH)
        if db_path.exists():
            db_path.unlink()

        from app.config import settings
        settings.DB_PATH = TEST_DB_PATH

        # 确保目录存在
        Path(settings.DATA_DIR).mkdir(parents=True, exist_ok=True)
        Path(settings.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
        Path(settings.AGENT_DIR).mkdir(parents=True, exist_ok=True)

        from app.database import init_db
        init_db()

        from fastapi.testclient import TestClient
        from app.main import app
        cls.client = TestClient(app)

        # 创建测试用户 (直接 hash)
        from app.services.auth_service import hash_password
        from app.database import get_connection
        with get_connection() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                ["admin", hash_password("admin123"), "admin"]
            )
            conn.commit()

        # 登录
        resp = cls.client.post("/api/auth/login", json={
            "username": "admin",
            "password": "admin123",
        })
        cls.token = resp.json()["data"]["token"]
        cls.headers = {"Authorization": f"Bearer {cls.token}"}

        # 插入一些测试数据以确保查询非空
        # 注意: hosts 表有 case_id INTEGER NOT NULL REFERENCES cases(id)
        #       alerts.host_id REFERENCES hosts(id)
        #       normalized_logs.host_id REFERENCES hosts(id)
        with get_connection() as conn:
            # 1. 先插案件 (hosts 依赖 cases)
            conn.execute(
                "INSERT OR IGNORE INTO cases (id, name, status, created_at) VALUES "
                "(1, '测试案件1', 'open', datetime('now'))"
            )
            # 2. 再插主机 (alerts 和 logs 依赖 hosts)
            conn.execute(
                "INSERT OR IGNORE INTO hosts (id, case_id, hostname, ip_address, status) "
                "VALUES (1, 1, 'test-host-01', '10.0.0.1', 'online')"
            )
            conn.execute(
                "INSERT OR IGNORE INTO hosts (id, case_id, hostname, ip_address, status) "
                "VALUES (2, 1, 'test-host-02', '10.0.0.2', 'offline')"
            )
            # 3. 再插告警
            conn.execute(
                "INSERT OR IGNORE INTO alerts (id, title, severity, status, host_id, rule_name, last_seen_at) VALUES "
                "(1, 'Test Alert 1', 'high', 'open', 1, 'test_rule', datetime('now'))"
            )
            conn.execute(
                "INSERT OR IGNORE INTO alerts (id, title, severity, status, host_id, rule_name, last_seen_at) VALUES "
                "(2, 'Test Alert 2', 'medium', 'open', 1, 'test_rule', datetime('now'))"
            )
            conn.execute(
                "INSERT OR IGNORE INTO alerts (id, title, severity, status, host_id, rule_name, last_seen_at) VALUES "
                "(3, 'Test Alert 3', 'low', 'dismissed', 2, 'other_rule', datetime('now'))"
            )
            # 4. 再插日志
            conn.execute(
                "INSERT OR IGNORE INTO normalized_logs (id, event_type, severity, host_id, timestamp) VALUES "
                "(1, 'failed_logon', 'high', 1, datetime('now'))"
            )
            conn.execute(
                "INSERT OR IGNORE INTO normalized_logs (id, event_type, severity, host_id, timestamp) VALUES "
                "(2, 'successful_logon', 'medium', 1, datetime('now'))"
            )
            # 5. 策略 (使用 model 方法)
            from app.models.policy import DetectionPolicy
            DetectionPolicy.create(
                name="测试策略",
                description="测试",
                enable_rag=1, enable_attack_chain=1,
            )
            conn.commit()

    # ================================================================
    # 1. 后端 API 测试: /api/ai/generate-report
    # ================================================================

    def test_01_generate_report_returns_200(self):
        """generate-report 返回 200."""
        resp = self.client.get("/api/ai/generate-report", params={"query": "安全态势报告"}, headers=self.headers)
        self.assertEqual(resp.status_code, 200)

    def test_02_generate_report_has_success_flag(self):
        """generate-report 含 success=True."""
        resp = self.client.get("/api/ai/generate-report", params={"query": "安全态势报告"}, headers=self.headers)
        data = resp.json()
        self.assertTrue(data.get("success"))

    def test_03_generate_report_has_summary(self):
        """generate-report data 含 summary 字段."""
        resp = self.client.get("/api/ai/generate-report", params={"query": "安全态势报告"}, headers=self.headers)
        data = resp.json().get("data", {})
        self.assertIn("summary", data)
        self.assertIsInstance(data["summary"], str)
        self.assertGreater(len(data["summary"]), 0)

    def test_04_generate_report_has_sections(self):
        """generate-report data 含 sections 列表 (非空)."""
        resp = self.client.get("/api/ai/generate-report", params={"query": "安全态势报告"}, headers=self.headers)
        data = resp.json().get("data", {})
        self.assertIn("sections", data)
        self.assertIsInstance(data["sections"], list)
        self.assertGreater(len(data["sections"]), 0)
        # 每个 section 有 title 和 items
        for sec in data["sections"]:
            self.assertIn("title", sec)
            self.assertIn("items", sec)

    def test_05_generate_report_has_suggestions(self):
        """generate-report data 含 suggestions 列表."""
        resp = self.client.get("/api/ai/generate-report", params={"query": "安全态势报告"}, headers=self.headers)
        data = resp.json().get("data", {})
        self.assertIn("suggestions", data)
        self.assertIsInstance(data["suggestions"], list)
        self.assertGreaterEqual(len(data["suggestions"]), 1)

    def test_06_generate_report_has_generated_at(self):
        """generate-report data 含 generated_at 时间戳."""
        resp = self.client.get("/api/ai/generate-report", params={"query": "安全态势报告"}, headers=self.headers)
        data = resp.json().get("data", {})
        self.assertIn("generated_at", data)
        self.assertIsInstance(data["generated_at"], str)
        self.assertGreater(len(data["generated_at"]), 0)

    def test_07_generate_report_required_fields(self):
        """generate-report 包含所有 5 个必需字段."""
        resp = self.client.get("/api/ai/generate-report", params={"query": "安全态势报告"}, headers=self.headers)
        data = resp.json().get("data", {})
        required_fields = ["generated_at", "query", "summary", "sections", "suggestions"]
        for field in required_fields:
            self.assertIn(field, data, f"缺少字段: {field}")

    def test_08_generate_report_section_types(self):
        """sections 应包含告警概览/日志/主机/案件/策略."""
        resp = self.client.get("/api/ai/generate-report", params={"query": "安全态势报告"}, headers=self.headers)
        sections = resp.json().get("data", {}).get("sections", [])
        titles = [s["title"] for s in sections]
        expected_titles = ["告警概览", "日志", "主机", "案件", "策略"]
        for et in expected_titles:
            self.assertTrue(
                any(et in t for t in titles),
                f"sections 中未找到含 '{et}' 的标题, 已有: {titles}"
            )

    # ================================================================
    # 2. 后端 API 测试: /api/ai/query-stream (SSE)
    # ================================================================

    def test_09_query_stream_returns_200(self):
        """query-stream 返回 200."""
        resp = self.client.get("/api/ai/query-stream", params={"query": "统计信息"}, headers=self.headers)
        self.assertEqual(resp.status_code, 200)

    def test_10_query_stream_content_type(self):
        """query-stream 返回 text/event-stream."""
        resp = self.client.get("/api/ai/query-stream", params={"query": "统计信息"}, headers=self.headers)
        self.assertIn("text/event-stream", resp.headers.get("content-type", ""))

    def test_11_query_stream_has_query_start_event(self):
        """SSE 流包含 query_start 事件."""
        resp = self.client.get("/api/ai/query-stream", params={"query": "统计信息"}, headers=self.headers)
        events = parse_sse_events(resp.text)
        event_types = [e["event"] for e in events]
        self.assertIn("query_start", event_types)

    def test_12_query_stream_has_query_end_event(self):
        """SSE 流包含 query_end 事件."""
        resp = self.client.get("/api/ai/query-stream", params={"query": "统计信息"}, headers=self.headers)
        events = parse_sse_events(resp.text)
        event_types = [e["event"] for e in events]
        self.assertIn("query_end", event_types)

    def test_13_query_end_has_exec_time_ms(self):
        """query_end 事件含 exec_time_ms 字段 (int)."""
        resp = self.client.get("/api/ai/query-stream", params={"query": "统计信息"}, headers=self.headers)
        events = parse_sse_events(resp.text)
        for ev in events:
            if ev["event"] == "query_end":
                self.assertIn("exec_time_ms", ev["data"])
                self.assertIsInstance(ev["data"]["exec_time_ms"], int)
                self.assertGreaterEqual(ev["data"]["exec_time_ms"], 0)
                return
        self.fail("未找到 query_end 事件")

    def test_14_query_end_has_results_count(self):
        """query_end 事件含 results_count 字段 (int)."""
        resp = self.client.get("/api/ai/query-stream", params={"query": "统计信息"}, headers=self.headers)
        events = parse_sse_events(resp.text)
        for ev in events:
            if ev["event"] == "query_end":
                self.assertIn("results_count", ev["data"])
                self.assertIsInstance(ev["data"]["results_count"], int)
                self.assertGreaterEqual(ev["data"]["results_count"], 0)
                return
        self.fail("未找到 query_end 事件")

    def test_15_query_end_has_both_new_fields(self):
        """query_end 同时包含 exec_time_ms 和 results_count."""
        resp = self.client.get("/api/ai/query-stream", params={"query": "统计信息"}, headers=self.headers)
        events = parse_sse_events(resp.text)
        for ev in events:
            if ev["event"] == "query_end":
                self.assertIn("exec_time_ms", ev["data"])
                self.assertIn("results_count", ev["data"])
                return
        self.fail("未找到 query_end 事件")

    def test_16_query_stream_has_text_chunks(self):
        """SSE 流包含 text_chunk 事件."""
        resp = self.client.get("/api/ai/query-stream", params={"query": "统计信息"}, headers=self.headers)
        events = parse_sse_events(resp.text)
        event_types = [e["event"] for e in events]
        self.assertIn("text_chunk", event_types)

    def test_17_query_stream_has_card_event(self):
        """SSE 流包含 card 事件."""
        resp = self.client.get("/api/ai/query-stream", params={"query": "统计信息"}, headers=self.headers)
        events = parse_sse_events(resp.text)
        event_types = [e["event"] for e in events]
        self.assertIn("card", event_types)

    def test_18_query_stream_all_query_types_have_query_end(self):
        """所有 6+ 查询类型的 SSE 流都包含 query_end 事件."""
        queries = ["告警", "日志", "主机", "案件", "统计", "策略", "在线主机", "严重的告警", "登录失败的日志"]
        for q in queries:
            resp = self.client.get("/api/ai/query-stream", params={"query": q}, headers=self.headers)
            events = parse_sse_events(resp.text)
            event_types = [e["event"] for e in events]
            self.assertIn("query_end", event_types, f"查询 '{q}' 缺少 query_end 事件")

    def test_19_query_stream_all_types_have_exec_time_ms_and_results_count(self):
        """所有查询类型的 query_end 事件都含 exec_time_ms + results_count."""
        queries = ["告警", "日志", "主机", "案件", "统计", "策略", "在线主机", "严重的告警", "登录失败的日志"]
        for q in queries:
            resp = self.client.get("/api/ai/query-stream", params={"query": q}, headers=self.headers)
            events = parse_sse_events(resp.text)
            found = False
            for ev in events:
                if ev["event"] == "query_end":
                    self.assertIn("exec_time_ms", ev["data"], f"查询 '{q}' 的 query_end 缺少 exec_time_ms")
                    self.assertIn("results_count", ev["data"], f"查询 '{q}' 的 query_end 缺少 results_count")
                    found = True
                    break
            self.assertTrue(found, f"查询 '{q}' 未找到 query_end 事件")

    def test_20_query_stream_same_session_id(self):
        """SSE 流中所有事件共享同一 session_id."""
        resp = self.client.get("/api/ai/query-stream", params={"query": "告警"}, headers=self.headers)
        events = parse_sse_events(resp.text)
        session_ids = set()
        for ev in events:
            if "session_id" in ev["data"]:
                session_ids.add(ev["data"]["session_id"])
        self.assertEqual(len(session_ids), 1, f"session_id 不一致: {session_ids}")

    # ================================================================
    # 3. 回归测试: 6 种查询类型
    # ================================================================

    def test_21_regression_alerts_query(self):
        """回归: 告警查询返回正确意图和数据."""
        resp = self.client.post("/api/ai/query", params={"query": "告警"}, headers=self.headers)
        data = resp.json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data["data"]["intent"], "alerts")
        self.assertIsNotNone(data["data"]["data"])

    def test_22_regression_logs_query(self):
        """回归: 日志查询返回正确意图和数据."""
        resp = self.client.post("/api/ai/query", params={"query": "日志"}, headers=self.headers)
        data = resp.json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data["data"]["intent"], "logs")
        self.assertIsNotNone(data["data"]["data"])

    def test_23_regression_hosts_query(self):
        """回归: 主机查询返回正确意图和数据."""
        resp = self.client.post("/api/ai/query", params={"query": "主机"}, headers=self.headers)
        data = resp.json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data["data"]["intent"], "hosts")
        self.assertIsNotNone(data["data"]["data"])

    def test_24_regression_cases_query(self):
        """回归: 案件查询返回正确意图和数据."""
        resp = self.client.post("/api/ai/query", params={"query": "案件"}, headers=self.headers)
        data = resp.json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data["data"]["intent"], "cases")
        self.assertIsNotNone(data["data"]["data"])

    def test_25_regression_stats_query(self):
        """回归: 统计查询返回正确意图和数据."""
        resp = self.client.post("/api/ai/query", params={"query": "统计"}, headers=self.headers)
        data = resp.json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data["data"]["intent"], "stats")
        self.assertIsNotNone(data["data"]["data"])

    def test_26_regression_policies_query(self):
        """回归: 策略查询返回正确意图和数据."""
        resp = self.client.post("/api/ai/query", params={"query": "策略"}, headers=self.headers)
        data = resp.json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data["data"]["intent"], "policies")
        self.assertIsNotNone(data["data"]["data"])

    def test_27_regression_unknown_query(self):
        """回归: 未知查询返回 summary 提示."""
        resp = self.client.post("/api/ai/query", params={"query": "今天天气怎么样"}, headers=self.headers)
        data = resp.json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data["data"]["intent"], "unknown")
        self.assertIn("未识别查询意图", data["data"]["summary"])

    def test_28_regression_empty_query(self):
        """回归: 空查询返回友好提示."""
        resp = self.client.post("/api/ai/query", params={"query": ""}, headers=self.headers)
        data = resp.json()
        self.assertTrue(data.get("success"))
        self.assertIn("请输入问题", data["data"]["summary"])

    def test_29_regression_severity_filter(self):
        """回归: 严重告警筛选 severity=high."""
        resp = self.client.post("/api/ai/query", params={"query": "严重的告警"}, headers=self.headers)
        data = resp.json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data["data"]["intent"], "alerts")
        self.assertEqual(data["data"]["params"].get("severity"), "high")

    def test_30_regression_login_fail_query(self):
        """回归: 登录失败日志筛选 event_type=failed_logon."""
        resp = self.client.post("/api/ai/query", params={"query": "登录失败的日志"}, headers=self.headers)
        data = resp.json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data["data"]["intent"], "logs")
        self.assertIn("failed_logon", data["data"]["params"].get("event_type", ""))

    # ================================================================
    # 4. SSE query-stream 回归: 6 种查询
    # ================================================================

    def test_31_sse_alerts_query(self):
        """SSE: 告警查询含 card(alert_list) + query_end."""
        resp = self.client.get("/api/ai/query-stream", params={"query": "告警"}, headers=self.headers)
        events = parse_sse_events(resp.text)
        event_types = [e["event"] for e in events]
        self.assertIn("card", event_types)
        self.assertIn("query_end", event_types)
        for ev in events:
            if ev["event"] == "card":
                self.assertEqual(ev["data"].get("card_type"), "alert_list")

    def test_32_sse_logs_query(self):
        """SSE: 日志查询含 card(log_list) + query_end."""
        resp = self.client.get("/api/ai/query-stream", params={"query": "日志"}, headers=self.headers)
        events = parse_sse_events(resp.text)
        card_types = [ev["data"].get("card_type") for ev in events if ev["event"] == "card"]
        self.assertIn("log_list", card_types)

    def test_33_sse_hosts_query(self):
        """SSE: 主机查询含 card(host_list) + query_end."""
        resp = self.client.get("/api/ai/query-stream", params={"query": "主机"}, headers=self.headers)
        events = parse_sse_events(resp.text)
        card_types = [ev["data"].get("card_type") for ev in events if ev["event"] == "card"]
        self.assertIn("host_list", card_types)

    def test_34_sse_cases_query(self):
        """SSE: 案件查询含 card(case_list) + query_end."""
        resp = self.client.get("/api/ai/query-stream", params={"query": "案件"}, headers=self.headers)
        events = parse_sse_events(resp.text)
        card_types = [ev["data"].get("card_type") for ev in events if ev["event"] == "card"]
        self.assertIn("case_list", card_types)

    def test_35_sse_stats_query(self):
        """SSE: 统计查询含 card(stats_chart) + query_end."""
        resp = self.client.get("/api/ai/query-stream", params={"query": "统计"}, headers=self.headers)
        events = parse_sse_events(resp.text)
        card_types = [ev["data"].get("card_type") for ev in events if ev["event"] == "card"]
        self.assertIn("stats_chart", card_types)

    def test_36_sse_policies_query(self):
        """SSE: 策略查询含 card(policy_list) + query_end."""
        resp = self.client.get("/api/ai/query-stream", params={"query": "策略"}, headers=self.headers)
        events = parse_sse_events(resp.text)
        card_types = [ev["data"].get("card_type") for ev in events if ev["event"] == "card"]
        self.assertIn("policy_list", card_types)

    # ================================================================
    # 5. 认证要求
    # ================================================================

    def test_37_generate_report_requires_auth(self):
        """generate-report 无认证返回 401."""
        resp = self.client.get("/api/ai/generate-report", params={"query": "test"})
        self.assertEqual(resp.status_code, 401)

    def test_38_query_stream_requires_auth(self):
        """query-stream 无认证返回 401."""
        resp = self.client.get("/api/ai/query-stream", params={"query": "test"})
        self.assertEqual(resp.status_code, 401)

    # ================================================================
    # 6. 前端构建验证
    # ================================================================

    def test_99_frontend_build(self):
        """前端 vite build 通过."""
        frontend_dir = BACKEND_DIR.parent / "frontend"
        build_result = os.system(f"cd {frontend_dir} && npx vite build 2>&1")
        self.assertEqual(build_result, 0, "vite build 失败")


# ============================================================
# 人工验证步骤清单
# ============================================================

MANUAL_VERIFICATION_STEPS = """
## 人工验证步骤清单

请在浏览器打开 http://127.0.0.1:5175 ，登录后进入 AI 实验室 → 自然语言指挥台，逐项验证：

### ✅ 功能 1: 消息操作菜单
1. [ ] 发送一条查询，AI 回复后鼠标 hover 到 AI 消息右上角
2. [ ] 看到 `···` 按钮弹出
3. [ ] 点击 `···` 弹出下拉菜单: 复制内容 / 引用追问 / 有用 / 没用 / 这不是我要的
4. [ ] 点击"复制内容"检查剪贴板
5. [ ] 点击"引用追问"检查输入框自动插入 `> ` 前缀
6. [ ] 点击"这不是我要的"检查自动重新查询

### ✅ 功能 2: 时间范围Pill
7. [ ] 输入"过去24小时严重的告警"，输入框下方出现蓝色 time pill
8. [ ] pill 显示"过去24小时"文本，可点击 x 清除
9. [ ] 测试"近7天"、"今天"、"昨天"、"本周"、"上周"

### ✅ 功能 3: 输入区智能补全
10. [ ] 输入框使用 el-autocomplete
11. [ ] 输入 `/` 或 `@` 或任意文本触发下拉建议
12. [ ] 显示 7 个模板查询 + 历史会话匹配

### ✅ 功能 4: 告警批量处置
13. [ ] 查询"告警"，告警卡片左侧有 el-checkbox
14. [ ] 勾选 1 条以上告警，输入区下方浮起 batch-bar
15. [ ] batch-bar 含：封锁IP / 隔离主机 / 导出 / 取消

### ✅ 功能 5: 意图修正反馈
16. [ ] 同功能1中的"这不是我要的"菜单项
17. [ ] 点击后自动用原查询+"换一种方式"重新查询

### ✅ 功能 6: 多轮复合查询
18. [ ] 第一轮查询后，chatContext.workingSet 记录结果 ID 集合
19. [ ] 第二轮可以用"它/该/这些"引用上一轮结果

### ✅ 功能 7: 对话导出
20. [ ] 页面头部可见"导出对话"按钮
21. [ ] 选择历史对话后点击按钮，下载 .md 文件
22. [ ] 检查 .md 文件内容格式正确

### ✅ 功能 8: 查询性能洞察
23. [ ] 发送任意查询，流结束后 AI 文本尾部追加 `⚡ Xms · Y条`
24. [ ] 再次不同查询，确认每次都有性能标签

### ✅ 功能 9: 报表生成
25. [ ] 页面头部可见"生成报告"按钮
26. [ ] 点击后 loading 状态后，消息区出现安全态势报告消息
27. [ ] 报告含 summary + sections + suggestions

### ✅ 功能 10: ECharts 仪表盘
28. [ ] 查询"统计"，stats 卡片顶部显示数字网格
29. [ ] 数字下方有小型 ECharts 饼图（日志/告警/未处理）
"""


if __name__ == "__main__":
    unittest.main(verbosity=2)
