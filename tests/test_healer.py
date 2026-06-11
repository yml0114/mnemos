"""
Tests for mnemos/healer/engine.py
"""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mnemos.storage.palimpsest import PalimpsestStore, MemoryTier
from mnemos.healer.engine import (
    HealerEngine,
    Inconsistency,
    InconsistencyType,
    Severity,
    _gen_id,
    _now,
)


@pytest.fixture
def store(tmp_path):
    db_path = str(tmp_path / "test_healer.db")
    s = PalimpsestStore(db_path)
    yield s
    s.close()


@pytest.fixture
def healer(store):
    return HealerEngine(store, auto_heal=True)


@pytest.fixture
def healer_no_auto(store):
    return HealerEngine(store, auto_heal=False)


def _insert(store, entry_id, content, tier="impression", is_active=1,
            created_at=None, touched_at=None, tags=None, entities=None):
    """Insert a raw entry directly into the store."""
    now = created_at or _now()
    touched = touched_at or now
    store.db.execute(
        """INSERT OR REPLACE INTO impressions
           (entry_id, title, content, scope_type, scope_id,
            tags_json, entities_json, beliefs_json, memory_type, is_active,
            hits, decay, state_key, anchors_json,
            created_at, touched_at, embedding_model)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (entry_id, "", content, "tenant", "default",
         json.dumps(tags or []), json.dumps(entities or []),
         json.dumps([]), tier, is_active,
         0, 1.0, "", json.dumps([]),
         now, touched, ""),
    )
    store.db.commit()


# ── Inconsistency model ───────────────────────────────────

class TestInconsistencyModel:
    def test_to_dict(self):
        inc = Inconsistency(
            inconsistency_id="inc-1",
            entry_id_a="a",
            entry_id_b="b",
            inconsistency_type=InconsistencyType.DUPLICATE_CONTENT,
            severity=Severity.WARNING,
            description="test desc",
            detail={"overlap": 0.9},
            auto_healed=False,
            suggested_fix="merge",
        )
        d = inc.to_dict()
        assert d["inconsistency_id"] == "inc-1"
        assert d["inconsistency_type"] == "duplicate_content"
        assert d["severity"] == "warning"
        assert d["detail"]["overlap"] == 0.9

    def test_repr(self):
        inc = Inconsistency("i1", "a", "b", "duplicate_content", "warning", "hello")
        assert "duplicate_content" in repr(inc)

    def test_defaults(self):
        inc = Inconsistency("i1", None, None, "type", "info", "desc")
        assert inc.auto_healed is False
        assert inc.detail == {}
        assert inc.suggested_fix is None


class TestHelpers:
    def test_gen_id(self):
        id1 = _gen_id("dup")
        id2 = _gen_id("dup")
        assert id1.startswith("dup_")
        assert id1 != id2

    def test_now(self):
        ts = _now()
        assert isinstance(ts, str)
        assert "T" in ts


class TestStats:
    def test_stats_empty(self, healer):
        s = healer.stats()
        assert s["total"] == 0
        assert s["healed"] == 0

    def test_stats_with_entries(self, healer, store):
        long = "this is a long piece of text for duplicate content detection testing in stats"
        _insert(store, "e1", long)
        _insert(store, "e2", long)
        healer.scan()
        s = healer.stats()
        assert s["total"] > 0


class TestScan:
    def test_scan_empty(self, healer):
        issues = healer.scan()
        assert isinstance(issues, list)

    def test_scan_duplicate_content(self, healer, store):
        long = "this is a long piece of text for duplicate content detection testing"
        _insert(store, "e1", long)
        _insert(store, "e2", long)
        issues = healer.scan()
        dupes = [i for i in issues if i.inconsistency_type == InconsistencyType.DUPLICATE_CONTENT]
        assert len(dupes) > 0

    def test_scan_with_limit(self, healer, store):
        long = "this is a long piece of text for duplicate content detection testing"
        for i in range(5):
            _insert(store, f"e{i}", f"{long} variant {i}")
            _insert(store, f"f{i}", f"{long} variant {i} copy")
        issues = healer.scan(limit=3)
        assert len(issues) <= 3


class TestOnWrite:
    def test_on_write_short_content(self, healer, store):
        _insert(store, "e1", "short")
        results = healer.on_write("e1", "impression", "short")
        dupes = [r for r in results if r.inconsistency_type == InconsistencyType.DUPLICATE_CONTENT]
        assert len(dupes) == 0

    def test_on_write_no_content(self, healer, store):
        _insert(store, "e1", "something")
        results = healer.on_write("e1", "impression", None)
        assert isinstance(results, list)

    def test_on_write_with_dupes(self, healer, store):
        long = "this is a long piece of text for duplicate content detection testing on write"
        _insert(store, "existing", long)
        _insert(store, "new", long)
        results = healer.on_write("new", "impression", long)
        assert isinstance(results, list)


class TestListInconsistencies:
    def test_list_empty(self, healer):
        results = healer.list_inconsistencies()
        assert results == []

    def test_list_with_entries(self, healer, store):
        long = "this is a long piece of text for duplicate detection in list test"
        _insert(store, "e1", long)
        _insert(store, "e2", long)
        healer.scan()
        results = healer.list_inconsistencies()
        assert len(results) > 0

    def test_list_by_severity(self, healer, store):
        long = "this is a long piece of text for severity filter testing in list"
        _insert(store, "e1", long)
        _insert(store, "e2", long)
        healer.scan()
        warnings = healer.list_inconsistencies(severity=Severity.WARNING)
        infos = healer.list_inconsistencies(severity=Severity.INFO)
        assert len(warnings) + len(infos) > 0

    def test_list_with_limit(self, healer, store):
        long = "this is a long piece of text for limit testing in list function"
        for i in range(3):
            _insert(store, f"e{i}", f"{long} variant {i}")
            _insert(store, f"f{i}", f"{long} variant {i} copy")
        healer.scan()
        results = healer.list_inconsistencies(limit=1)
        assert len(results) <= 1


class TestDismiss:
    def test_dismiss_existing(self, healer, store):
        long = "this is a long piece of text for dismiss testing in healer engine"
        _insert(store, "e1", long)
        _insert(store, "e2", long)
        healer.scan()
        issues = healer.list_inconsistencies()
        if issues:
            result = healer.dismiss(issues[0].inconsistency_id)
            assert result is True
            remaining = healer.list_inconsistencies()
            assert len(remaining) < len(issues)

    def test_dismiss_nonexistent(self, healer):
        result = healer.dismiss("nonexistent_id")
        assert result is False


class TestAutoHeal:
    def test_heal_all_empty(self, healer):
        result = healer.heal_all()
        assert result["total"] == 0
        assert result["healed"] == 0

    def test_heal_all_with_dupes(self, healer, store):
        long = "this is a long piece of text for heal all testing in healer engine"
        _insert(store, "e1", long)
        _insert(store, "e2", long)
        healer.scan()
        result = healer.heal_all()
        assert result["total"] > 0

    def test_auto_heal_disabled(self, healer_no_auto, store):
        long = "this is a long piece of text for auto heal disabled testing"
        _insert(store, "e1", long)
        _insert(store, "e2", long)
        healer_no_auto.scan()
        issues = healer_no_auto.list_inconsistencies()
        if issues:
            result = healer_no_auto.auto_heal(issues[0])
            assert result is False


class TestContradictionDetection:
    def test_detect_contradiction(self, healer):
        result = healer._detect_contradiction("用户喜欢 Python", "用户不喜欢 Python")
        assert len(result) > 0

    def test_detect_no_contradiction(self, healer):
        result = healer._detect_contradiction("用户喜欢 Python", "用户喜欢 JavaScript")
        assert len(result) == 0

    def test_detect_negation(self, healer):
        result = healer._detect_contradiction("是 true", "是 false")
        assert len(result) > 0


class TestTextOverlap:
    def test_identical(self, healer):
        score = healer._text_overlap("hello world", "hello world")
        assert score == 1.0

    def test_no_overlap(self, healer):
        score = healer._text_overlap("abc def", "xyz uvw")
        assert score == 0.0

    def test_partial_overlap(self, healer):
        score = healer._text_overlap("hello world foo", "hello world bar")
        assert 0 < score < 1.0

    def test_empty(self, healer):
        score = healer._text_overlap("", "hello")
        assert score == 0.0


class TestTableName:
    def test_impression(self, healer):
        assert healer._table_name("impression") == "impressions"
        assert healer._table_name("core") == "impressions"

    def test_pattern(self, healer):
        assert healer._table_name("longterm") == "patterns"

    def test_principle(self, healer):
        assert healer._table_name("archetype") == "principles"

    def test_unknown(self, healer):
        assert healer._table_name("unknown") == "impressions"
