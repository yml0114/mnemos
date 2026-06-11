"""tests/test_server_dashboard.py — api/server_with_dashboard.py 覆盖率测试"""
from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.fixture()
def store(tmp_path):
    from mnemos.storage.palimpsest import PalimpsestStore
    s = PalimpsestStore(str(tmp_path / "test.db"))
    s.connect()
    # 允许跨线程访问（TestClient 在新线程发送请求）
    s.db.execute("PRAGMA journal_mode=WAL")
    yield s
    s.close()


@pytest.fixture()
def client(tmp_path, store):
    """创建 FastAPI TestClient，mock 掉 _get_store"""
    import mnemos.api.server_with_dashboard as mod

    mod._dashboard_provider = None

    # 每次请求创建新的连接（线程安全）
    def _make_thread_safe_store():
        from mnemos.storage.palimpsest import PalimpsestStore
        s2 = PalimpsestStore(str(store._path))
        s2.connect()
        return s2

    with patch("mnemos.api.server._get_store", side_effect=_make_thread_safe_store):
        with patch("mnemos.api.server_with_dashboard._get_store", side_effect=_make_thread_safe_store):
            from fastapi.testclient import TestClient
            from mnemos.api.server_with_dashboard import app

            c = TestClient(app)
            yield c


# ── Root / Health ───────────────────────────────────────


class TestRootEndpoints:
    def test_root_returns_html(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert len(resp.text) > 0

    def test_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "timestamp" in data


# ── Dashboard Data APIs ─────────────────────────────────


class TestDashboardAPIs:
    def test_api_galaxy(self, client):
        resp = client.get("/api/galaxy")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, (dict, list))

    def test_api_belief_tree(self, client):
        resp = client.get("/api/belief-tree")
        assert resp.status_code == 200

    def test_api_belief_tree_with_memory_id(self, client):
        resp = client.get("/api/belief-tree?memory_id=mem-1")
        assert resp.status_code == 200

    def test_api_entity_graph(self, client):
        resp = client.get("/api/entity-graph")
        assert resp.status_code == 200

    def test_api_entity_graph_with_center(self, client):
        resp = client.get("/api/entity-graph?center=entity1")
        assert resp.status_code == 200

    def test_api_overview(self, client):
        resp = client.get("/api/overview")
        assert resp.status_code == 200


# ── Extract Conversation ────────────────────────────────


class TestExtractConversation:
    def test_extract_empty_messages(self, client):
        resp = client.post("/v1/extract/conversation", json={"messages": []})
        assert resp.status_code == 200
        assert resp.json()["created"] == []

    def test_extract_single_message(self, client):
        resp = client.post("/v1/extract/conversation", json={
            "messages": [{"role": "user", "content": "Hello world"}],
            "conversation_id": "conv-1",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["created"]) == 1

    def test_extract_multiple_messages(self, client):
        resp = client.post("/v1/extract/conversation", json={
            "messages": [
                {"role": "user", "content": "What is AI?"},
                {"role": "assistant", "content": "AI is artificial intelligence."},
                {"role": "user", "content": "Tell me more"},
            ]
        })
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["created"]) == 3

    def test_extract_skips_empty_content(self, client):
        resp = client.post("/v1/extract/conversation", json={
            "messages": [
                {"role": "user", "content": "real message"},
                {"role": "user", "content": ""},
                {"role": "assistant", "content": ""},
            ]
        })
        assert resp.status_code == 200
        assert len(resp.json()["created"]) == 1

    def test_extract_long_content_truncated_title(self, client):
        long_content = "A" * 200
        resp = client.post("/v1/extract/conversation", json={
            "messages": [{"role": "user", "content": long_content}]
        })
        assert resp.status_code == 200
        assert len(resp.json()["created"]) == 1

    def test_extract_no_conversation_id(self, client):
        resp = client.post("/v1/extract/conversation", json={
            "messages": [{"role": "user", "content": "test"}]
        })
        assert resp.status_code == 200

    def test_extract_role_tags(self, client):
        resp = client.post("/v1/extract/conversation", json={
            "messages": [
                {"role": "user", "content": "user msg"},
                {"role": "assistant", "content": "asst msg"},
            ]
        })
        assert resp.status_code == 200
        assert len(resp.json()["created"]) == 2


# ── Dashboard Provider Singleton ────────────────────────


class TestDashboardProviderInit:
    def test_singleton_lazy_init(self, store):
        import mnemos.api.server_with_dashboard as mod
        mod._dashboard_provider = None

        def _make_store():
            from mnemos.storage.palimpsest import PalimpsestStore
            s2 = PalimpsestStore(str(store._path))
            s2.connect()
            return s2

        with patch("mnemos.api.server_with_dashboard._get_store", side_effect=_make_store):
            from mnemos.viz.data_provider import DashboardProvider
            provider = mod._get_dashboard_provider()
            assert isinstance(provider, DashboardProvider)
            provider2 = mod._get_dashboard_provider()
            assert provider is provider2
