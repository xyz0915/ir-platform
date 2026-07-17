"""自然语言指挥台 v3.1 端到端测试.

测试范围（10 项新增功能）:
  1. 语义意图识别 — POST /api/ai/nl-understand
  2. 流式停止按钮 — 前端功能
  3. 查看更多/分页 — 前端功能
  4. 告警详情浮层面板 — 前端功能
  5. 可配置查询模板 — 前端功能
  6. 对话检索 — 前端功能
  7. 用户反馈闭环入库 — POST /api/ai/feedback, GET /api/ai/feedback/stats, GET /api/ai/feedback/list
  8. 一键处置预案 — GET /api/ai/presets
  9. 时间线回放 — 前端骨架函数
  10. Token用量与AI调用明细 — GET /api/ai/audit-log

运行方式:
    cd backend && venv/Scripts/python.exe -m pytest tests/test_ai_advanced_v31.py -v
    或
    cd backend && venv/Scripts/python.exe tests/test_ai_advanced_v31.py -v
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

# ============================================================
# Helpers
# ============================================================

TEST_DB_PATH = str(BACKEND_DIR / "data" / "test_ai_advanced_v31.db")


# ============================================================
# Test Suite
# ============================================================

class TestAiAdvancedV31(unittest.TestCase):
    """自然语言指挥台 v3.1 新增功能端到端测试."""

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

        # 插入一些种子数据 (用于 feedback 表测试 / 关联查询)
        with get_connection() as conn:
            # ai_feedback 种子数据
            conn.execute(
                "INSERT INTO ai_feedback (session_id, query, reply, rating, comment) VALUES (?, ?, ?, ?, ?)",
                ["sess-001", "严重的告警", "共 3 条严重告警", 1, "很有用"]
            )
            conn.execute(
                "INSERT INTO ai_feedback (session_id, query, reply, rating, comment) VALUES (?, ?, ?, ?, ?)",
                ["sess-002", "在线主机", "共 5 台在线主机", -1, "不准确"]
            )
            conn.execute(
                "INSERT INTO ai_feedback (session_id, query, reply, rating, comment) VALUES (?, ?, ?, ?, ?)",
                ["sess-003", "统计信息", "统计完成", 0, ""]
            )
            # ai_audit_log 种子数据 — 使用修复后 DDL 兼容的列名
            # DDL 列: model_name, total_tokens, latency_ms, endpoint (通过 ALTER TABLE 补充)
            conn.execute(
                "INSERT INTO ai_audit_log (endpoint, total_tokens, latency_ms, model_name, intent) VALUES (?, ?, ?, ?, ?)",
                ["/api/ai/query", 150, 320, "gpt-4o", "alerts"]
            )
            conn.execute(
                "INSERT INTO ai_audit_log (endpoint, total_tokens, latency_ms, model_name, intent) VALUES (?, ?, ?, ?, ?)",
                ["/api/ai/query", 200, 450, "gpt-4o", "stats"]
            )
            conn.execute(
                "INSERT INTO ai_audit_log (endpoint, total_tokens, latency_ms, model_name, intent) VALUES (?, ?, ?, ?, ?)",
                ["/api/ai/query-stream", 300, 1200, "gpt-4o", "hosts"]
            )
            conn.commit()

    # ================================================================
    # 1. 语义意图识别 — POST /api/ai/nl-understand
    # ================================================================

    def test_01_nl_understand_alerts_query(self):
        """nl-understand: '严重的告警' → intent=alerts (关键词降级)."""
        resp = self.client.post(
            "/api/ai/nl-understand",
            params={"query": "严重的告警"},
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("success"))
        self.assertIn("data", data)
        self.assertEqual(data["data"]["intent"], "alerts")

    def test_02_nl_understand_logs_query(self):
        """nl-understand: '登录失败的日志' → intent=logs (关键词降级)."""
        resp = self.client.post(
            "/api/ai/nl-understand",
            params={"query": "登录失败的日志"},
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data["data"]["intent"], "logs")

    def test_03_nl_understand_hosts_query(self):
        """nl-understand: '在线主机' → intent=hosts (关键词降级)."""
        resp = self.client.post(
            "/api/ai/nl-understand",
            params={"query": "在线主机"},
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data["data"]["intent"], "hosts")

    def test_04_nl_understand_cases_query(self):
        """nl-understand: '未结案件' → intent=cases (关键词降级)."""
        resp = self.client.post(
            "/api/ai/nl-understand",
            params={"query": "未结案件"},
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data["data"]["intent"], "cases")

    def test_05_nl_understand_stats_query(self):
        """nl-understand: '统计信息' → intent=stats (关键词降级)."""
        resp = self.client.post(
            "/api/ai/nl-understand",
            params={"query": "统计信息"},
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data["data"]["intent"], "stats")

    def test_06_nl_understand_empty_query(self):
        """nl-understand: 空查询 → intent=unknown."""
        resp = self.client.post(
            "/api/ai/nl-understand",
            params={"query": ""},
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data["data"]["intent"], "unknown")
        self.assertIn("请输入查询", data["data"]["explain"])

    def test_07_nl_understand_unknown_query(self):
        """nl-understand: 无关联查询 → intent=unknown (关键词降级)."""
        resp = self.client.post(
            "/api/ai/nl-understand",
            params={"query": "今天天气怎么样"},
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data["data"]["intent"], "unknown")
        self.assertIn("关键词降级", data["data"]["explain"])

    def test_08_nl_understand_response_format(self):
        """nl-understand 响应包含 intent/params/explain 字段."""
        resp = self.client.post(
            "/api/ai/nl-understand",
            params={"query": "严重的告警"},
            headers=self.headers,
        )
        data = resp.json().get("data", {})
        self.assertIn("intent", data)
        self.assertIn("params", data)
        self.assertIn("explain", data)

    # ================================================================
    # 2. 用户反馈闭环入库 — POST /api/ai/feedback
    # ================================================================

    def test_10_submit_feedback_useful(self):
        """feedback: 提交 '有用' 反馈成功."""
        resp = self.client.post(
            "/api/ai/feedback",
            params={
                "session_id": "sess-test-001",
                "query": "测试查询",
                "reply": "测试回复",
                "rating": 1,
                "comment": "很有用",
            },
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("success"))
        self.assertIn("反馈已记录", data["data"]["message"])

    def test_11_submit_feedback_useless(self):
        """feedback: 提交 '无用' 反馈成功."""
        resp = self.client.post(
            "/api/ai/feedback",
            params={
                "session_id": "sess-test-002",
                "query": "测试查询",
                "reply": "测试回复",
                "rating": -1,
                "comment": "不准确",
            },
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("success"))

    def test_12_submit_feedback_neutral(self):
        """feedback: 提交中性评分 (rating=0) 成功."""
        resp = self.client.post(
            "/api/ai/feedback",
            params={
                "session_id": "sess-test-003",
                "query": "测试查询",
                "reply": "测试回复",
                "rating": 0,
                "comment": "",
            },
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("success"))

    # ================================================================
    # 3. 用户反馈统计 — GET /api/ai/feedback/stats
    # ================================================================

    def test_14_feedback_stats_returns_total(self):
        """feedback/stats: 返回 total 字段."""
        resp = self.client.get("/api/ai/feedback/stats", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json().get("data", {})
        self.assertIn("total", data)
        # 3 条种子 + 刚插入的 3 条 = 6
        self.assertGreaterEqual(data["total"], 3)

    def test_15_feedback_stats_has_useful_and_useless(self):
        """feedback/stats: 返回 useful/useless 字段."""
        resp = self.client.get("/api/ai/feedback/stats", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json().get("data", {})
        self.assertIn("useful", data)
        self.assertIn("useless", data)
        self.assertIsInstance(data["useful"], int)
        self.assertIsInstance(data["useless"], int)

    def test_16_feedback_stats_response_format(self):
        """feedback/stats 返回标准 success+data 格式."""
        resp = self.client.get("/api/ai/feedback/stats", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        result = resp.json()
        self.assertTrue(result.get("success"))
        self.assertIn("data", result)

    # ================================================================
    # 4. 用户反馈列表 — GET /api/ai/feedback/list
    # ================================================================

    def test_17_feedback_list_returns_items(self):
        """feedback/list: 返回 items 列表."""
        resp = self.client.get("/api/ai/feedback/list", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json().get("data", {})
        self.assertIn("items", data)
        self.assertIsInstance(data["items"], list)
        self.assertGreater(len(data["items"]), 0)

    def test_18_feedback_list_has_total(self):
        """feedback/list: 返回 total 字段."""
        resp = self.client.get("/api/ai/feedback/list", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json().get("data", {})
        self.assertIn("total", data)
        self.assertIsInstance(data["total"], int)

    def test_19_feedback_list_pagination(self):
        """feedback/list: 分页参数 page/page_size 生效."""
        resp = self.client.get(
            "/api/ai/feedback/list",
            params={"page": 1, "page_size": 2},
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json().get("data", {})
        self.assertLessEqual(len(data["items"]), 2)

    def test_20_feedback_list_items_have_required_fields(self):
        """feedback/list: items 包含 session_id/query/rating/comment 字段."""
        resp = self.client.get("/api/ai/feedback/list", headers=self.headers)
        items = resp.json().get("data", {}).get("items", [])
        self.assertGreater(len(items), 0)
        item = items[0]
        self.assertIn("session_id", item)
        self.assertIn("query", item)
        self.assertIn("rating", item)
        self.assertIn("comment", item)

    # ================================================================
    # 5. 一键处置预案 — GET /api/ai/presets
    # ================================================================

    def test_22_presets_returns_list(self):
        """presets: 返回预案列表."""
        resp = self.client.get("/api/ai/presets", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("success"))
        self.assertIn("data", data)
        self.assertIsInstance(data["data"], list)

    def test_23_presets_contains_rdp_preset(self):
        """presets: 包含 'RDP 爆破应急' 预案."""
        resp = self.client.get("/api/ai/presets", headers=self.headers)
        presets = resp.json().get("data", [])
        names = [p["name"] for p in presets]
        self.assertIn("RDP 爆破应急", names)

    def test_24_presets_contains_webshell_preset(self):
        """presets: 包含 'Webshell 清除' 预案."""
        resp = self.client.get("/api/ai/presets", headers=self.headers)
        presets = resp.json().get("data", [])
        names = [p["name"] for p in presets]
        self.assertIn("Webshell 清除", names)

    def test_25_presets_contains_exfiltration_preset(self):
        """presets: 包含 '数据外泄响应' 预案."""
        resp = self.client.get("/api/ai/presets", headers=self.headers)
        presets = resp.json().get("data", [])
        names = [p["name"] for p in presets]
        self.assertIn("数据外泄响应", names)

    def test_26_presets_have_required_fields(self):
        """presets 每个预案含 name/description/tags/steps 字段."""
        resp = self.client.get("/api/ai/presets", headers=self.headers)
        presets = resp.json().get("data", [])
        for p in presets:
            self.assertIn("name", p)
            self.assertIn("description", p)
            self.assertIn("tags", p)
            self.assertIn("steps", p)

    def test_27_presets_minimum_count(self):
        """presets: 至少返回 3 个预置预案."""
        resp = self.client.get("/api/ai/presets", headers=self.headers)
        presets = resp.json().get("data", [])
        self.assertGreaterEqual(len(presets), 3)

    # ================================================================
    # 6. Token用量与AI调用明细 — GET /api/ai/audit-log
    # ================================================================

    def test_30_audit_log_returns_success(self):
        """audit-log: 返回 success=True."""
        resp = self.client.get("/api/ai/audit-log", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("success"))

    def test_31_audit_log_has_total_calls(self):
        """audit-log: 返回 total_calls 字段."""
        resp = self.client.get("/api/ai/audit-log", headers=self.headers)
        data = resp.json().get("data", {})
        self.assertIn("total_calls", data)
        self.assertGreaterEqual(data["total_calls"], 3)

    def test_32_audit_log_has_total_tokens(self):
        """audit-log: 返回 total_tokens 字段."""
        resp = self.client.get("/api/ai/audit-log", headers=self.headers)
        data = resp.json().get("data", {})
        self.assertIn("total_tokens", data)
        self.assertIsInstance(data["total_tokens"], (int, float))
        self.assertGreaterEqual(data["total_tokens"], 0)

    def test_33_audit_log_has_detail_list(self):
        """audit-log: 返回 detail 列表（按 endpoint 分组）."""
        resp = self.client.get("/api/ai/audit-log", headers=self.headers)
        data = resp.json().get("data", {})
        self.assertIn("detail", data)
        self.assertIsInstance(data["detail"], list)
        self.assertGreater(len(data["detail"]), 0)

    def test_34_audit_log_detail_has_required_fields(self):
        """audit-log detail 每条含 endpoint/calls/tokens/total_ms."""
        resp = self.client.get("/api/ai/audit-log", headers=self.headers)
        details = resp.json().get("data", {}).get("detail", [])
        for d in details:
            self.assertIn("endpoint", d)
            self.assertIn("calls", d)
            self.assertIn("tokens", d)
            self.assertIn("total_ms", d)

    def test_35_audit_log_days_param(self):
        """audit-log: 支持 days 参数."""
        resp = self.client.get(
            "/api/ai/audit-log",
            params={"days": 30},
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 200)

    # ================================================================
    # 7. 认证要求 — 所有端点无认证返回 401
    # ================================================================

    def test_40_nl_understand_requires_auth(self):
        """nl-understand 无认证返回 401."""
        resp = self.client.post("/api/ai/nl-understand", params={"query": "告警"})
        self.assertEqual(resp.status_code, 401)

    def test_41_feedback_requires_auth(self):
        """feedback 无认证返回 401."""
        resp = self.client.post("/api/ai/feedback", params={
            "session_id": "test", "query": "test", "reply": "test", "rating": 1,
        })
        self.assertEqual(resp.status_code, 401)

    def test_42_feedback_stats_requires_auth(self):
        """feedback/stats 无认证返回 401."""
        resp = self.client.get("/api/ai/feedback/stats")
        self.assertEqual(resp.status_code, 401)

    def test_43_presets_requires_auth(self):
        """presets 无认证返回 401."""
        resp = self.client.get("/api/ai/presets")
        self.assertEqual(resp.status_code, 401)

    def test_44_audit_log_requires_auth(self):
        """audit-log 无认证返回 401."""
        resp = self.client.get("/api/ai/audit-log")
        self.assertEqual(resp.status_code, 401)

    def test_45_feedback_list_requires_auth(self):
        """feedback/list 无认证返回 401."""
        resp = self.client.get("/api/ai/feedback/list")
        self.assertEqual(resp.status_code, 401)

    # ================================================================
    # 8. 前端构建验证
    # ================================================================

    def test_90_frontend_build(self):
        """前端 vite build 通过."""
        frontend_dir = BACKEND_DIR.parent / "frontend"
        if not (frontend_dir / "package.json").exists():
            self.skipTest("前端目录不存在，跳过构建测试")
        build_result = os.system(f"cd {frontend_dir} && npx vite build 2>&1")
        self.assertEqual(build_result, 0, "vite build 失败")


# ============================================================
# 人工验证步骤清单
# ============================================================

MANUAL_VERIFICATION_STEPS = """
## 人工验证步骤清单 (v3.1 新增功能)

