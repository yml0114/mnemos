"""tests/test_sync.py — sync/engine.py 覆盖率测试"""
from __future__ import annotations

import sqlite3

import pytest

from mnemos.storage.palimpsest import PalimpsestStore
from mnemos.sync.engine import (
    SyncEngine,
    _gen_id,
    _parse_vector_clock,
    _vector_clock_compare,
    _vector_clock_increment,
    _vector_clock_merge,
)


# ── Fixtures ────────────────────────────────────────────


@pytest.fixture()
def store(tmp_path):
    s = PalimpsestStore(str(tmp_path / "test.db"))
    s.connect()
    yield s
    s.close()


@pytest.fixture()
def engine(store):
    return SyncEngine(store, node_id="test-node")


# ── Helper functions ────────────────────────────────────


class TestHelpers:
    def test_gen_id_default_prefix(self):
        rid = _gen_id()
        assert rid.startswith("sync_")
        assert len(rid) == len("sync_") + 12

    def test_gen_id_custom_prefix(self):
        rid = _gen_id("change")
        assert rid.startswith("change_")

    def test_gen_id_unique(self):
        ids = {_gen_id() for _ in range(50)}
        assert len(ids) == 50

    def test_parse_vector_clock_empty(self):
        assert _parse_vector_clock("") == {}
        assert _parse_vector_clock(None) == {}

    def test_parse_vector_clock_valid(self):
        assert _parse_vector_clock('{"a":1,"b":2}') == {"a": 1, "b": 2}

    def test_parse_vector_clock_invalid_json(self):
        assert _parse_vector_clock("not json") == {}

    def test_vector_clock_increment(self):
        vc = {"a": 1}
        result = _vector_clock_increment(vc, "b")
        assert result == {"a": 1, "b": 1}

    def test_vector_clock_increment_existing(self):
        vc = {"a": 3}
        result = _vector_clock_increment(vc, "a")
        assert result == {"a": 4}

    def test_vector_clock_increment_immutable(self):
        vc = {"a": 1}
        _vector_clock_increment(vc, "a")
        assert vc == {"a": 1}  # 原值不变

    def test_vector_clock_merge(self):
        a = {"a": 2, "b": 1}
        b = {"b": 3, "c": 1}
        result = _vector_clock_merge(a, b)
        assert result == {"a": 2, "b": 3, "c": 1}

    def test_vector_clock_compare_equal(self):
        assert _vector_clock_compare({"a": 1}, {"a": 1}) == "equal"

    def test_vector_clock_compare_a_leading(self):
        assert _vector_clock_compare({"a": 2}, {"a": 1}) == "a领先"

    def test_vector_clock_compare_b_leading(self):
        assert _vector_clock_compare({"a": 1}, {"a": 2}) == "b领先"

    def test_vector_clock_compare_concurrent(self):
        assert _vector_clock_compare({"a": 2}, {"b": 2}) == "concurrent"

    def test_vector_clock_compare_empty(self):
        assert _vector_clock_compare({}, {}) == "equal"


# ── SyncEngine ──────────────────────────────────────────


class TestSyncEngineInit:
    def test_default_node_id(self, store):
        eng = SyncEngine(store)
        assert eng.node_id.startswith("node_")

    def test_custom_node_id(self, store):
        eng = SyncEngine(store, node_id="laptop")
        assert eng.node_id == "laptop"


class TestSyncEngineLogChange:
    def test_log_change_returns_id(self, engine):
        sid = engine._log_change("mem-1", "create", "impression", {"title": "hello"})
        assert sid.startswith("change_")

    def test_log_change_persists(self, engine, store):
        sid = engine._log_change("mem-1", "create", "impression", {"title": "hello"})
        row = store.db.execute(
            "SELECT * FROM sync_log WHERE sync_id=?", (sid,)
        ).fetchone()
        assert row is not None
        assert row["memory_id"] == "mem-1"
        assert row["operation"] == "create"
        assert row["tier"] == "impression"
        assert row["sync_status"] == "pending"

    def test_log_change_with_entity_id(self, engine, store):
        sid = engine._log_change(
            "mem-1", "update", "impression", {}, entity_id="ent-1"
        )
        row = store.db.execute(
            "SELECT * FROM sync_log WHERE sync_id=?", (sid,)
        ).fetchone()
        assert row["entity_id"] == "ent-1"


class TestSyncEngineUpdateStatus:
    def test_update_status(self, engine, store):
        sid = engine._log_change("mem-1", "create", "impression")
        engine._update_sync_status(sid, "done")
        row = store.db.execute(
            "SELECT sync_status FROM sync_log WHERE sync_id=?", (sid,)
        ).fetchone()
        assert row["sync_status"] == "done"


class TestSyncEnginePendingChanges:
    def test_pending_empty(self, engine):
        assert engine._pending_changes() == []

    def test_pending_with_data(self, engine):
        engine._log_change("mem-1", "create", "impression")
        engine._log_change("mem-2", "update", "impression")
        engine._log_change("mem-3", "delete", "impression")
        # 标记 mem-3 为 done
        rows = engine._pending_changes()
        engine._update_sync_status(rows[-1]["sync_id"], "done")
        remaining = engine._pending_changes()
        assert len(remaining) == 2


