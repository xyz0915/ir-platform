"""单元测试：_lookup_event 弹性查询函数.

覆盖场景：
- 直接 ID 匹配成功
- cm:suspicious_startup_items:130 精确匹配
- cmsuspicious_startup_items130 模糊匹配（slug → 还原为 cm:suspicious_startup_items:130）
- 找不到时返回 None（不抛异常）

安全红线：使用 IsolatedDBTestCase（临时 SQLite），绝不触碰 backend/data/ir.db。
"""

import json
from typing import Any

from app.database import get_connection

from tests._qa_batch1_common import IsolatedDBTestCase


def _insert_event(conn, event_id: str, event_key: str,
                  host_id: int = 1, event_type: str = "test",
                  severity: str = "medium", timestamp: str = "2026-07-18 10:00:00",
                  evidence: dict | None = None,
                  related_events: list | None = None) -> dict[str, Any]:
    """向 security_events 表插入一条测试事件，返回完整行。"""
    conn.execute(
        """INSERT INTO security_events
           (id, timestamp, host_id, event_type, severity, source_collector,
            event_key, attack_chain_id, attack_stage, ioc_matches, evidence,
            ai_verdict, status, assignee, related_events, matched_rules)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            event_id,
            timestamp,
            host_id,
            event_type,
            severity,
            "test_collector",
            event_key,
            None,
            "initial_access",
            "[]",
            json.dumps(evidence or {}, ensure_ascii=False),
            "{}",
            "pending",
            None,
            json.dumps(related_events or [], ensure_ascii=False),
            "[]",
        ),
    )
    return dict(conn.execute(
        "SELECT * FROM security_events WHERE id = ?", (event_id,)
    ).fetchone())


class TestLookupEvent(IsolatedDBTestCase):
    """_lookup_event 单元测试套件。"""

    def _lookup(self, event_id: str, join_hosts: bool = False):
        """调用 _lookup_event 并返回结果。"""
        from app.api.events import _lookup_event
        with get_connection() as conn:
            return _lookup_event(conn, event_id, join_hosts=join_hosts)

    # ── 场景 1: 直接 ID 精确匹配 ──────────────────────────────────

    def test_exact_id_match(self):
        """security_events.id 精确匹配成功时返回行。"""
        with get_connection() as conn:
            _insert_event(conn, "cm:suspicious_startup_items:130",
                          "suspicious_startup_items:130")

        row = self._lookup("cm:suspicious_startup_items:130")
        self.assertIsNotNone(row)
        self.assertEqual(row["id"], "cm:suspicious_startup_items:130")
        self.assertEqual(row["event_type"], "test")

    # ── 场景 2: event_key 精确匹配 ────────────────────────────────

    def test_event_key_match(self):
        """主键 id 不匹配但 event_key 匹配时返回行。"""
        with get_connection() as conn:
            _insert_event(conn, "cm:test_event:99",
                          "suspicious_startup_items:130")

        # 用 event_key 查询
        row = self._lookup("suspicious_startup_items:130")
        self.assertIsNotNone(row)
        self.assertEqual(row["id"], "cm:test_event:99")
        self.assertEqual(row["event_key"], "suspicious_startup_items:130")

    # ── 场景 3: cm:suspicious_startup_items:130 精确匹配（主路径）──

    def test_cm_colon_format_match(self):
        """cm:suspicious_startup_items:130 格式精确匹配。"""
        with get_connection() as conn:
            _insert_event(conn, "cm:suspicious_startup_items:130",
                          "suspicious_startup_items:130")

        row = self._lookup("cm:suspicious_startup_items:130")
        self.assertIsNotNone(row)
        self.assertEqual(row["id"], "cm:suspicious_startup_items:130")

    # ── 场景 4: cmsuspicious_startup_items130 模糊匹配 ──────────

    def test_slug_fuzzy_match(self):
        """无冒号 slug 格式 cmsuspicious_startup_items130 → 匹配 cm:suspicious_startup_items:130。"""
        with get_connection() as conn:
            _insert_event(conn, "cm:suspicious_startup_items:130",
                          "suspicious_startup_items:130")

        row = self._lookup("cmsuspicious_startup_items130")
        self.assertIsNotNone(row)
        self.assertEqual(row["id"], "cm:suspicious_startup_items:130")

    def test_slug_fuzzy_match_abnormal_processes(self):
        """测试另一类事件：cmabnormal_processes551 → cm:abnormal_processes:551。"""
        with get_connection() as conn:
            _insert_event(conn, "cm:abnormal_processes:551",
                          "abnormal_processes:551")

        row = self._lookup("cmabnormal_processes551")
        self.assertIsNotNone(row)
        self.assertEqual(row["id"], "cm:abnormal_processes:551")

    def test_slug_fuzzy_match_single_digit(self):
        """测试数字为个位数的情况：cmsuspicious_conn20 → cm:suspicious_conn:20。"""
        with get_connection() as conn:
            _insert_event(conn, "cm:suspicious_conn:20",
                          "suspicious_conn:20")

        row = self._lookup("cmsuspicious_conn20")
        self.assertIsNotNone(row)
        self.assertEqual(row["id"], "cm:suspicious_conn:20")

    # ── 场景 5: 找不到时返回 None（不抛异常）────────────────────

    def test_not_found_returns_none(self):
        """完全不存在的 ID 应返回 None，不抛异常。"""
        result = self._lookup("cm:nonexistent:999")
        self.assertIsNone(result)

    def test_not_found_slug_returns_none(self):
        """不存在的 slug 格式也应返回 None。"""
        result = self._lookup("cmdoes_not_exist_anything888")
        self.assertIsNone(result)

    def test_not_found_empty_string(self):
        """空字符串应返回 None。"""
        result = self._lookup("")
        self.assertIsNone(result)

    def test_not_found_garbage_string(self):
        """乱码字符串应返回 None，不抛异常。"""
        result = self._lookup("!!@@##__INVALID__!!")
        self.assertIsNone(result)

    # ── 场景 6: join_hosts=True 时的 JOIN 查询 ─────────────────

    def test_lookup_with_join_hosts(self):
        """join_hosts=True 时返回含主机/案件字段的 JOIN 结果。"""
        from app.database import get_connection
        with get_connection() as conn:
            conn.execute("INSERT INTO cases (id, name, case_number) VALUES (1, '测试案件', 'CASE-001')")
            conn.execute(
                "INSERT INTO hosts (id, case_id, hostname, ip_address) VALUES (1, 1, 'test-host', '192.168.1.1')"
            )
            _insert_event(conn, "cm:suspicious_startup_items:130",
                          "suspicious_startup_items:130", host_id=1)

        from app.api.events import _lookup_event
        with get_connection() as conn2:
            row = _lookup_event(conn2, "cm:suspicious_startup_items:130", join_hosts=True)

        self.assertIsNotNone(row)
        self.assertEqual(row["hostname"], "test-host")
        self.assertEqual(row["ip_address"], "192.168.1.1")
        self.assertEqual(row["case_name"], "测试案件")
        self.assertEqual(row["case_number"], "CASE-001")
