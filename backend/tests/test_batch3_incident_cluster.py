"""第③批 T-D1 · IncidentCluster 模型 CRUD 单元测试.

覆盖（使用 _qa_batch1_common 隔离 SQLite，绝不触碰 ir.db）：
- create 返回的 cluster_id 以 ``ic-`` 前缀。
- list 支持 severity 过滤 + 分页，返回 ``{items,total,page,page_size}``。
- get / delete 正常。
- 非法 severity 自动归一为 medium。
- member_event_ids / host_ids / ai_verdict_agg 以 JSON 反序列化还原。
"""

import asyncio
import json
from pathlib import Path
from unittest.mock import patch

import sys
_THIS = Path(__file__).resolve().parent
_BACKEND = _THIS.parent
for _p in (str(_BACKEND), str(_THIS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from app.models.incident_cluster import IncidentCluster

from _qa_batch1_common import IsolatedDBTestCase


def _seed_clusters():
    """写入若干不同严重度的簇，返回 cluster_id 列表。"""
    ids = []
    ids.append(IncidentCluster.create(
        title="簇A", severity="critical", confidence=0.9,
        member_event_ids=["1", "2"], host_ids=["10"],
        summary="A", ai_verdict_agg={"labels": {"suspicious": 2}},
    ))
    ids.append(IncidentCluster.create(
        title="簇B", severity="high", confidence=0.7,
        member_event_ids=["3"], host_ids=["11"],
        summary="B", ai_verdict_agg={"labels": {"suspicious": 1}},
    ))
    ids.append(IncidentCluster.create(
        title="簇C", severity="medium", confidence=0.5,
        member_event_ids=["4", "5", "6"], host_ids=["10", "12"],
        summary="C", ai_verdict_agg={"labels": {"suspicious": 3}},
    ))
    return ids


class TestIncidentClusterCRUD(IsolatedDBTestCase):
    def test_create_returns_ic_prefix(self):
        cid = IncidentCluster.create(title="t", severity="high")
        self.assertTrue(cid.startswith("ic-"), f"cluster_id 应以 ic- 开头，实际: {cid}")
        self.assertEqual(len(cid), 3 + 12)  # "ic-" + 12 hex

    def test_get_returns_full_dict_with_json_fields(self):
        cid = IncidentCluster.create(
            title="json簇", severity="critical", confidence=0.81,
            member_event_ids=["1", "2", "3"], host_ids=["7", "8"],
            summary="聚合摘要",
            ai_verdict_agg={"labels": {"suspicious": 3}, "avg_confidence": 0.8},
        )
        row = IncidentCluster.get(cid)
        self.assertIsNotNone(row)
        self.assertEqual(row["title"], "json簇")
        self.assertEqual(row["severity"], "critical")
        self.assertAlmostEqual(row["confidence"], 0.81, places=2)
        # JSON 字段反序列化
        self.assertEqual(row["member_event_ids"], ["1", "2", "3"])
        self.assertEqual(row["host_ids"], ["7", "8"])
        self.assertEqual(row["ai_verdict_agg"]["avg_confidence"], 0.8)

    def test_invalid_severity_normalized_to_medium(self):
        cid = IncidentCluster.create(title="x", severity="bogus")
        row = IncidentCluster.get(cid)
        self.assertEqual(row["severity"], "medium")

    def test_list_pagination_shape_and_defaults(self):
        _seed_clusters()
        data = IncidentCluster.list()
        self.assertIn("items", data)
        self.assertIn("total", data)
        self.assertIn("page", data)
        self.assertIn("page_size", data)
        self.assertEqual(data["page"], 1)
        self.assertEqual(data["page_size"], 50)
        self.assertEqual(data["total"], 3)
        self.assertEqual(len(data["items"]), 3)

    def test_list_severity_filter(self):
        _seed_clusters()
        crit = IncidentCluster.list(severity="critical")
        self.assertEqual(crit["total"], 1)
        self.assertEqual(crit["items"][0]["severity"], "critical")
        # 不存在的严重度 → 空
        none = IncidentCluster.list(severity="low")
        self.assertEqual(none["total"], 0)
        self.assertEqual(none["items"], [])

    def test_list_pagination_slices(self):
        ids = _seed_clusters()
        # page_size=2，取第 1 页应 2 条，total 仍为 3
        p1 = IncidentCluster.list(page=1, page_size=2)
        self.assertEqual(len(p1["items"]), 2)
        self.assertEqual(p1["total"], 3)
        self.assertEqual(p1["page_size"], 2)
        p2 = IncidentCluster.list(page=2, page_size=2)
        self.assertEqual(len(p2["items"]), 1)
        self.assertEqual(p2["total"], 3)

    def test_delete_works_and_get_returns_none(self):
        cid = _seed_clusters()[0]
        self.assertTrue(IncidentCluster.delete(cid))
        self.assertIsNone(IncidentCluster.get(cid))
        # 重复删除返回 False
        self.assertFalse(IncidentCluster.delete(cid))


if __name__ == "__main__":
    import unittest
    unittest.main()
