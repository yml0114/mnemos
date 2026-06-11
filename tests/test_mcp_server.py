"""tests/test_mcp_server.py — mcp/server.py 覆盖率测试

mcp SDK 未安装在测试环境中，通过 sys.modules mock 解决。
"""
from __future__ import annotations

import json
import sys
import types
from unittest.mock import MagicMock, patch

import pytest


# ── Mock mcp SDK ────────────────────────────────────────
# 在导入 mnemos.mcp.server 之前，注入一个假的 mcp.server.fastmcp 模块

_fake_mcp = types.ModuleType("mcp")
_fake_mcp_server = types.ModuleType("mcp.server")
_fake_fastmcp = types.ModuleType("mcp.server.fastmcp")

# FastMCP stub: 构造一个装饰器工厂
class _FakeFastMCP:
    def __init__(self, *a, **kw):
        pass
    def tool(self):
        def deco(fn):
            return fn
        return deco

_fake_fastmcp.FastMCP = _FakeFastMCP
_fake_mcp.server = _fake_mcp_server
_fake_mcp_server.fastmcp = _fake_fastmcp

sys.modules.setdefault("mcp", _fake_mcp)
sys.modules.setdefault("mcp.server", _fake_mcp_server)
sys.modules.setdefault("mcp.server.fastmcp", _fake_fastmcp)

# 现在可以安全导入
from mnemos.storage.palimpsest import PalimpsestStore  # noqa: E402
from mnemos.core.models import MemoryEntry, MemoryTier, ScopeType  # noqa: E402
import mnemos.mcp.server as mod  # noqa: E402


# ── Fixtures ────────────────────────────────────────────


@pytest.fixture()
def store(tmp_path):
    s = PalimpsestStore(str(tmp_path / "test.db"))
    s.connect()
    entry = MemoryEntry(
        entry_id="mcp-mem-1",
        content="test content for mcp",
        title="mcp test",
        scope_type=ScopeType.TENANT,
        scope_id="default",
        tier=MemoryTier.IMPRESSION,
        tags=["mcp", "test"],
        entities_json=[],
    )
    s.inscribe(entry)
    yield s
    s.close()


@pytest.fixture(autouse=True)
def _reset_singletons():
    """每个测试前重置全局单例"""
    mod._store = None
    mod._engine = None
    mod._sync_engine = None
    mod._mm_engine = None
    mod._healer = None
    mod._tg_engine = None
    yield
    mod._store = None
    mod._engine = None


@pytest.fixture()
def patch_store(store):
    def _make_store():
        s2 = PalimpsestStore(str(store._path))
        s2.connect()
        return s2
    with patch.object(mod, "_get_store", side_effect=_make_store):
        yield


@pytest.fixture()
def patch_engine(patch_store):
    engine = MagicMock()
    engine.search.return_value = []
    with patch.object(mod, "_get_engine", return_value=engine):
        yield engine


# ── _do_remember ────────────────────────────────────────


class TestDoRemember:
    def test_basic(self, patch_store):
        result = mod._do_remember({"content": "I love mnemos", "title": "love"})
        data = json.loads(result)
        assert "entry_id" in data
        assert data["status"] == "remembered"

    def test_with_tags(self, patch_store):
        result = mod._do_remember({"content": "tagged", "tags": ["a", "b"]})
        data = json.loads(result)
        assert data["status"] == "remembered"

    def test_with_entities(self, patch_store):
        result = mod._do_remember({
            "content": "met Alice",
            "entities": [{"label": "Alice", "entity_type": "person"}],
        })
        data = json.loads(result)
        assert data["status"] == "remembered"

    def test_minimal(self, patch_store):
        result = mod._do_remember({"content": "bare minimum"})
        data = json.loads(result)
        assert "entry_id" in data


# ── _do_recall ──────────────────────────────────────────


class TestDoRecall:
    def test_basic(self, patch_engine):
        result = mod._do_recall({"query": "test"})
        data = json.loads(result)
        assert "results" in data
        assert data["found"] == 0

    def test_with_limit(self, patch_engine):
        result = mod._do_recall({"query": "test", "max_results": 5})
        data = json.loads(result)
        assert "results" in data

    def test_with_scope(self, patch_engine):
        result = mod._do_recall({
            "query": "test",
            "scope_type": "tenant",
            "scope_id": "default",
        })
        data = json.loads(result)
        assert "results" in data


