"""tests/test_server.py — api/server.py 覆盖率测试"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from mnemos.storage.palimpsest import PalimpsestStore
from mnemos.core.models import MemoryEntry, MemoryTier, ScopeType


# ── Fixtures ────────────────────────────────────────────


@pytest.fixture()
def store(tmp_path):
    s = PalimpsestStore(str(tmp_path / "test.db"))
    s.connect()
    # 写入一条记忆供后续 API 使用
    entry = MemoryEntry(
        entry_id="test-mem-1",
        content="hello world",
        title="test memory",
        scope_type=ScopeType.TENANT,
        scope_id="default",
        tier=MemoryTier.IMPRESSION,
        tags=["test"],
        entities_json=[],
    )
    s.inscribe(entry)
    yield s
    s.close()


@pytest.fixture()
def client(store):
    """创建 TestClient，mock 各 singleton 使其线程安全"""
    import mnemos.api.server as mod

    def _make_store():
        from mnemos.storage.palimpsest import PalimpsestStore
        s2 = PalimpsestStore(str(store._path))
        s2.connect()
        return s2

    with patch.object(mod, "_get_store", side_effect=_make_store):
        with patch.object(mod, "_get_engine") as mock_engine:
            with patch.object(mod, "_get_sync") as mock_sync:
                with patch.object(mod, "_get_multimodal") as mock_mm:
                    with patch.object(mod, "_get_healer") as mock_healer:
                        with patch.object(mod, "_get_temporal") as mock_temporal:
                            from fastapi.testclient import TestClient
                            c = TestClient(mod.app)
                            yield c


# ── Health ──────────────────────────────────────────────


class TestHealth:
    def test_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"


# ── Remember ────────────────────────────────────────────


class TestRemember:
    def test_remember_basic(self, client):
        resp = client.post("/remember", json={
            "content": "I learned Python today",
            "title": "Python learning",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "entry_id" in data
        assert data["entry_id"]  # 非空

    def test_remember_with_tags(self, client):
        resp = client.post("/remember", json={
            "content": "Important decision",
            "title": "Decision",
            "tags": ["decision", "important"],
        })
        assert resp.status_code == 200

    def test_remember_with_entities(self, client):
        resp = client.post("/remember", json={
            "content": "Met Alice at the conference",
            "title": "Meeting",
            "entities": [{"label": "Alice", "entity_type": "person"}],
        })
        assert resp.status_code == 200

    def test_remember_minimal(self, client):
        resp = client.post("/remember", json={
            "content": "just content",
        })
        assert resp.status_code == 200


# ── Recall ──────────────────────────────────────────────


class TestRecall:
    def test_recall_basic(self, client):
        resp = client.post("/recall", json={
            "query": "hello",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)
        assert "results" in data
        assert isinstance(data["results"], list)

    def test_recall_with_limit(self, client):
        resp = client.post("/recall", json={
            "query": "test",
            "max_results": 5,
        })
        assert resp.status_code == 200

    def test_recall_with_scope(self, client):
        resp = client.post("/recall", json={
            "query": "hello",
            "scope_type": "tenant",
            "scope_id": "default",
        })
        assert resp.status_code == 200

    def test_recall_with_tiers(self, client):
        resp = client.post("/recall", json={
            "query": "hello",
            "tiers": ["impression"],
        })
        assert resp.status_code == 200


# ── Stats ───────────────────────────────────────────────


class TestStats:
    def test_stats(self, client):
        resp = client.get("/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)


# ── Touch ───────────────────────────────────────────────


class TestTouch:
    def test_touch_existing(self, client):
        resp = client.post("/touch", json={"entry_id": "test-mem-1", "tier": "impression"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "touched"

    def test_touch_nonexistent(self, client):
        resp = client.post("/touch", json={"entry_id": "nonexistent"})
        assert resp.status_code == 200


# ── Decay ───────────────────────────────────────────────


class TestDecay:
    def test_decay_default(self, client):
        resp = client.post("/decay", json={})
        assert resp.status_code == 200


# ── Neglected ───────────────────────────────────────────


class TestNeglected:
    def test_neglected_basic(self, client):
        resp = client.post("/neglected", json={})
        assert resp.status_code == 200

    def test_neglected_with_limit(self, client):
        resp = client.post("/neglected", json={"limit": 10})
        assert resp.status_code == 200


# ── Condense ────────────────────────────────────────────


class TestCondense:
    def test_condense_basic(self, client):
        resp = client.post("/condense")
        assert resp.status_code == 200


# ── Profile ─────────────────────────────────────────────


class TestProfile:
    def test_profile_basic(self, client):
        resp = client.post("/profile", json={"query": "what do I like"})
        assert resp.status_code == 200
        data = resp.json()
        assert "profile" in data or isinstance(data, dict)

    def test_profile_with_memory_id(self, client):
        resp = client.post("/profile", json={
            "query": "tell me about test-mem-1",
            "memory_id": "test-mem-1",
        })
        assert resp.status_code == 200


# ── Stage ───────────────────────────────────────────────


class TestStage:
    def test_stage_basic(self, client):
        resp = client.post("/stage", json={
            "query": "test query",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)
