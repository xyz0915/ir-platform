#!/usr/bin/env python3
"""分析中心页面空库 500 回归测试.

背景：分析中心页面（AnalysisCenterView）在 onMounted 会并发发起 3 个请求：
  - GET /api/analysis/events?filter=matched      (fetchRuleEvents)
  - GET /api/analysis/events/filters?filter=matched  (fetchFilterMeta)
  - GET /api/analysis/events/stats?filter=matched    (fetchStats)

此前 event_stats 直接引用 security_events.ai_verdict 列，而该列仅由
ai_noise_reduce 服务在首次运行 AI 研判时懒添加；未跑过 AI 研判的库
（含全新/空库）缺少该列，导致 event_stats 抛出
`sqlite3.OperationalError: no such column: se.ai_verdict` → HTTP 500，
整个分析中心页面加载失败。

根因修复：将 ai_verdict 提升为 security_events 的规范列（DDL + init_db 迁移），
任意库在启动时即具备该列。

本测试：独立临时 SQLite 库 + FastAPI TestClient（startup 触发 init_db 种入
默认 admin 并迁移 ai_verdict 列），断言上述接口在空库下均返回 200 且结构合法
（空列表 / 零值），并且 ai_label 筛选路径（同样引用 ai_verdict）也不崩。

运行方式:
    cd backend
    venv\\Scripts\\python.exe -m pytest tests\\test_analysis_center_empty_db.py -v
"""

import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

# ── 关键：在任何 app 导入之前，将数据库路径指向独立临时库，绝不触碰生产库 ──
_TMP = tempfile.TemporaryDirectory()
_TMP_DIR = _TMP.name
_TMP_PATH = Path(_TMP_DIR)

from app.config import settings  # noqa: E402

# 注意：DATA_DIR 必须保持 Path 类型（其它模块会做 DATA_DIR / "xxx" 运算），
# 只把需要字符串落盘的路径（DB_PATH / UPLOAD_DIR / AGENT_DIR）转为 str。
settings.DB_PATH = str(_TMP_PATH / "ir_platform.db")
settings.DATA_DIR = _TMP_PATH
settings.UPLOAD_DIR = str(_TMP_PATH / "imports")
settings.AGENT_DIR = str(_TMP_PATH / "agent")

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402


class TestAnalysisCenterEmptyDb(unittest.TestCase):
    """空库下分析中心核心接口不应 500."""

    @classmethod
    def setUpClass(cls):
        """启动 TestClient（触发 startup -> init_db 迁移 ai_verdict 列 + 种入 admin）."""
        cls.client = TestClient(app)
        cls.client.__enter__()
        # 确认迁移确实写入了 ai_verdict 列（不触碰生产库，只读临时库）
        conn = sqlite3.connect(settings.DB_PATH)
        conn.row_factory = sqlite3.Row
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(security_events)").fetchall()]
        conn.close()
        cls.has_ai_verdict = "ai_verdict" in cols
        # 登录拿 token
        resp = cls.client.post(
            "/api/auth/login", json={"username": "admin", "password": "admin123"}
        )
        cls.token = resp.json().get("data", {}).get("token")
        cls.headers = {"Authorization": f"Bearer {cls.token}"}

    @classmethod
    def tearDownClass(cls):
        try:
            cls.client.__exit__(None, None, None)
        except Exception:
            pass
        _TMP.cleanup()

    def test_00_migration_added_ai_verdict_column(self):
        """init_db 迁移必须为 security_events 补齐 ai_verdict 列（根因修复点）."""
        self.assertTrue(
            self.has_ai_verdict,
            "security_events 缺少 ai_verdict 列，event_stats 仍会 500",
        )

    def test_01_stats_matched_returns_200_not_500(self):
        """曾稳定 500 的 event_stats（filter=matched）在空库下应返回 200.

        回归点：此前抛 `no such column: se.ai_verdict`。
        """
        resp = self.client.get(
            "/api/analysis/events/stats",
            params={"filter": "matched"},
            headers=self.headers,
        )
        self.assertEqual(
            resp.status_code, 200, f"event_stats 仍 500: {resp.text}"
        )
        body = resp.json()
        data = body.get("data", {})
        # 关键计数应为 int 且为空库零值
        for key in ("total_events", "matched_events", "unmatched_events",
                    "distinct_rules_hit", "today_new", "today_matched",
                    "ai_recommended", "ai_suspicious", "ai_false_positive"):
            self.assertIn(key, data, f"stats 缺失字段 {key}")
            self.assertIsInstance(data[key], int, f"{key} 应为 int")
            self.assertEqual(data[key], 0, f"空库下 {key} 应为 0，实际 {data[key]}")

    def test_02_filters_matched_returns_200(self):
        """fetchFilterMeta 对应接口在空库下应返回 200 且结构合法."""
        resp = self.client.get(
            "/api/analysis/events/filters",
            params={"filter": "matched"},
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 200, f"filters 500: {resp.text}")
        data = resp.json().get("data", {})
        self.assertIsInstance(data.get("cases", []), list)
        self.assertIsInstance(data.get("hosts", []), list)
        self.assertIsInstance(data.get("hit_rules", []), list)
        self.assertIsInstance(data.get("severity_counts", []), list)

    def test_03_events_list_matched_returns_200(self):
        """fetchRuleEvents 对应接口在空库下应返回 200 且 items 为空列表."""
        resp = self.client.get(
            "/api/analysis/events",
            params={"filter": "matched", "page": 1, "page_size": 20},
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 200, f"events list 500: {resp.text}")
        data = resp.json().get("data", {})
        self.assertEqual(data.get("items", []), [])
        self.assertEqual(data.get("total", -1), 0)
        stats = data.get("stats", {})
        self.assertEqual(stats.get("total"), 0)

    def test_04_ai_label_filter_path_does_not_crash(self):
        """ai_label 筛选（suspicious / false_positive / recommended）同样引用 ai_verdict，
        空库下应返回 200 而非 500."""
        for label in ("recommended", "suspicious", "false_positive"):
            resp = self.client.get(
                "/api/analysis/events",
                params={"ai_label": label, "page": 1, "page_size": 20},
                headers=self.headers,
            )
            self.assertEqual(
                resp.status_code, 200,
                f"ai_label={label} 仍 500: {resp.text}",
            )

    def test_05_stats_filter_all_returns_200(self):
        """对照：filter=all 的 stats 也应 200."""
        resp = self.client.get(
            "/api/analysis/events/stats", params={}, headers=self.headers
        )
        self.assertEqual(resp.status_code, 200, f"stats(all) 500: {resp.text}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
