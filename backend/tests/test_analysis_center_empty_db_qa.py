#!/usr/bin/env python3
"""分析中心空库 500 —— 独立回归测试（QA 视角，独立于工程师的测试）.

背景与根因：
  分析中心页面（AnalysisCenterView）onMounted 会并发打 3 个接口：
    GET /api/analysis/events/stats?filter=matched   (fetchStats)
    GET /api/analysis/events/filters?filter=matched  (fetchFilterMeta)
    GET /api/analysis/events?filter=matched&page=1&page_size=20 (fetchRuleEvents)
  其中 event_stats() 与 ai_label 筛选（event_filter_service）都无条件引用
  security_events.ai_verdict 列。该列此前仅由 ai_noise_reduce 首次跑 AI 研判时
  懒添加，未跑过 AI 研判的空库缺少该列 →
  `sqlite3.OperationalError: no such column: se.ai_verdict` → HTTP 500，整页崩。

修复（工程师在 database.py）：
  security_events 建表 DDL 新增 ai_verdict 列；init_db() 新增幂等迁移函数
  _alter_security_events_add_ai_verdict(conn) 在启动时补齐该列。

本测试独立验证：
  R0. import app.main 无导入/语法错误（否则所有用例直接失败）。
  R1. 迁移确实生效：直连临时库 PRAGMA table_info(security_events) 断言存在
      ai_verdict 列（纯 schema 验证，不碰生产库）。
  R2. 空库下 3 个核心接口（filter=matched）均返回 200 且结构合法（空列表/零值）。
  R3. 防回归：filter=all 的 stats/filters/events 也应 200（防止"修东墙破西墙"）。
  R4. ai_label 三类筛选（recommended/suspicious/false_positive）同样引用 ai_verdict，
      空库下应 200 而非 500。

隔离策略（关键）：
  - 在任何 app 导入之前，把 settings.DB_PATH / DATA_DIR / UPLOAD_DIR / AGENT_DIR
    指向独立临时目录，绝不指向生产库 backend/data/ir_platform.db，也绝不做任何手工 ALTER。
  - 用 TestClient.__enter__() 触发 startup -> init_db()，由代码自身补齐 ai_verdict 列。

运行方式：
    cd backend
    venv\\Scripts\\python.exe -m pytest tests\\test_analysis_center_empty_db_qa.py -v
"""

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

# ── 0. 路径与隔离：在任何 app 导入之前完成 ─────────────────────────────────
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

_TMP = tempfile.TemporaryDirectory()
_TMP_PATH = Path(_TMP.name)

# 仅在导入 config 后才覆盖，确保覆盖生效（config 是模块级单例）。
from app.config import settings  # noqa: E402

# DATA_DIR 必须保持 Path（其它模块会做 DATA_DIR / "xxx" 运算）；
# 仅落盘路径（DB_PATH / UPLOAD_DIR / AGENT_DIR）转 str。
settings.DB_PATH = str(_TMP_PATH / "ir_platform.db")
settings.DATA_DIR = _TMP_PATH
settings.UPLOAD_DIR = str(_TMP_PATH / "imports")
settings.AGENT_DIR = str(_TMP_PATH / "agent")

# R0: import app.main 本身即验证（导入失败会令后续用例直接 error）。
from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402


