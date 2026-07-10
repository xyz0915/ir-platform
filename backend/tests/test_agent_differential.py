#!/usr/bin/env python3
"""Agent 差分采集 + 可靠性（任务③）单元测试.

覆盖：
  - diff.compute_diff：列表 added/removed、字典 added/changed
  - CollectorHealth：record / build 结构（符合 §3.2）
  - run_collectors：单采集器超时/异常降级为 failed + 空结构；进程为空 → degraded + 告警
  - build_output：注入 collection_health 顶层字段
"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
AGENT_DIR = PROJECT_ROOT / "agent"
for p in (str(PROJECT_ROOT), str(AGENT_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from utils.diff import compute_diff, load_baseline, save_baseline  # noqa: E402
from utils._health import CollectorHealth  # noqa: E402
import agent  # noqa: E402
from collectors.base_collector import BaseCollector  # noqa: E402


class TestDiff(unittest.TestCase):
    def test_list_added_removed(self):
        base = {"processes": [{"pid": 1}, {"pid": 2}]}
        cur = {"processes": [{"pid": 2}, {"pid": 3}]}
        d = compute_diff(base, cur)
        self.assertIn("processes", d)
        self.assertEqual(d["processes"]["added"], [{"pid": 3}])
        self.assertEqual(d["processes"]["removed"], [{"pid": 1}])

    def test_dict_changed(self):
        base = {"registry": {"a": 1, "b": 2}}
        cur = {"registry": {"a": 1, "b": 3, "c": 4}}
        d = compute_diff(base, cur)
        self.assertIn("registry", d)
        self.assertEqual(d["registry"]["changed"], {"b": {"old": 2, "new": 3}})
        self.assertEqual(d["registry"]["added"], {"c": 4})
        self.assertEqual(d["registry"]["removed"], {})

    def test_no_diff_empty(self):
        base = {"x": [1, 2]}
        cur = {"x": [1, 2]}
        self.assertEqual(compute_diff(base, cur), {})

    def test_baseline_roundtrip(self):
        import json
        import tempfile
        raw = {"processes": [{"pid": 1}]}
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            path = f.name
            json.dump(raw, f)
        loaded = load_baseline(path)
        self.assertEqual(loaded, raw)
        Path(path).unlink()


class TestCollectorHealth(unittest.TestCase):
    def test_build_structure(self):
        h = CollectorHealth()
        h.record("processes", "degraded", 0, ["进程列表为空，可能影响关联分析"])
        h.record("network", "ok", 45)
        h.record("registry", "failed", 0, ["registry 采集失败"])
        out = h.build("2026-07-11 10:00:00")
        self.assertEqual(out["collected_at"], "2026-07-11 10:00:00")
        self.assertEqual(out["collectors"]["processes"]["status"], "degraded")
        self.assertEqual(out["collectors"]["network"]["count"], 45)
        self.assertIn("进程列表为空", out["warnings"][0])
        self.assertIn("1 failed", out["summary"])
        self.assertIn("1 degraded", out["summary"])


class TestRunCollectorsHealth(unittest.TestCase):
    def setUp(self):
        self._orig_map = agent.COLLECTOR_MAP
        self._orig_load = agent.load_collector
        self._orig_list = agent._LIST_COLLECTORS
        # 使用真实采集器名以便命中 _LIST_COLLECTORS / 进程空告警逻辑
        agent.COLLECTOR_MAP = {"users": "", "processes": "", "fake_fail": ""}
        # 让 fake_fail 走列表分支，降级返回 []
        agent._LIST_COLLECTORS = set(agent._LIST_COLLECTORS) | {"fake_fail"}

        def fake_load(name, log_days=7):
            class Fake(BaseCollector):
                platform = ["all"]

                def collect(self):
                    if name == "fake_fail":
                        raise RuntimeError("boom")
                    if name == "processes":
                        return []  # 空进程列表
                    return [{"pid": 1}]
            return Fake()

        agent.load_collector = fake_load

    def tearDown(self):
        agent.COLLECTOR_MAP = self._orig_map
        agent.load_collector = self._orig_load
        agent._LIST_COLLECTORS = self._orig_list

    def test_failed_collector_degrades(self):
        from utils._health import CollectorHealth
        health = CollectorHealth()
        results = agent.run_collectors(["fake_fail"], health=health)
        self.assertEqual(results["fake_fail"], [])  # 降级为空结构
        self.assertEqual(health.collectors["fake_fail"]["status"], "failed")

    def test_processes_empty_degraded(self):
        from utils._health import CollectorHealth
        health = CollectorHealth()
        results = agent.run_collectors(["processes"], health=health)
        self.assertEqual(results["processes"], [])
        rec = health.collectors["processes"]
        self.assertEqual(rec["status"], "degraded")
        self.assertTrue(any("进程列表为空" in w for w in rec["warnings"]))

    def test_ok_collector(self):
        from utils._health import CollectorHealth
        health = CollectorHealth()
        results = agent.run_collectors(["users"], health=health)
        self.assertEqual(results["users"], [{"pid": 1}])
        self.assertEqual(health.collectors["users"]["status"], "ok")


class TestBuildOutputHealth(unittest.TestCase):
    def test_injects_collection_health(self):
        from utils.output import build_output
        metadata = {"hostname": "h", "collection_time": "t"}
        health = {"collected_at": "t", "collectors": {}, "warnings": [], "summary": "all ok"}
        out = build_output(metadata, {}, collection_health=health)
        self.assertIn("collection_health", out)
        self.assertEqual(out["collection_health"]["summary"], "all ok")


if __name__ == "__main__":
    unittest.main()