请在浏览器打开 http://127.0.0.1:5175 ，登录后进入 AI 实验室 → 自然语言指挥台，逐项验证：

### ✅ 功能 1: 语义意图识别
1. [ ] 在输入框输入"严重的告警"，发送后查看返回结果是否正确识别为告警意图
2. [ ] 输入"登录失败的日志"，确认识别为日志意图
3. [ ] 输入"统计信息"，确认识别为统计意图
4. [ ] 输入无意义内容（如"今天天气"），确认意图为 unknown

### ✅ 功能 2: 流式停止按钮
5. [ ] 发送一条查询，等待流式回复开始输出
6. [ ] 确认输入框右侧出现红色 ⏹ 停止按钮
7. [ ] 点击按钮，确认 SSE 流终止，已收到内容保留
8. [ ] 确认按钮状态恢复正常（可再次输入）

### ✅ 功能 3: 查看更多/分页
9. [ ] 查询"告警"，告警卡片底部显示"查看更多 (N 条)"链接
10. [ ] 点击链接，确认卡片展开显示更多告警
11. [ ] 多次点击，确认 showMoreCount 每次增加 10

### ✅ 功能 4: 告警详情浮层面板
12. [ ] 查询"告警"，点击某条告警的标题
13. [ ] 确认右侧滑出 el-drawer 面板
14. [ ] 面板展示：严重度/规则/来源/主机/详情/进程/路径/时间
15. [ ] 面板底部按钮：封锁IP / 隔离主机 / 查看详情

