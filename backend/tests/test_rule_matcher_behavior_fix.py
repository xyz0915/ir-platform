"""规则匹配引擎 — 行为规则根因修复测试（v2.1）.

验证两处根因修复：
  1. _EVENT_TYPE_CATEGORY_MAP 现对 process_start/process_terminate 路由到 "behavior"，
     使 26 条行为规则（orphan_process 等）能作为候选加载（此前永不执行）。
  2. orphan_process / child_of_office / child_of_browser 在父进程信息缺失（None/空）时
     不再误判为命中（修复 str(None)=="none" 导致 "explorer" not in "none" 恒 True）。

使用方法:
    pytest backend/tests/test_rule_matcher_behavior_fix.py -v
"""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import os
import unittest
from contextlib import contextmanager
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services import rule_matcher
from app.services.rule_matcher import match_event


def _build_rules_db(path: str) -> None:
    """构造一个仅含行为规则的临时库，用于验证候选加载。"""
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE rules (id INTEGER PRIMARY KEY, name TEXT, rule_type TEXT, "
        "category TEXT, severity TEXT, condition TEXT, enabled INTEGER, "
        "engine_type TEXT)"
    )
    behavior_rules = [
        (11, "orphan_process", "behavior", "behavior", "high", json.dumps({"pattern": "orphan_process"}), 1, None),
        (12, "suspicious_parent_child", "behavior", "behavior", "medium", json.dumps({"pattern": "child_of_office"}), 1, None),
        (13, "unsigned_process", "behavior", "behavior", "medium", json.dumps({"pattern": "child_of_browser"}), 1, None),
        (95, "process_chain_attack", "behavior", "behavior", "critical", json.dumps({"pattern": "process_chain_attack"}), 1, None),
    ]
    conn.executemany(
        "INSERT INTO rules (id, name, rule_type, category, severity, condition, enabled, engine_type) "
        "VALUES (?,?,?,?,?,?,?,?)", behavior_rules
    )
    conn.commit()
    conn.close()


class TestBehaviorRuleLoading(unittest.TestCase):
    """验证行为规则现可被 process 事件加载并匹配。"""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        _build_rules_db(self.tmp.name)
        self.conn = sqlite3.connect(self.tmp.name)
        self.conn.row_factory = sqlite3.Row
        rule_matcher._rule_cache.clear()
        # 使用旧 matcher 灰度路径（与 DB patching 兼容）
        rule_matcher.USE_UNIFIED_ENGINE = False

    def tearDown(self):
        self.conn.close()
        os.unlink(self.tmp.name)

    @contextmanager
    def _patch_db(self):
        @contextmanager
        def _fake():
            yield self.conn
        with patch("app.services.rule_matcher.get_connection", _fake):
            yield

    def test_orphan_process_matches_when_ppid_zero(self):
        """ppid==0 的进程事件应命中 orphan_process（核心行为检测恢复）。"""
        with self._patch_db():
            event = {"id": "e1", "event_type": "process_start",
                     "severity": "high",
                     "evidence": {"process_name": "x.exe", "ppid": 0, "parent_name": ""}}
            result = match_event(event)
        names = {r["rule_name"] for r in result}
        self.assertIn("orphan_process", names)
        orphan = next(r for r in result if r["rule_name"] == "orphan_process")
        self.assertEqual(orphan["confidence"], 0.75)

    def test_orphan_process_no_match_when_parent_missing(self):
        """父进程信息缺失（parent_name=None）的事件不应被误判为孤儿（修复点）。"""
        with self._patch_db():
            event = {"id": "e2", "event_type": "process_start",
                     "severity": "high",
                     "evidence": {"process_name": "y.exe", "ppid": 1234}}
            result = match_event(event)
        names = {r["rule_name"] for r in result}
        self.assertNotIn("orphan_process", names)

    def test_orphan_process_no_match_when_legit_parent(self):
        """父进程为 explorer.exe 的进程不应被判孤儿。"""
        with self._patch_db():
            event = {"id": "e3", "event_type": "process_start",
                     "severity": "high",
                     "evidence": {"process_name": "z.exe", "ppid": 2234, "parent_name": "explorer.exe"}}
            result = match_event(event)
        names = {r["rule_name"] for r in result}
        self.assertNotIn("orphan_process", names)

    def test_child_of_browser_matches(self):
        """父进程为 chrome.exe 的进程应命中 child_of_browser（规则13 unsigned_process）。"""
        with self._patch_db():
            event = {"id": "e4", "event_type": "process_start",
                     "severity": "high",
                     "evidence": {"process_name": "powershell.exe", "parent_name": "chrome.exe"}}
            result = match_event(event)
        names = {r["rule_name"] for r in result}
        self.assertIn("unsigned_process", names)  # 规则13 pattern=child_of_browser
        self.assertNotIn("suspicious_parent_child", names)  # 规则12 是 child_of_office，不应命中

    def test_no_behavior_for_non_process_event(self):
        """非进程事件（如 network_outbound）不应加载行为规则。"""
        with self._patch_db():
            event = {"id": "e5", "event_type": "network_outbound",
                     "severity": "high",
                     "evidence": {"process_name": "x.exe", "ppid": 0, "parent_name": ""}}
            result = match_event(event)
        names = {r["rule_name"] for r in result}
        self.assertNotIn("orphan_process", names)


if __name__ == "__main__":
    unittest.main()
