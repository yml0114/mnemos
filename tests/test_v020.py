"""
Tests for new v0.2.0 modules: BM25, Evaluation, Profile, Nexus English, Alchemist LLM
"""

import pytest
import numpy as np

from mnemos.retrieval.bm25 import BM25Scorer
from mnemos.evaluation import LLMJudge, RuleJudge
from mnemos.profile import Mneme, UserProfile
from mnemos.temporal.nexus import Nexus
from mnemos.core.models import MemoryEntry, EntityRef, ScopeType
from mnemos.storage.palimpsest import PalimpsestStore


# ── BM25 Tests ──────────────────────────────────────────

class TestBM25:
    def setup_method(self):
        self.scorer = BM25Scorer()
        self.scorer.index([
            ("d1", "用户喜欢黑暗模式和极简界面"),
            ("d2", "用户住在上海浦东新区"),
            ("d3", "用户正在开发AI平行世界项目"),
            ("d4", "用户偏好使用MacBook进行开发工作"),
            ("d5", "The user prefers dark mode and minimal UI design"),
        ])

    def test_basic_score(self):
        results = self.scorer.score("黑暗模式")
        assert len(results) > 0
        assert results[0][0] == "d1"  # d1 is most relevant
        assert results[0][1] > 0.5

    def test_english_score(self):
        results = self.scorer.score("dark mode")
        assert len(results) > 0
        # Should match d5 (English) and possibly d1 (if dark=黑暗 maps)
        top_ids = [r[0] for r in results[:3]]
        assert "d5" in top_ids

    def test_no_match(self):
        results = self.scorer.score("量子计算超导体")
        assert len(results) == 0 or results[0][1] < 0.1

    def test_add_and_remove(self):
        self.scorer.add("d6", "新增文档关于Rust编程语言")
        results = self.scorer.score("Rust编程")
        assert any(r[0] == "d6" for r in results)

        self.scorer.remove("d6")
        results2 = self.scorer.score("Rust编程")
        assert not any(r[0] == "d6" for r in results2)

    def test_empty_query(self):
        results = self.scorer.score("")
        assert results == []

    def test_score_ordering(self):
        results = self.scorer.score("用户喜欢")
        scores = [r[1] for r in results]
        assert scores == sorted(scores, reverse=True)


# ── RuleJudge Tests ─────────────────────────────────────

class TestRuleJudge:
    def setup_method(self):
        self.judge = RuleJudge()

    def test_exact_match(self):
        result = self.judge.judge(
            question="Where does the user live?",
            ground_truth="Shanghai",
            system_answer="Shanghai",
        )
        assert result["score"] >= 0.8

    def test_partial_match(self):
        result = self.judge.judge(
            question="Where does the user live?",
            ground_truth="Shanghai Pudong",
            system_answer="Shanghai",
        )
        assert 0.1 < result["score"] < 1.0

    def test_no_match(self):
        result = self.judge.judge(
            question="Where does the user live?",
            ground_truth="Shanghai",
            system_answer="Beijing",
        )
        assert result["score"] < 0.3

    def test_empty_answer(self):
        result = self.judge.judge(
            question="Where?",
            ground_truth="Shanghai",
            system_answer="",
        )
        assert result["score"] == 0.0

    def test_dont_know(self):
        result = self.judge.judge(
            question="Where?",
            ground_truth="Shanghai",
            system_answer="I don't know",
        )
        assert result["score"] == 0.0

    def test_chinese_match(self):
        result = self.judge.judge(
            question="用户住在哪里？",
            ground_truth="上海浦东",
            system_answer="上海浦东新区",
        )
        assert result["score"] >= 0.4  # Partial overlap


# ── LLMJudge Tests (no API key — only structure) ───────

class TestLLMJudge:
    def test_structure(self):
        judge = LLMJudge(api_key="fake", model="gpt-4o")
        assert judge.model == "gpt-4o"
        assert judge.api_key == "fake"

    def test_parse_valid_json(self):
        judge = LLMJudge()
        result = judge._parse_response('{"score": 0.8, "explanation": "Mostly correct"}')
        assert result["score"] == 0.8

    def test_parse_embedded_json(self):
        judge = LLMJudge()
        result = judge._parse_response('Here is my evaluation: {"score": 1.0, "explanation": "Perfect match"}')
        assert result["score"] == 1.0

    def test_parse_invalid(self):
        judge = LLMJudge()
        result = judge._parse_response("I cannot evaluate this")
        assert result["score"] == 0.0


# ── Nexus English Entity Tests ──────────────────────────