class TestAnalysisCenterEmptyDbQA(unittest.TestCase):
    """空库下分析中心核心接口不应 500（独立 QA 回归）."""

    @classmethod
    def setUpClass(cls):
        """启动 TestClient 触发 startup -> init_db（补齐 ai_verdict 列 + 种入 admin）."""
        cls.client = TestClient(app)
        cls.client.__enter__()
        cls.db_path = settings.DB_PATH
        # R1: 直连临时库，确认迁移写入了 ai_verdict 列（只读，不碰生产库）。
        conn = sqlite3.connect(cls.db_path)
        try:
            conn.row_factory = sqlite3.Row
            cols = [r["name"] for r in conn.execute(
                "PRAGMA table_info(security_events)"
            ).fetchall()]
        finally:
            conn.close()
        cls.security_events_columns = cols
        # 登录拿 token（admin/admin123 由 init_db 种入）。
        resp = cls.client.post(
            "/api/auth/login", json={"username": "admin", "password": "admin123"}
        )
        assert resp.status_code == 200, f"admin 登录失败: {resp.text}"
        cls.token = resp.json().get("data", {}).get("token")
        cls.headers = {"Authorization": f"Bearer {cls.token}"}

    @classmethod
    def tearDownClass(cls):
        try:
            cls.client.__exit__(None, None, None)
        except Exception:
            pass
        _TMP.cleanup()

    # ── R1. 迁移验证 ───────────────────────────────────────────
    def test_00_migration_added_ai_verdict_column(self):
        """init_db 必须为 security_events 补齐 ai_verdict 列（根因修复点）."""
        self.assertIn(
            "ai_verdict",
            self.security_events_columns,
            "security_events 缺少 ai_verdict 列，event_stats 仍会 500",
        )

    # ── R2. 核心接口（filter=matched）──────────────────────────
    def test_01_stats_matched_returns_200_with_zero_ints(self):
        """曾稳定 500 的 event_stats（filter=matched）空库下应 200 且计数均为 int 零值."""
        resp = self.client.get(
            "/api/analysis/events/stats",
            params={"filter": "matched"},
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 200, f"event_stats 仍 500: {resp.text}")
        data = resp.json().get("data", {})
        for key in (
            "total_events",
            "matched_events",
            "unmatched_events",
            "distinct_rules_hit",
            "today_new",
            "today_matched",
            "ai_recommended",
            "ai_suspicious",
            "ai_false_positive",
        ):
            self.assertIn(key, data, f"stats 缺少字段 {key}")
            self.assertIsInstance(data[key], int, f"{key} 应为 int，实际 {type(data[key])}")
            self.assertEqual(data[key], 0, f"空库下 {key} 应为 0，实际 {data[key]}")

    def test_02_filters_matched_returns_200_with_empty_lists(self):
        """fetchFilterMeta（filter=matched）空库下应 200 且 cases/hosts/hit_rules 为空列表."""
        resp = self.client.get(
            "/api/analysis/events/filters",
            params={"filter": "matched"},
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 200, f"filters 仍 500: {resp.text}")
        data = resp.json().get("data", {})
        self.assertEqual(data.get("cases", None), [], f"cases 应为 []，实际 {data.get('cases')}")
        self.assertEqual(data.get("hosts", None), [], f"hosts 应为 []，实际 {data.get('hosts')}")
        self.assertEqual(data.get("hit_rules", None), [], f"hit_rules 应为 []，实际 {data.get('hit_rules')}")

    def test_03_events_matched_returns_200_with_empty_items(self):
        """fetchRuleEvents（filter=matched）空库下应 200 且 items=[] total=0."""
        resp = self.client.get(
            "/api/analysis/events",
            params={"filter": "matched", "page": 1, "page_size": 20},
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 200, f"events list 仍 500: {resp.text}")
        data = resp.json().get("data", {})
        self.assertEqual(data.get("items", None), [], f"items 应为 []，实际 {data.get('items')}")
        self.assertEqual(data.get("total", None), 0, f"total 应为 0，实际 {data.get('total')}")
        self.assertEqual(
            data.get("stats", {}).get("total"), 0,
            f"stats.total 应为 0，实际 {data.get('stats', {}).get('total')}",
        )

    # ── R3. 防回归：filter=all 也应 200 ────────────────────────
    def test_04_stats_all_returns_200(self):
        """对照：filter=all 的 stats 也应 200."""
        resp = self.client.get("/api/analysis/events/stats", params={}, headers=self.headers)
        self.assertEqual(resp.status_code, 200, f"stats(all) 仍 500: {resp.text}")

    def test_05_filters_all_returns_200(self):
        """对照：filter=all 的 filters 也应 200."""
        resp = self.client.get(
            "/api/analysis/events/filters", params={"filter": "all"}, headers=self.headers
        )
        self.assertEqual(resp.status_code, 200, f"filters(all) 仍 500: {resp.text}")

    def test_06_events_all_returns_200(self):
        """对照：filter=all 的 events list 也应 200 且结构合法."""
        resp = self.client.get(
            "/api/analysis/events",
            params={"filter": "all", "page": 1, "page_size": 20},
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 200, f"events(all) 仍 500: {resp.text}")
        data = resp.json().get("data", {})
        self.assertIsInstance(data.get("items"), list)
        self.assertIsInstance(data.get("total"), int)

    # ── R4. ai_label 筛选路径（同样引用 ai_verdict）────────────
    def test_07_ai_label_filter_path_does_not_crash(self):
        """ai_label 三类筛选（recommended/suspicious/false_positive）空库下应 200 而非 500."""
        for label in ("recommended", "suspicious", "false_positive"):
            resp = self.client.get(
                "/api/analysis/events",
                params={"ai_label": label, "page": 1, "page_size": 20},
                headers=self.headers,
            )
            self.assertEqual(
                resp.status_code, 200, f"ai_label={label} 仍 500: {resp.text}"
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