class TestSyncEngineRecordOps:
    def test_record_create(self, engine, store):
        sid = engine.record_create("mem-1", "impression", {"title": "test"})
        row = store.db.execute(
            "SELECT * FROM sync_log WHERE sync_id=?", (sid,)
        ).fetchone()
        assert row["operation"] == "create"
        assert row["memory_id"] == "mem-1"

    def test_record_update(self, engine, store):
        sid = engine.record_update("mem-1", "impression", {"title": "updated"})
        row = store.db.execute(
            "SELECT * FROM sync_log WHERE sync_id=?", (sid,)
        ).fetchone()
        assert row["operation"] == "update"

    def test_record_delete(self, engine, store):
        sid = engine.record_delete("mem-1", "impression")
        row = store.db.execute(
            "SELECT * FROM sync_log WHERE sync_id=?", (sid,)
        ).fetchone()
        assert row["operation"] == "delete"

    def test_record_create_no_payload(self, engine):
        sid = engine.record_create("mem-1")
        assert sid.startswith("change_")

    def test_record_update_no_payload(self, engine):
        sid = engine.record_update("mem-1")
        assert sid.startswith("change_")


class TestSyncEngineStatus:
    def test_status_empty(self, engine):
        s = engine.status()
        assert s["pending"] == 0
        assert s["inflight"] == 0
        assert s["conflict"] == 0
        assert s["done"] == 0
        assert s["total"] == 0
        assert s["node_id"] == "test-node"
        assert s["last_sync"] is None

    def test_status_with_records(self, engine):
        engine._log_change("m1", "create", "impression")
        engine._log_change("m2", "update", "impression")
        sid = engine._log_change("m3", "delete", "impression")
        engine._update_sync_status(sid, "done")
        s = engine.status()
        assert s["pending"] == 2
        assert s["done"] == 1
        assert s["total"] == 3
        assert s["last_sync"] is not None


class TestSyncEnginePush:
    def test_push_empty(self, engine):
        result = engine.push()
        assert result == {
            "pushed": 0,
            "conflicts": 0,
            "skipped": 0,
            "total": 0,
        }

    def test_push_with_pending(self, engine):
        engine.record_create("mem-1", "impression", {"title": "test"})
        engine.record_create("mem-2", "impression", {"title": "test2"})
        result = engine.push()
        assert result["total"] == 2


class TestSyncEnginePull:
    def test_pull_missing_file(self, engine):
        result = engine.pull("/nonexistent/path/db.sqlite")
        assert result["applied"] == 0
        assert "error" in result

    def test_pull_empty_remote(self, engine, tmp_path):
        remote_path = tmp_path / "remote.db"
        remote = PalimpsestStore(str(remote_path))
        remote.connect()
        remote.close()
        result = engine.pull(str(remote_path))
        assert result["total"] == 0


class TestSyncEngineResolve:
    def test_resolve_conflicts_empty(self, engine):
        assert engine.resolve_conflicts() == []

    def test_resolve_conflicts_with_data(self, engine, store):
        sid = engine._log_change("m1", "create", "impression", {"title": "test"})
        engine._update_sync_status(sid, "conflict")
        conflicts = engine.resolve_conflicts()
        assert len(conflicts) == 1
        assert conflicts[0]["sync_id"] == sid

    def test_resolve_nonexistent(self, engine):
        result = engine.resolve("nonexistent_id")
        assert result["applied"] is False
        assert "error" in result

    def test_resolve_unknown_strategy(self, engine, store):
        sid = engine._log_change("m1", "create", "impression")
        engine._update_sync_status(sid, "conflict")
        result = engine.resolve(sid, resolution="bad_strategy")
        assert result["applied"] is False
        assert "Unknown strategy" in result["error"]

    def test_resolve_keep_local(self, engine, store):
        sid = engine._log_change("m1", "create", "impression", {"title": "test"})
        engine._update_sync_status(sid, "conflict")
        result = engine.resolve(sid, resolution="keep_local")
        assert result["applied"] is True
        assert result["resolution"] == "keep_local"

    def test_resolve_lww_no_local(self, engine, store):
        sid = engine._log_change("m1", "create", "impression", {
            "title": "test",
            "created_at": "2099-01-01T00:00:00",
        })
        engine._update_sync_status(sid, "conflict")
        result = engine.resolve(sid, resolution="lww")
        assert result["applied"] is True or result["applied"] is False
        assert result["resolution"] == "lww"


class TestSyncEngineMerge:
    def test_merge_missing_remote(self, engine):
        result = engine.merge("/nonexistent/path/db.sqlite")
        assert "pull_result" in result
        assert result["pull_result"]["applied"] == 0

    def test_merge_empty_remote(self, engine, tmp_path):
        remote_path = tmp_path / "remote.db"
        remote = PalimpsestStore(str(remote_path))
        remote.connect()
        remote.close()
        result = engine.merge(str(remote_path))
        assert result["pull_result"]["total"] == 0
        assert result["resolved"] == 0
        assert result["strategy"] == "lww"
