"""Tests for mnemos.graph module."""

import pytest
import tempfile
import os
from mnemos.storage.palimpsest import PalimpsestStore
from mnemos.graph import KnowledgeGraph


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
def kg(store):
    """创建 KnowledgeGraph 实例"""
    return KnowledgeGraph(store)


class TestKnowledgeGraph:
    """Tests for KnowledgeGraph."""

    def test_add_edge(self, kg):
        """添加边"""
        kg.add_edge("Alice", "Bob", relation="friends", weight=2.0)
        edges = kg.get_edges("Alice")
        assert len(edges) == 1
        assert edges[0]["target"] == "Bob"
        assert edges[0]["relation"] == "friends"
        assert edges[0]["weight"] == 2.0

    def test_add_edge_default_relation(self, kg):
        """添加边使用默认关系"""
        kg.add_edge("A", "B")
        edges = kg.get_edges("A")
        assert edges[0]["relation"] == "related"

    def test_remove_edge(self, kg):
        """删除边"""
        kg.add_edge("A", "B", relation="test")
        kg.remove_edge("A", "B", relation="test")
        edges = kg.get_edges("A")
        assert len(edges) == 0

    def test_get_edges_empty(self, kg):
        """获取不存在实体的边"""
        edges = kg.get_edges("nonexistent")
        assert edges == []

    def test_neighbors(self, kg):
        """获取邻居（返回 {depth: [edge_dict, ...]}）"""
        kg.add_edge("A", "B")
        kg.add_edge("A", "C")
        kg.add_edge("B", "D")
        
        result = kg.neighbors("A")
        assert isinstance(result, dict)
        # depth 1 应包含 A->B 和 A->C
        assert 1 in result
        targets_d1 = {e["target"] for e in result[1]}
        assert "B" in targets_d1
        assert "C" in targets_d1

    def test_shortest_path(self, kg):
        """最短路径"""
        kg.add_edge("A", "B")
        kg.add_edge("B", "C")
        kg.add_edge("A", "D")
        
        path = kg.shortest_path("A", "C")
        assert path is not None
        assert path[0] == "A"
        assert path[-1] == "C"

    def test_shortest_path_no_path(self, kg):
        """无路径时返回 None"""
        kg.add_edge("A", "B")
        kg.add_edge("C", "D")
        
        path = kg.shortest_path("A", "C")
        assert path is None

    def test_update_edge_weight(self, kg):
        """更新边权重"""
        kg.add_edge("A", "B", weight=1.0)
        kg.update_edge_weight("A", "B", delta=0.5)
        
        edges = kg.get_edges("A")
        assert edges[0]["weight"] == 1.5

    def test_entity_communities(self, kg):
        """社区检测"""
        kg.add_edge("A", "B")
        kg.add_edge("B", "C")
        kg.add_edge("D", "E")
        
        communities = kg.entity_communities()
        # entity_communities 返回 list[list[str]]
        assert isinstance(communities, list)
        assert len(communities) >= 1
        # A, B, C 应在同一社区
        flat = [e for c in communities for e in c]
        assert "A" in flat
        assert "B" in flat

    def test_stats(self, kg):
        """统计信息"""
        kg.add_edge("A", "B")
        kg.add_edge("B", "C")
        
        stats = kg.stats()
        assert "total_edges" in stats
        assert stats["total_edges"] == 2

    def test_to_dict(self, kg):
        """导出为字典"""
        kg.add_edge("A", "B", weight=1.0)
        kg.add_edge("A", "C", weight=2.0)
        
        result = kg.to_dict(center="A", limit=10)
        assert "nodes" in result
        assert "edges" in result
        assert len(result["edges"]) >= 2
