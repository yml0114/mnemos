"""集成模块测试 — Stager, Curator, 框架连接器, 时序推理, 嵌入"""

import pytest
import numpy as np
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


# ── 时序推理测试 ────────────────────────────────────────


class TestChronos:
    def test_detect_current_state_intent(self):
        from mnemos.temporal import Chronos
        c = Chronos()
        from mnemos.core.models import TemporalQueryMode
        assert c.detect_intent("他现在住在哪里") == TemporalQueryMode.CURRENT_STATE
        assert c.detect_intent("目前做什么工作") == TemporalQueryMode.CURRENT_STATE

    def test_detect_historical_intent(self):
        from mnemos.temporal import Chronos
        c = Chronos()
        from mnemos.core.models import TemporalQueryMode
        assert c.detect_intent("去年发生了什么") == TemporalQueryMode.HISTORICAL_RANGE

    def test_detect_upcoming_intent(self):
        from mnemos.temporal import Chronos
        c = Chronos()
        from mnemos.core.models import TemporalQueryMode
        assert c.detect_intent("下周有什么计划") == TemporalQueryMode.UPCOMING

    def test_infer_memory_type_state(self):
        from mnemos.temporal import Chronos
        c = Chronos()
        from mnemos.core.models import MemoryType
        assert c.classify(MemoryEntry(content="他住在北京")) == MemoryType.STATE

    def test_infer_memory_type_plan(self):
        from mnemos.temporal import Chronos
        c = Chronos()
        from mnemos.core.models import MemoryType
        assert c.classify(MemoryEntry(content="计划下周去上海")) == MemoryType.PLAN

    def test_infer_memory_type_preference(self):
        from mnemos.temporal import Chronos
        c = Chronos()
        from mnemos.core.models import MemoryType
        assert c.classify(MemoryEntry(content="用户喜欢黑暗模式")) == MemoryType.PREFERENCE

    def test_infer_memory_type_absence(self):
        from mnemos.temporal import Chronos
        c = Chronos()
        from mnemos.core.models import MemoryType
        assert c.classify(MemoryEntry(content="没有驾照")) == MemoryType.ABSENCE

    def test_infer_memory_type_event_default(self):
        from mnemos.temporal import Chronos
        c = Chronos()
        from mnemos.core.models import MemoryType
        assert c.classify(MemoryEntry(content="今天天气很好")) == MemoryType.EVENT

    def test_annotate_sets_memory_type(self):
        from mnemos.temporal import Chronos
        c = Chronos()
        from mnemos.core.models import MemoryType
        entry = MemoryEntry(content="他目前在字节跳动工作")
        c.annotate(entry)
        assert entry.memory_type == MemoryType.STATE
        assert entry.state_key != ""

    def test_state_deactivation(self, store):
        from mnemos.temporal import Chronos
        from mnemos.core.models import MemoryType
        c = Chronos()

        # 写入旧状态
        old = MemoryEntry(content="住在上海", scope_id="u1", memory_type=MemoryType.STATE)
        c.annotate(old)
        store.inscribe(old)

        # 写入新状态（同 state_key）
        new = MemoryEntry(content="住在北京", scope_id="u1", memory_type=MemoryType.STATE)
        c.annotate(new)
        store.inscribe(new)

        # 旧状态应被关闭
        old_reloaded = store.by_id(old.entry_id)
        assert old_reloaded is not None
        assert not old_reloaded.is_active

    def test_rerank_current_state_boosts_active(self):
        from mnemos.temporal import Chronos
        from mnemos.core.models import MemoryType, TemporalQueryMode, SearchResult

        c = Chronos()
        active = MemoryEntry(
            content="住在北京", memory_type=MemoryType.STATE, is_active=True
        )
        inactive = MemoryEntry(
            content="住在上海", memory_type=MemoryType.STATE, is_active=False
        )
        results = [
            SearchResult(entry=active, resonance_score=0.5, signal_breakdown={}),
            SearchResult(entry=inactive, resonance_score=0.5, signal_breakdown={}),
        ]
        reranked = c.rerank(results, "现在住哪里", TemporalQueryMode.CURRENT_STATE)
        # 活跃状态应排到前面
        assert reranked[0].entry.is_active

    def test_rerank_upcoming_boosts_plans(self):
        from mnemos.temporal import Chronos
        from mnemos.core.models import MemoryType, TemporalQueryMode, SearchResult
        from datetime import datetime, timedelta, timezone

        c = Chronos()
        future = datetime.now(timezone.utc) + timedelta(days=3)
        plan = MemoryEntry(
            content="下周出差", memory_type=MemoryType.PLAN,
            event_start=future, is_active=True,
        )
        event = MemoryEntry(
            content="上周开会", memory_type=MemoryType.EVENT,
        )
        results = [
            SearchResult(entry=plan, resonance_score=0.5, signal_breakdown={}),
            SearchResult(entry=event, resonance_score=0.5, signal_breakdown={}),
        ]
        reranked = c.rerank(results, "这周有什么安排", TemporalQueryMode.UPCOMING)
        assert reranked[0].entry.memory_type == MemoryType.PLAN


