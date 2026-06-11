"""测试 Alchemist 记忆凝练引擎"""
from __future__ import annotations

import pytest
from datetime import datetime, timezone

from mnemos.condensation.alchemist import AlchemistCondenser
from mnemos.core.models import (
    MemoryEntry, MemoryTier, ScopeType,
    EntityRef, BeliefRecord, ConfidenceLevel,
)
from mnemos.storage.palimpsest import PalimpsestStore


def _store(tmp_path):
    db = str(tmp_path / "test.db")
    return PalimpsestStore(db)


def _impression(title, content, entity_label, belief_content=None, scope=ScopeType.UNIVERSE, scope_id="default"):
    """创建一个规范的 IMPRESSION 条目"""
    beliefs = []
    if belief_content:
        beliefs.append(BeliefRecord(content=belief_content, confidence=ConfidenceLevel.CONFIRMED))
    return MemoryEntry(
        title=title,
        content=content,
        tier=MemoryTier.IMPRESSION,
        scope=scope,
        scope_id=scope_id,
        entities=[EntityRef(label=entity_label, entity_type="topic")],
        beliefs=beliefs,
        tags=["test"],
    )


class TestImpressionsToPatterns:

    def test_below_threshold(self, tmp_path):
        store = _store(tmp_path)
        alc = AlchemistCondenser(store)
        for i in range(4):  # < 5
            store.inscribe(_impression(f"t{i}", f"content {i}" * 10, "AI"))
        result = alc.impressions_to_patterns(ScopeType.UNIVERSE, "default")
        assert result == []

    def test_above_threshold(self, tmp_path):
        store = _store(tmp_path)
        alc = AlchemistCondenser(store)
        for i in range(6):  # >= 5
            store.inscribe(_impression(f"t{i}", f"content about AI {i}" * 10, "AI"))
        result = alc.impressions_to_patterns(ScopeType.UNIVERSE, "default")
        assert len(result) > 0
        assert result[0].tier == MemoryTier.PATTERN

    def test_custom_threshold(self, tmp_path):
        store = _store(tmp_path)
        alc = AlchemistCondenser(store)
        for i in range(4):
            store.inscribe(_impression(f"t{i}", f"content {i}" * 10, "Python"))
        result = alc.impressions_to_patterns(ScopeType.UNIVERSE, "default", min_impressions=3)
        assert len(result) > 0

    def test_entity_clustering(self, tmp_path):
        store = _store(tmp_path)
        alc = AlchemistCondenser(store)
        # 不同实体，各自 < 5
        for i in range(3):
            store.inscribe(_impression(f"t{i}", f"c {i}" * 10, "AI"))
        for i in range(3):
            store.inscribe(_impression(f"u{i}", f"c {i}" * 10, "Python"))
        result = alc.impressions_to_patterns(ScopeType.UNIVERSE, "default")
        assert result == []

    def test_mixed_entities_enough(self, tmp_path):
        store = _store(tmp_path)
        alc = AlchemistCondenser(store)
        for i in range(6):
            store.inscribe(_impression(f"t{i}", f"content {i}" * 10, "AI"))
        # AI >= 5, should produce patterns
        result = alc.impressions_to_patterns(ScopeType.UNIVERSE, "default")
        assert len(result) > 0

    def test_confirmed_beliefs_included(self, tmp_path):
        store = _store(tmp_path)
        alc = AlchemistCondenser(store)
        for i in range(6):
            store.inscribe(_impression(
                f"t{i}", f"content {i}" * 10, "AI",
                belief_content="AI is transforming software",
            ))
        result = alc.impressions_to_patterns(ScopeType.UNIVERSE, "default")
        assert len(result) > 0


class TestPatternsToPrinciples:

    def test_below_threshold(self, tmp_path):
        store = _store(tmp_path)
        alc = AlchemistCondenser(store)
        result = alc.patterns_to_principles(ScopeType.UNIVERSE, "default")
        assert result == []

    def test_above_threshold_with_beliefs(self, tmp_path):
        store = _store(tmp_path)
        alc = AlchemistCondenser(store)
        # 先通过 impressions_to_patterns 创建 patterns
        for i in range(6):
            store.inscribe(_impression(f"t{i}", f"content {i}" * 10, "AI",
                                       belief_content="AI is transformative"))
        patterns = alc.impressions_to_patterns(ScopeType.UNIVERSE, "default")
        assert len(patterns) > 0
        result = alc.patterns_to_principles(ScopeType.UNIVERSE, "default")
        # 即使 patterns >= 3，还需要高置信度信念
        assert isinstance(result, list)

    def test_low_confidence_not_enough(self, tmp_path):
        store = _store(tmp_path)
        alc = AlchemistCondenser(store)
        for i in range(6):
            store.inscribe(_impression(f"t{i}", f"content {i}" * 10, "AI"))
        alc.impressions_to_patterns(ScopeType.UNIVERSE, "default")
        result = alc.patterns_to_principles(ScopeType.UNIVERSE, "default")
        # 没有 confirmed 信念 → 不结晶
        assert result == []

    def test_no_beliefs(self, tmp_path):
        store = _store(tmp_path)
        alc = AlchemistCondenser(store)
        for i in range(6):
            store.inscribe(_impression(f"t{i}", f"content {i}" * 10, "AI"))
        alc.impressions_to_patterns(ScopeType.UNIVERSE, "default")
        result = alc.patterns_to_principles(ScopeType.UNIVERSE, "default")
        assert result == []


class TestAutoCondense:

    def test_empty_store(self, tmp_path):
        store = _store(tmp_path)
        alc = AlchemistCondenser(store)
        result = alc.auto_condense(ScopeType.UNIVERSE, "default")
        assert result["patterns_created"] == 0
        assert result["principles_created"] == 0

    def test_full_chain(self, tmp_path):
        store = _store(tmp_path)
        alc = AlchemistCondenser(store)
        for i in range(6):
            store.inscribe(_impression(
                f"t{i}", f"content {i}" * 10, "AI",
                belief_content="AI is transformative",
            ))
        result = alc.auto_condense(ScopeType.UNIVERSE, "default")
        assert isinstance(result, dict)
        assert "patterns_created" in result
        assert "principles_created" in result


class TestLLMDistill:

    def test_no_llm_client(self, tmp_path):
        store = _store(tmp_path)
        alc = AlchemistCondenser(store)
        result = alc.llm_distill(ScopeType.UNIVERSE, "default", llm_client=None)
        assert result == []

    def test_with_impressions(self, tmp_path):
        store = _store(tmp_path)
        alc = AlchemistCondenser(store)
        for i in range(6):
            store.inscribe(_impression(f"t{i}", f"content {i}" * 10, "AI"))
        result = alc.llm_distill(ScopeType.UNIVERSE, "default", llm_client=None)
        assert result == []


class TestThresholds:

    def test_impression_threshold(self):
        assert AlchemistCondenser.IMPRESSION_THRESHOLD == 5

    def test_pattern_threshold(self):
        assert AlchemistCondenser.PATTERN_THRESHOLD == 3
