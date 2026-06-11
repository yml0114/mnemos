"""Tests for mnemos.viz.data_provider module."""

import pytest
import tempfile
import os
from mnemos.storage.palimpsest import PalimpsestStore
from mnemos.viz.data_provider import DashboardProvider


@pytest.fixture
def store():
    """创建临时数据库"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    s = PalimpsestStore(path)
    s.connect()
    yield s
    s.close()
    os.unlink(path)


@pytest.fixture
def provider(store):
    """创建 DashboardProvider 实例"""
    return DashboardProvider(store)


@pytest.fixture
def store_with_data(store):
    """填充测试数据的 store"""
    from mnemos.core.models import MemoryEntry, MemoryTier, ScopeType, EntityRef

    # 添加记忆条目
    entry1 = MemoryEntry(
        entry_id="test-1",
        content="Python is a programming language",
        title="Python",
        tier=MemoryTier.IMPRESSION,
        scope_type=ScopeType.UNIVERSE,
        entities=[EntityRef(label="Python"), EntityRef(label="Programming")],
        tags=["tech", "programming"],
    )
    entry2 = MemoryEntry(
        entry_id="test-2",
        content="JavaScript is used for web development",
        title="JavaScript",
        tier=MemoryTier.IMPRESSION,
        scope_type=ScopeType.UNIVERSE,
        entities=[EntityRef(label="JavaScript"), EntityRef(label="Web")],
        tags=["tech", "web"],
    )
    entry3 = MemoryEntry(
        entry_id="test-3",
        content="Machine learning is a subset of AI",
        title="ML",
        tier=MemoryTier.IMPRESSION,
        scope_type=ScopeType.UNIVERSE,
        entities=[EntityRef(label="Machine Learning"), EntityRef(label="AI")],
        tags=["ai", "tech"],
    )
    store.inscribe(entry1)
    store.inscribe(entry2)
    store.inscribe(entry3)
    return store


class TestDashboardProvider:
    """Tests for DashboardProvider."""

    def test_galaxy_empty(self, provider):
        """空数据库返回空星系"""
        result = provider.galaxy()
        assert "nodes" in result
        assert "links" in result
        assert "timeline" in result
        assert "total" in result
        assert result["total"] == 0
        assert result["nodes"] == []

    def test_galaxy_with_data(self, store_with_data):
        """有数据时返回节点"""
        provider = DashboardProvider(store_with_data)
        result = provider.galaxy()
        assert result["total"] >= 1
        assert len(result["nodes"]) >= 1
        # 节点应包含必要字段
        node = result["nodes"][0]
        assert "id" in node
        assert "label" in node
        assert "tier" in node
        assert "entities" in node

    def test_belief_tree_empty(self, provider):
        """空数据库返回空信念树"""
        result = provider.belief_tree()
        assert "trees" in result
        assert "total_beliefs" in result
        assert result["total_beliefs"] == 0

    def test_entity_graph_empty(self, provider):
        """空数据库返回空图谱"""
        result = provider.entity_graph()
        assert "nodes" in result
        assert "edges" in result
        assert "total_nodes" in result
        assert "total_edges" in result
        assert result["total_nodes"] == 0

    def test_entity_graph_with_data(self, store_with_data):
        """有数据时返回图谱"""
        provider = DashboardProvider(store_with_data)
        result = provider.entity_graph()
        assert "nodes" in result
        assert "edges" in result

    def test_entity_graph_center(self, store_with_data):
        """指定中心实体的图谱"""
        provider = DashboardProvider(store_with_data)
        result = provider.entity_graph(center_label="Python")
        assert "center" in result
        assert result["center"] == "Python"

    def test_overview_empty(self, provider):
        """空数据库返回统计概览"""
        result = provider.overview()
        assert "counts" in result
        assert "timeline" in result
        assert "top_entities" in result
        assert "decay_distribution" in result
        assert "generated_at" in result

    def test_overview_with_data(self, store_with_data):
        """有数据时返回统计概览"""
        provider = DashboardProvider(store_with_data)
        result = provider.overview()
        assert result["counts"]["impressions"] >= 1
        assert len(result["top_entities"]) >= 1

    def test_parse_entities_string_list(self, provider):
        """解析字符串列表格式的实体"""
        result = DashboardProvider._parse_entities('["Python", "AI"]')
        assert result == ["Python", "AI"]

    def test_parse_entities_dict_list(self, provider):
        """解析字典列表格式的实体"""
        result = DashboardProvider._parse_entities('[{"label": "Python"}, {"label": "AI"}]')
        assert result == ["Python", "AI"]

    def test_parse_entities_empty(self, provider):
        """解析空实体"""
        assert DashboardProvider._parse_entities(None) == []
        assert DashboardProvider._parse_entities("[]") == []

    def test_sync_status(self, provider):
        """同步状态（可能无 sync_log 表）"""
        result = provider.sync_status()
        # 可能返回 error 或正常结果
        assert "total" in result or "error" in result