# ── _do_stats ───────────────────────────────────────────


class TestDoStats:
    def test_basic(self, patch_store):
        result = mod._do_stats({})
        data = json.loads(result)
        assert isinstance(data, dict)


# ── _do_touch ───────────────────────────────────────────


class TestDoTouch:
    def test_touch(self, patch_store):
        result = mod._do_touch({"entry_id": "mcp-mem-1", "tier": "impression"})
        data = json.loads(result)
        assert data["status"] == "touched"


# ── _do_decay ───────────────────────────────────────────


class TestDoDecay:
    def test_decay(self, patch_store):
        result = mod._do_decay({"rate": 0.01})
        data = json.loads(result)
        assert data["status"] == "decayed"


# ── _do_neglected ───────────────────────────────────────


class TestDoNeglected:
    def test_neglected(self, patch_store):
        result = mod._do_neglected({})
        data = json.loads(result)
        assert isinstance(data, dict)

    def test_neglected_with_limit(self, patch_store):
        result = mod._do_neglected({"limit": 5})
        data = json.loads(result)
        assert isinstance(data, dict)


# ── _do_profile ─────────────────────────────────────────


class TestDoProfile:
    def test_profile(self, patch_engine):
        result = mod._do_profile({"query": "what do I like"})
        data = json.loads(result)
        assert isinstance(data, dict)


# ── _do_stage ───────────────────────────────────────────


class TestDoStage:
    def test_stage(self, patch_engine):
        result = mod._do_stage({"query": "test"})
        data = json.loads(result)
        assert isinstance(data, dict)


# ── _do_import ──────────────────────────────────────────


class TestDoImport:
    def test_import_basic(self, patch_store):
        result = mod._do_import({
            "memories": [{"content": "imported memory", "title": "import"}],
        })
        data = json.loads(result)
        assert data["imported"] == 1

    def test_import_multiple(self, patch_store):
        result = mod._do_import({
            "memories": [
                {"content": "first", "title": "one"},
                {"content": "second", "title": "two"},
            ],
        })
        data = json.loads(result)
        assert data["imported"] == 2

    def test_import_empty(self, patch_store):
        result = mod._do_import({"memories": []})
        data = json.loads(result)
        assert isinstance(data, dict)
        assert data.get("imported", data.get("count", 0)) == 0


# ── _do_sync ────────────────────────────────────────────


class TestDoSync:
    def test_push(self, patch_store):
        sync_engine = MagicMock()
        sync_engine.push.return_value = {"synced": 0}
        sync_engine.status.return_value = {"pending": 0, "synced": 0}
        with patch.object(mod, "_get_sync", return_value=sync_engine):
            result = mod._do_sync({"action": "push"})
            data = json.loads(result)
            assert isinstance(data, dict)

    def test_pull(self, patch_store):
        sync_engine = MagicMock()
        sync_engine.pull.return_value = {"pulled": 0}
        sync_engine.status.return_value = {"pending": 0, "synced": 0}
        with patch.object(mod, "_get_sync", return_value=sync_engine):
            result = mod._do_sync({"action": "pull"})
            data = json.loads(result)
            assert isinstance(data, dict)

    def test_status(self, patch_store):
        sync_engine = MagicMock()
        sync_engine.status.return_value = {"pending": 0, "synced": 0}
        with patch.object(mod, "_get_sync", return_value=sync_engine):
            result = mod._do_sync({"action": "status"})
            data = json.loads(result)
            assert isinstance(data, dict)

    def test_unknown_action(self, patch_store):
        result = mod._do_sync({"action": "invalid"})
        data = json.loads(result)
        assert isinstance(data, dict)  # 返回 status 或 error 都行


# ── _do_multimodal ──────────────────────────────────────


