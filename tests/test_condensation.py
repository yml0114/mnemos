"""测试 condensation（凝练）机制 — v7.17 核心功能"""
import sqlite3
import pytest
from mnemos.storage.palimpsest import PalimpsestStore


@pytest.fixture
def store(tmp_path):
    db = tmp_path / "condense_test.db"
    s = PalimpsestStore(str(db))
    s.connect()
    yield s
    s._conn.close()


class TestCondensationSchema:
    """验证 schema 包含 condensations 表和 condensed_up_to 列"""

    def test_condensations_table_exists(self, store):
        cur = store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='condensations'"
        )
        assert cur.fetchone() is not None

    def test_condensed_up_to_column(self, store):
        cols = [r[1] for r in store._conn.execute("PRAGMA table_info(sessions)").fetchall()]
        assert "condensed_up_to" in cols

    def test_condensations_schema(self, store):
        cols = {r[1]: r[2] for r in store._conn.execute("PRAGMA table_info(condensations)").fetchall()}
        assert "id" in cols
        assert "session_id" in cols
        assert "summary" in cols
        assert "message_count" in cols
        assert "start_time" in cols
        assert "end_time" in cols


class TestAutoCondense:
    """测试 auto_condense 自动凝练逻辑"""

    def test_below_threshold_no_condense(self, store):
        """低于阈值不凝练"""
        sid = store.create_session("test")
        for i in range(5):
            store.append_message(sid, "user", "agent", [{"type": "text", "content": f"msg {i}"}])
        result = store.auto_condense(sid, llm_fn=lambda prompt: "摘要", threshold=20)
        assert result is None

    def test_above_threshold_condenses(self, store):
        """超过阈值触发凝练"""
        sid = store.create_session("test")
        for i in range(25):
            store.append_message(sid, "user", "agent", [{"type": "text", "content": f"message {i}"}])
        result = store.auto_condense(sid, llm_fn=lambda prompt: "这是一段摘要", threshold=20)
        assert result is not None
        assert "这是一段摘要" in str(result)

    def test_idempotent_at_threshold(self, store):
        """恰好在阈值不凝练（20 条未凝练 + threshold=20 → 不触发）"""
        sid = store.create_session("test")
        for i in range(20):
            store.append_message(sid, "user", "agent", [{"type": "text", "content": f"msg {i}"}])
        result = store.auto_condense(sid, llm_fn=lambda p: "摘要", threshold=20)
        assert result is None

    def test_condensation_recorded(self, store):
        """凝练后 condensations 表有记录"""
        sid = store.create_session("test")
        for i in range(25):
            store.append_message(sid, "user", "agent", [{"type": "text", "content": f"msg {i}"}])
        store.auto_condense(sid, llm_fn=lambda p: "摘要内容", threshold=20)
        rows = store._conn.execute(
            "SELECT * FROM condensations WHERE session_id=?", (sid,)
        ).fetchall()
        assert len(rows) == 1

    def test_impression_created(self, store):
        """凝练后创建 impression"""
        sid = store.create_session("test")
        for i in range(25):
            store.append_message(sid, "user", "agent", [{"type": "text", "content": f"msg {i}"}])
        store.auto_condense(sid, llm_fn=lambda p: "测试摘要内容", threshold=20)
        results = store.fts("测试摘要内容", limit=5)
        assert len(results) > 0

    def test_second_condense_increments(self, store):
        """第二次凝练是增量的（两次凝练之间需追加新消息）"""
        sid = store.create_session("test")
        for i in range(50):
            store.append_message(sid, "user", "agent", [{"type": "text", "content": f"msg {i}"}])
        r1 = store.auto_condense(sid, llm_fn=lambda p: "摘要1", threshold=20)
        assert r1 is not None  # 50-20=30 条被凝练
        # 追加新消息使未凝练数再次超过阈值
        for i in range(25):
            store.append_message(sid, "user", "agent", [{"type": "text", "content": f"new msg {i}"}])
        r2 = store.auto_condense(sid, llm_fn=lambda p: "摘要2", threshold=20)
        assert r2 is not None  # (30+25)-30=25, 25-20=5 条被凝练
        rows = store._conn.execute(
            "SELECT * FROM condensations WHERE session_id=?", (sid,)
        ).fetchall()
        assert len(rows) == 2

    def test_uncompacted_skips_condensed(self, store):
        """get_uncompacted_messages：凝练前返回需凝练的消息，凝练后返回空"""
        sid = store.create_session("test")
        for i in range(25):
            store.append_message(sid, "user", "agent", [{"type": "text", "content": f"msg {i}"}])
        # 凝练前：25 - 20 = 5 条需要凝练
        uncompacted = store.get_uncompacted_messages(sid, threshold=20)
        assert len(uncompacted) == 5
        # 凝练后：已凝练的消息被跳过
        store.auto_condense(sid, llm_fn=lambda p: "摘要", threshold=20)
        uncompacted2 = store.get_uncompacted_messages(sid, threshold=20)
        assert len(uncompacted2) == 0

    def test_get_full_context_includes_summary(self, store):
        """get_full_context 返回凝练摘要"""
        sid = store.create_session("test")
        for i in range(25):
            store.append_message(sid, "user", "agent", [{"type": "text", "content": f"msg {i}"}])
        store.auto_condense(sid, llm_fn=lambda p: "这是测试摘要", threshold=20)
        ctx = store.get_full_context(sid, recent_n=3)
        assert len(ctx['condensations']) > 0


class TestLegacyDBMigration:
    """测试旧 DB 兼容性迁移"""

    def test_add_condensed_up_to_column(self, tmp_path):
        """旧 sessions 表缺少 condensed_up_to 列时自动迁移"""
        db = tmp_path / "legacy.db"
        conn = sqlite3.connect(str(db))
        conn.execute("""
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY, agent_name TEXT, created_at TEXT, metadata_json TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE impressions (
                id TEXT PRIMARY KEY, tier TEXT DEFAULT 'impression',
                title TEXT, content TEXT, raw_input TEXT,
                scope TEXT DEFAULT '', scope_type TEXT DEFAULT 'tenant',
                scope_id TEXT DEFAULT '',
                source TEXT DEFAULT '', confidence REAL DEFAULT 0.5,
                tags_json TEXT DEFAULT '[]', related_to_json TEXT DEFAULT '[]',
                entry_id TEXT, created_at TEXT, touched_at TEXT, decay REAL DEFAULT 0.0,
                is_active INTEGER DEFAULT 1, state_key TEXT, state_json TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE messages (
                id TEXT PRIMARY KEY, session_id TEXT, role TEXT,
                agent_id TEXT DEFAULT '', tokens INTEGER DEFAULT 0,
                finish_reason TEXT, time_created TEXT DEFAULT ''
            )
        """)
        conn.execute("""
            CREATE TABLE parts (
                id TEXT PRIMARY KEY, message_id TEXT, idx INTEGER, type TEXT, content TEXT
            )
        """)
        conn.commit()
        conn.close()

        store = PalimpsestStore(str(db))
        store.connect()
        cols = [r[1] for r in store._conn.execute("PRAGMA table_info(sessions)").fetchall()]
        assert "condensed_up_to" in cols
        tbl = store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='condensations'"
        ).fetchone()
        assert tbl is not None
        store._conn.close()
