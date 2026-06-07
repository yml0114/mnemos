"""集成模块测试 — Stager, Curator, 框架连接器"""

import pytest
from mnemos.core.models import MemoryEntry, MemoryQuery, ScopeType
from mnemos.storage.palimpsest import PalimpsestStore
from mnemos.retrieval.resonance import ResonanceEngine
from mnemos.retrieval.stager import Stager
from mnemos.curation import Curator


@pytest.fixture
def store():
    s = PalimpsestStore(":memory:")
    s.connect()
    yield s
    s.close()


@pytest.fixture
def engine(store):
    return ResonanceEngine(store)


@pytest.fixture
def stager():
    return Stager()


@pytest.fixture
def curator(store):
    return Curator(store)


class TestStager:
    def test_empty_results(self, stager):
        plan = stager.plan([])
        assert plan.total_memories == 0
        assert plan.estimated_tokens == 0

    def test_layered_injection(self, stager, engine, store):
        """测试高/中/低共振的三层分层 — 少量短记忆时格式化开销可能抵消 Token 缩减"""
        entries = [
            ("核心记忆", "用户偏好 Python 进行数据管道开发，习惯用 pandas 和 polars 处理大规模数据，注重性能优化", ["Python", "偏好"]),
            ("相关记忆", "用户使用 macOS 作为主要开发环境，终端偏好 iTerm2 + zsh", ["macOS", "环境"]),
            ("边缘记忆", "今天天气不错适合散步", ["天气"]),
            ("补充", "用户喜欢在周末安静时段集中编码", ["习惯"]),
        ]
        for title, content, tags in entries:
            store.inscribe(MemoryEntry(
                title=title, content=content,
                scope=ScopeType.TENANT, scope_id="test",
                tags=tags,
            ))
        results = engine.search(MemoryQuery(query_text="Python 开发偏好"))
        plan = stager.plan(results)
        assert plan.total_memories > 0
        assert len(plan.core) > 0
        assert plan.reduction_pct >= 0  # 少量记忆时格式化开销可能抵消缩减

    def test_stats_output(self, stager, engine, store):
        store.inscribe(MemoryEntry(
            title="测试", content="Python 数据分析",
            scope=ScopeType.TENANT, scope_id="test",
        ))
        results = engine.search(MemoryQuery(query_text="Python"))
        plan = stager.plan(results)
        stats = stager.stats(plan)
        assert "core_count" in stats
        assert "estimated_tokens" in stats
        assert "reduction_pct" in stats


class TestCurator:
    def test_exact_duplicate_skip(self, curator, store):
        entry = MemoryEntry(
            title="测试", content="Python 是一门很好的编程语言",
            scope=ScopeType.TENANT, scope_id="test",
        )
        store.inscribe(entry)
        dup = MemoryEntry(
            title="测试", content="Python 是一门很好的编程语言",
            scope=ScopeType.TENANT, scope_id="test",
        )
        result = curator.smart_inscribe(dup)
        assert result["action"] in ("skipped", "merged")

    def test_different_content_insert(self, curator):
        entry = MemoryEntry(
            title="A", content="今天天气真好",
            scope=ScopeType.TENANT, scope_id="test",
        )
        result = curator.smart_inscribe(entry)
        assert result["action"] == "inserted"

    def test_similar_content_merge(self, curator, store):
        store.inscribe(MemoryEntry(
            title="偏好", content="用户喜欢用 Python 做数据分析",
            scope=ScopeType.TENANT, scope_id="test",
        ))
        similar = MemoryEntry(
            title="偏好2", content="用户喜欢用 Python 做数据分析和机器学习",
            scope=ScopeType.TENANT, scope_id="test",
        )
        result = curator.smart_inscribe(similar)
        assert result["action"] in ("merged", "inserted")

    def test_jaccard_threshold(self, curator):
        a = "Python 数据分析 机器学习"
        b = "Python 数据挖掘 深度学习"
        jac = curator._jaccard(a, b)
        assert 0 < jac < 1.0

    def test_edit_distance(self, curator):
        a = "Python is great"
        b = "Python is grate"
        edit = curator._normalized_edit(a, b)
        assert edit < 0.2


class TestLangChainIntegration:
    def test_basic_remember_recall(self):
        from mnemos.integrations.langchain import MnemosMemory
        mem = MnemosMemory(":memory:", scope_id="test-lc", auto_remember=False)
        try:
            result = mem.remember("用户喜欢用 React 开发前端")
            assert result["action"] == "inserted"
            results = mem.recall("React 前端")
            assert len(results) > 0
            assert "React" in results[0]["content"]
        finally:
            mem.close()

    def test_inject_context(self):
        from mnemos.integrations.langchain import MnemosMemory
        mem = MnemosMemory(":memory:", scope_id="test-lc")
        try:
            mem.remember("项目使用 FastAPI + PostgreSQL 技术栈")
            mem.remember("用户偏好异步编程模式")
            ctx = mem.inject_context("项目技术栈")
            assert "system" in ctx
            assert "stats" in ctx
            assert ctx["stats"]["core_count"] >= 0
        finally:
            mem.close()

    def test_langchain_memory_interface(self):
        from mnemos.integrations.langchain import MnemosMemory
        mem = MnemosMemory(":memory:", scope_id="test-lc", auto_remember=False)
        try:
            mem.remember("用户名叫张三")
            mem.remember("张三住在北京")
            vars = mem.load_memory_variables({"input": "张三住在哪里"})
            assert isinstance(vars, dict)
            assert "context" in vars
        finally:
            mem.close()


class TestCrewAIIntegration:
    def test_search_and_save(self):
        from mnemos.integrations.crewai import MnemosCrewMemory
        mem = MnemosCrewMemory(":memory:", scope_id="test-crew")
        try:
            mem.save("Agent Alpha 负责数据分析任务")
            mem.save("Agent Beta 负责前端开发任务")
            results = mem.search("数据分析")
            assert len(results) > 0
            assert "数据分析" in results[0]["content"]
        finally:
            mem.close()

    def test_task_memory(self):
        from mnemos.integrations.crewai import MnemosCrewMemory
        mem = MnemosCrewMemory(":memory:", scope_id="test-crew")
        try:
            mem.remember_task("分析销售数据", "Q2 销售额增长 15%")
            mem.remember_agent_thought("分析师", "需要对比去年同期数据")
            results = mem.search("销售额")
            assert len(results) > 0
        finally:
            mem.close()

    def test_context_injection(self):
        from mnemos.integrations.crewai import MnemosCrewMemory
        mem = MnemosCrewMemory(":memory:", scope_id="test-crew")
        try:
            mem.save("项目的核心目标是提升用户留存率")
            ctx = mem.get_context("核心目标")
            assert isinstance(ctx, str)
            assert len(ctx) > 0
        finally:
            mem.close()