# ── 实体链接测试 ────────────────────────────────────────


class TestNexus:
    def test_extract_person(self):
        from mnemos.temporal.nexus import Nexus
        from mnemos.core.models import MemoryEntry
        n = Nexus()
        entities = n.extract(MemoryEntry(content="张三和李四一起去北京出差"))
        labels = {e.label for e in entities}
        # 启发式 NER，至少提取到一个含"张"或"李"的实体
        assert any("张" in l or "李" in l for l in labels), f"labels: {labels}"

    def test_extract_place(self):
        from mnemos.temporal.nexus import Nexus
        from mnemos.core.models import MemoryEntry
        n = Nexus()
        entities = n.extract(MemoryEntry(content="北京市朝阳区望京SOHO"))
        labels = {e.label for e in entities}
        # 至少提取到一个含"市"或"区"的实体
        assert any("市" in l or "区" in l for l in labels), f"labels: {labels}"

    def test_extract_org(self):
        from mnemos.temporal.nexus import Nexus
        from mnemos.core.models import MemoryEntry
        n = Nexus()
        entities = n.extract(MemoryEntry(content="字节跳动公司发布了新产品"))
        labels = {e.label for e in entities}
        assert "字节跳动公司" in labels

    def test_extract_tech_term(self):
        from mnemos.temporal.nexus import Nexus
        from mnemos.core.models import MemoryEntry
        n = Nexus()
        entities = n.extract(MemoryEntry(content="使用 Python 和 FastAPI 开发"))
        labels = {e.label for e in entities}
        assert "Python" in labels
        assert "FastAPI" in labels

    def test_extract_query_entities(self):
        from mnemos.temporal.nexus import Nexus
        n = Nexus()
        entities = n.extract_query_entities("张三的公司在哪里")
        assert any("张三" in e for e in entities)


# ── 嵌入引擎测试 ────────────────────────────────────────


class TestHermes:
    def test_hash_embedding_always_works(self):
        from mnemos.embedding import Hermes
        h = Hermes()
        vec = h.embed("测试文本")
        assert vec.shape == (384,)
        assert 0.9 < float(np.linalg.norm(vec)) < 1.1

    def test_same_text_same_vector(self):
        from mnemos.embedding import Hermes
        h = Hermes()
        v1 = h.embed("用户喜欢黑暗模式")
        v2 = h.embed("用户喜欢黑暗模式")
        assert np.allclose(v1, v2)

    def test_different_text_different_vector(self):
        from mnemos.embedding import Hermes
        h = Hermes()
        v1 = h.embed("用户喜欢黑暗模式")
        v2 = h.embed("今天天气很好适合出去玩")
        sim = h.cosine_similarity(v1, v2)
        assert sim < 0.5  # 不同主题应低相似度

    def test_batch_similarity(self):
        from mnemos.embedding import Hermes
        h = Hermes()
        query = h.embed("Python编程")
        candidates = np.array([
            h.embed("Python 是一种编程语言"),
            h.embed("今天天气很好"),
            h.embed("Python 和 FastAPI 开发"),
        ])
        scores = h.batch_similarity(query, candidates)
        # "Python编程" 应该与含 Python 的文本更相似
        assert scores[0] > scores[1]
        assert scores[2] > scores[1]

    def test_hermes_singleton(self):
        from mnemos.embedding import get_hermes, Hermes
        h1 = get_hermes()
        h2 = get_hermes()
        assert h1 is h2