### ✅ 功能 5: 可配置查询模板
16. [ ] 页面头部点击"模板管理"按钮
17. [ ] 弹窗显示当前模板列表
18. [ ] 点击"新增模板"输入名称和内容
19. [ ] 保存后刷新页面，确认模板持久化（localStorage）
20. [ ] 点击删除，确认模板被移除
21. [ ] 输入框输入时，确认自定义模板出现在补全建议中

### ✅ 功能 6: 对话检索
22. [ ] 页面顶部找到搜索框
23. [ ] 输入关键词（如"告警"）
24. [ ] 确认页面自动滚动到第一条匹配的消息

### ✅ 功能 7: 用户反馈闭环入库
25. [ ] 发送一条查询，hover 到 AI 消息右上角
26. [ ] 点击"有用"按钮，确认弹出"反馈已记录"提示
27. [ ] 再发一条查询，点击"没用"按钮，确认提示
28. [ ] 调 GET /api/ai/feedback/stats 查看统计是否更新
29. [ ] 调 GET /api/ai/feedback/list 查看反馈列表

### ✅ 功能 8: 一键处置预案
30. [ ] 调 GET /api/ai/presets 确认返回 3 个预案
31. [ ] 预案名称：RDP爆破应急 / Webshell清除 / 数据外泄响应
32. [ ] 每条预案包含 name/description/tags/steps

### ✅ 功能 9: 时间线回放
33. [ ] 点击告警浮层，确认时间线回放入口
34. [ ] 点击回放按钮，确认逐条切换查看
35. [ ] 确认回放过程中高亮当前事件

### ✅ 功能 10: Token用量与AI调用明细
36. [ ] 调 GET /api/ai/audit-log 确认返回调用统计
37. [ ] 确认 total_calls / total_tokens / detail 字段
38. [ ] 发送一条 SSE 流式查询
39. [ ] 再次调 audit-log，确认新调用被记录
"""


if __name__ == "__main__":
    unittest.main(verbosity=2)