class TestDoMultimodal:
    def test_attach(self, patch_store):
        mm_engine = MagicMock()
        mm_engine.attach_media.return_value = {"attachment_id": "att-1"}
        with patch.object(mod, "_get_multimodal", return_value=mm_engine):
            result = mod._do_multimodal({
                "action": "attach",
                "memory_id": "mcp-mem-1",
                "file_path": "/tmp/test.jpg",
                "media_type": "image",
            })
            data = json.loads(result)
            assert isinstance(data, dict)

    def test_search(self, patch_store):
        mm_engine = MagicMock()
        mm_engine.search_by_summary.return_value = []
        with patch.object(mod, "_get_multimodal", return_value=mm_engine):
            result = mod._do_multimodal({
                "action": "search",
                "query": "test",
            })
            data = json.loads(result)
            assert isinstance(data, list)

    def test_stats(self, patch_store):
        mm_engine = MagicMock()
        mm_engine.stats.return_value = {"total": 0}
        with patch.object(mod, "_get_multimodal", return_value=mm_engine):
            result = mod._do_multimodal({"action": "stats"})
            data = json.loads(result)
            assert isinstance(data, dict)


# ── _do_heal ────────────────────────────────────────────


class TestDoHeal:
    def test_scan(self, patch_store):
        healer = MagicMock()
        healer.scan.return_value = []
        with patch.object(mod, "_get_healer", return_value=healer):
            result = mod._do_heal({"action": "scan"})
            data = json.loads(result)
            assert data["found"] == 0

    def test_stats(self, patch_store):
        healer = MagicMock()
        healer.stats.return_value = {"total_issues": 0}
        with patch.object(mod, "_get_healer", return_value=healer):
            result = mod._do_heal({"action": "stats"})
            data = json.loads(result)
            assert isinstance(data, dict)


# ── _do_timeline ────────────────────────────────────────


class TestDoTimeline:
    def test_timeline(self, patch_store):
        tg = MagicMock()
        tg.timeline.return_value = []
        tg.stats.return_value = {"total_events": 0}
        with patch.object(mod, "_get_temporal", return_value=tg):
            result = mod._do_timeline({"memory_id": "mcp-mem-1"})
            data = json.loads(result)
            assert isinstance(data, dict)

    def test_stats(self, patch_store):
        tg = MagicMock()
        tg.stats.return_value = {"total_events": 0}
        with patch.object(mod, "_get_temporal", return_value=tg):
            result = mod._do_timeline({"action": "stats"})
            data = json.loads(result)
            assert isinstance(data, dict)

    def test_stats_default(self, patch_store):
        """unknown action falls through to stats()"""
        tg = MagicMock()
        tg.stats.return_value = {"total_events": 0}
        with patch.object(mod, "_get_temporal", return_value=tg):
            result = mod._do_timeline({"action": "invalid"})
            data = json.loads(result)
            assert isinstance(data, dict)


# ── _do_conversation_append ─────────────────────────────


class TestDoConversationAppend:
    def test_append(self, patch_store):
        store = mod._get_store()
        session_id = store.create_session("test-project")
        result = mod._do_conversation_append({
            "session_id": session_id,
            "role": "user",
            "parts": [{"content": "hello", "type": "text"}],
        })
        data = json.loads(result)
        assert data["status"] == "appended"

    def test_append_assistant(self, patch_store):
        store = mod._get_store()
        session_id = store.create_session("test-project")
        result = mod._do_conversation_append({
            "session_id": session_id,
            "role": "assistant",
            "parts": [{"content": "hi there", "type": "text"}],
        })
        data = json.loads(result)
        assert data["status"] == "appended"


# ── _do_conversation_search ─────────────────────────────


class TestDoConversationSearch:
    def test_search(self, patch_store):
        result = mod._do_conversation_search({"query": "hello"})
        data = json.loads(result)
        assert isinstance(data, dict)


# ── mnemos tool dispatch ────────────────────────────────


class TestMnemosTool:
    def test_stats_action(self, patch_store):
        result = mod.mnemos("stats")
        data = json.loads(result)
        assert isinstance(data, dict)

    def test_remember_action(self, patch_store):
        result = mod.mnemos("remember", json.dumps({"content": "via tool", "title": "tool"}))
        data = json.loads(result)
        assert "entry_id" in data

    def test_recall_action(self, patch_engine):
        result = mod.mnemos("recall", json.dumps({"query": "test"}))
        data = json.loads(result)
        assert "results" in data

    def test_unknown_action(self, patch_store):
        result = mod.mnemos("nonexistent_action")
        data = json.loads(result)
        assert data.get("status") == "error" or "error" in data


# ── main() ──────────────────────────────────────────────


class TestMain:
    def test_main_callable(self):
        assert callable(mod.main)
