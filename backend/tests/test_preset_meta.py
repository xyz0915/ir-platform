"""Test: pipeline_presets 元数据字段（author/category/tags/usage_count/last_used_at）.

覆盖 commit 97028159 引入的 PipelinePresetModel 新能力：
  - create 带元数据 / 默认值
  - increment_usage（usage_count +1、last_used_at 非空、不存在返回 False）
  - update_meta（白名单：category/tags/description，白名单外字段不生效）
  - list() / get() tags 解析为数组
  - 清理测试数据

使用 conftest 的 db_path fixture（独立临时 SQLite），不污染真实库。
"""

import pytest

from app.models.agent_definition import PipelinePresetModel

pytestmark = pytest.mark.usefixtures("db_path")


def _make_preset(name: str = "p_meta_test", **kw) -> dict:
    data = {
        "name": name,
        "description": "desc",
        "agents": ["a1", "a2"],
        "author": "alice",
        "category": "分析",
        "tags": ["tag1", "tag2"],
    }
    data.update(kw)
    return PipelinePresetModel.create(data)


@pytest.fixture(autouse=True)
def _cleanup():
    """每个用例后清理本文件创建的预设，避免 UNIQUE(name) 冲突。"""
    yield
    for p in PipelinePresetModel.list():
        if str(p.get("name", "")).startswith("p_meta_test"):
            PipelinePresetModel.delete(p["id"])


class TestCreateMeta:
    def test_create_with_meta_roundtrip(self):
        p = _make_preset()
        got = PipelinePresetModel.get(p["id"])
        assert got["author"] == "alice"
        assert got["category"] == "分析"
        assert got["tags"] == ["tag1", "tag2"]
        assert isinstance(got["tags"], list)
        assert got["usage_count"] == 0
        assert got["last_used_at"] is None
        assert got["agents"] == ["a1", "a2"]

    def test_create_defaults(self):
        p = PipelinePresetModel.create({"name": "p_meta_test_defaults", "agents": ["x"]})
        got = PipelinePresetModel.get(p["id"])
        assert got["author"] == ""
        assert got["category"] == "other"
        assert got["tags"] == []
        assert isinstance(got["tags"], list)
        assert got["usage_count"] == 0

    def test_create_tags_not_list_graceful(self):
        # 非 list 的 tags 存为字符串；读取时 JSON 解析失败降级为 []（不抛异常）
        p = PipelinePresetModel.create(
            {"name": "p_meta_test_strtags", "agents": ["x"], "tags": "notalist"}
        )
        got = PipelinePresetModel.get(p["id"])
        assert got["tags"] == []  # _d 解析失败回退默认值


class TestIncrementUsage:
    def test_increment(self):
        p = _make_preset("p_meta_test_inc")
        assert p["usage_count"] == 0
        ok = PipelinePresetModel.increment_usage(p["id"])
        assert ok is True
        got = PipelinePresetModel.get(p["id"])
        assert got["usage_count"] == 1
        assert got["last_used_at"]  # 非空

    def test_increment_twice(self):
        p = _make_preset("p_meta_test_inc2")
        PipelinePresetModel.increment_usage(p["id"])
        PipelinePresetModel.increment_usage(p["id"])
        got = PipelinePresetModel.get(p["id"])
        assert got["usage_count"] == 2

    def test_increment_missing_returns_false(self):
        assert PipelinePresetModel.increment_usage(99999999) is False


class TestUpdateMeta:
    def test_update_category_tags(self):
        p = _make_preset("p_meta_test_upd")
        got = PipelinePresetModel.update_meta(
            p["id"], category="处置", tags=["t9", "t8"]
        )
        assert got["category"] == "处置"
        assert got["tags"] == ["t9", "t8"]
        assert isinstance(got["tags"], list)

    def test_update_whitelist_ignores_name(self):
        p = _make_preset("p_meta_test_ign")
        orig_name = p["name"]
        got = PipelinePresetModel.update_meta(p["id"], name="HACKED", agents=["zzz"])
        assert got["name"] == orig_name  # name 未被改
        assert got["agents"] == ["a1", "a2"]  # agents 未被改

    def test_update_meta_missing_returns_none(self):
        assert PipelinePresetModel.update_meta(99999999, category="x") is None

    def test_update_meta_empty_kwargs_returns_current(self):
        p = _make_preset("p_meta_test_nokw")
        got = PipelinePresetModel.update_meta(p["id"])
        assert got["id"] == p["id"]


class TestListTags:
    def test_list_parses_tags(self):
        _make_preset("p_meta_test_list", tags=["aa", "bb"])
        rows = PipelinePresetModel.list()
        target = [r for r in rows if r["name"] == "p_meta_test_list"]
        assert len(target) == 1
        assert target[0]["tags"] == ["aa", "bb"]
        assert isinstance(target[0]["tags"], list)