class TestNexusEnglish:
    def setup_method(self):
        self.nexus = Nexus()

    def _make_entry(self, content: str) -> MemoryEntry:
        return MemoryEntry(
            entry_id="test-en",
            title="test",
            content=content,
            scope=ScopeType.TENANT,
            scope_id="test",
        )

    def test_english_person(self):
        entry = self._make_entry("John Smith works at Google in New York")
        entities = self.nexus.extract(entry)
        labels = [e.label for e in entities]
        assert "John Smith" in labels

    def test_english_organization(self):
        entry = self._make_entry("She joined OpenAI Research last year")
        entities = self.nexus.extract(entry)
        labels = [e.label for e in entities]
        org_entities = [e for e in entities if e.entity_type == "organization"]
        assert len(org_entities) > 0

    def test_english_place(self):
        entry = self._make_entry("The conference was held in San Francisco City")
        entities = self.nexus.extract(entry)
        labels = [e.label for e in entities]
        place_entities = [e for e in entities if e.entity_type == "location"]
        assert len(place_entities) > 0

    def test_mixed_cn_en(self):
        entry = self._make_entry("张伟和John Smith在Shanghai City讨论项目")
        entities = self.nexus.extract(entry)
        labels = [e.label for e in entities]
        # Should find both Chinese and English entities
        assert len(entities) >= 2

    def test_query_entities_en(self):
        entities = self.nexus.extract_query_entities("What did John Smith say about OpenAI?")
        assert "John Smith" in entities


# ── Profile (Mneme) Tests ───────────────────────────────

class TestMneme:
    def setup_method(self):
        self.store = PalimpsestStore(":memory:")
        self.store.connect()

        # Insert sample memories
        for content, tags in [
            ("用户喜欢黑暗模式和极简UI", ["preference"]),
            ("用户在用MacBook M2 Max开发", ["tool"]),
            ("用户正在开发AI平行世界项目", ["project"]),
            ("用户不喜欢复杂的操作流程", ["dislike"]),
            ("用户住在上海浦东新区", ["location"]),
        ]:
            self.store.inscribe(MemoryEntry(
                entry_id=f"prof-{tags[0]}",
                title=tags[0],
                content=content,
                scope=ScopeType.TENANT,
                scope_id="user-001",
                tags=tags,
            ))

    def test_build_profile(self):
        mneme = Mneme(self.store)
        profile = mneme.build("user-001")
        assert isinstance(profile, UserProfile)
        assert profile.scope_id == "user-001"

    def test_profile_has_last_updated(self):
        mneme = Mneme(self.store)
        profile = mneme.build("user-001")
        assert profile.last_updated != ""

    def test_summary(self):
        mneme = Mneme(self.store)
        profile = mneme.build("user-001")
        summary = mneme.summary(profile)
        assert isinstance(summary, str)
        assert len(summary) > 0

    def test_empty_profile(self):
        mneme = Mneme(self.store)
        profile = mneme.build("nonexistent-user")
        summary = mneme.summary(profile)
        assert "无画像" in summary


# ── Alchemist LLM Distill Tests ────────────────────────

class TestAlchemistLLM:
    def test_llm_distill_without_client(self):
        """Should return empty list when no LLM client provided."""
        from mnemos.condensation.alchemist import AlchemistCondenser
        store = PalimpsestStore(":memory:")
        store.connect()
        alchemist = AlchemistCondenser(store)
        result = alchemist.llm_distill(llm_client=None)
        assert result == []


# ── BM25 + Resonance Integration Test ──────────────────

class TestResonanceBM25:
    def setup_method(self):
        self.store = PalimpsestStore(":memory:")
        self.store.connect()
        for i, (content, tag) in enumerate([
            ("Python是最好的编程语言", "tech"),
            ("用户偏好使用Rust进行系统开发", "tech"),
            ("今天天气很好适合出门散步", "life"),
            ("机器学习模型训练需要大量GPU", "tech"),
            ("用户喜欢看科幻电影", "entertainment"),
        ]):
            self.store.inscribe(MemoryEntry(
                entry_id=f"bm25-{i}",
                title=tag,
                content=content,
                scope=ScopeType.TENANT,
                scope_id="test",
                tags=[tag],
            ))

    def test_bm25_signal_in_resonance(self):
        from mnemos.retrieval.resonance import ResonanceEngine
        from mnemos.core.models import MemoryQuery
        engine = ResonanceEngine(self.store)
        results = engine.search(MemoryQuery(query_text="Python编程"))
        # Should find the Python entry
        assert len(results) > 0
        top_content = results[0].entry.content
        assert "Python" in top_content
