"""
v7.16~v7.17 新功能测试
覆盖：会话持久化、无限上下文
"""

import pytest
import sqlite3
import json
from pathlib import Path
from datetime import datetime, timezone


@pytest.fixture
def db_path(tmp_path):
    """创建临时数据库"""
    return str(tmp_path / "test.db")


@pytest.fixture
def store(db_path):
    """创建 PalimpsestStore 实例"""
    from mnemos.storage.palimpsest import PalimpsestStore
    return PalimpsestStore(db_path)


@pytest.fixture
def session_id(store):
    """创建会话并返回 session_id"""
    return store.create_session("test-project", metadata={"user": "test"})


def _make_parts(content: str, role: str = "user") -> list[dict]:
    """创建消息 parts"""
    return [{"type": "text", "content": content}]


# ── 会话持久化测试 (v7.16) ─────────────────────────────────


class TestSessionPersistence:
    """测试会话持久化功能"""

    def test_create_session(self, store):
        """测试创建会话"""
        sid = store.create_session("test-project", metadata={"user": "test"})
        assert sid is not None
        assert len(sid) > 0

    def test_append_message(self, store, session_id):
        """测试追加消息"""
        store.append_message(session_id, "user", "agent-1", _make_parts("我喜欢 Python"))
        store.append_message(session_id, "assistant", "agent-2", _make_parts("Python 很好！"))
        
        messages = store.list_messages(session_id)
        assert len(messages) >= 2

    def test_list_messages_with_limit(self, store, session_id):
        """测试获取消息（带限制）"""
        for i in range(5):
            store.append_message(session_id, "user", "agent-1", _make_parts(f"消息 {i}"))
        
        messages = store.list_messages(session_id, limit=2)
        assert len(messages) == 2

    def test_conversation_search(self, store, session_id):
        """测试搜索消息"""
        store.append_message(session_id, "user", "agent-1", _make_parts("我喜欢 Python 编程"))
        store.append_message(session_id, "user", "agent-1", _make_parts("机器学习很有趣"))
        
        results = store.conversation_search("Python", session_id=session_id)
        assert len(results) > 0

    def test_around_message(self, store, session_id):
        """测试获取消息上下文窗口"""
        msg_ids = []
        for i in range(5):
            mid = store.append_message(session_id, "user", "agent-1", _make_parts(f"消息 {i}"))
            msg_ids.append(mid)
        
        # 获取中间消息的上下文
        context = store.around_message(msg_ids[2], before=1, after=1)
        assert len(context) >= 1


# ── 无限上下文测试 (v7.17) ─────────────────────────────────


class TestAutoCondensation:
    """测试自动凝练功能"""

    def test_auto_condense(self, store, session_id):
        """测试自动凝练"""
        # 添加足够多消息触发凝练
        for i in range(25):
            store.append_message(session_id, "user", "agent-1", _make_parts(f"消息 {i}"))
        
        # 定义 LLM 函数
        def mock_llm(prompt: str) -> str:
            return "这是一段凝练摘要"
        
        # 触发凝练（阈值 20）
        result = store.auto_condense(session_id, llm_fn=mock_llm, threshold=20)
        assert result is not None
        assert "message_count" in result
        assert "summary_preview" in result

    def test_get_full_context(self, store, session_id):
        """测试获取完整上下文"""
        for i in range(25):
            store.append_message(session_id, "user", "agent-1", _make_parts(f"消息 {i}"))
        
        def mock_llm(prompt: str) -> str:
            return "凝练摘要"
        
        store.auto_condense(session_id, llm_fn=mock_llm, threshold=20)
        
        context = store.get_full_context(session_id, recent_n=5)
        assert "recent_messages" in context

    def test_get_condensed_history(self, store, session_id):
        """测试获取凝练历史"""
        for i in range(25):
            store.append_message(session_id, "user", "agent-1", _make_parts(f"消息 {i}"))
        
        def mock_llm(prompt: str) -> str:
            return "凝练摘要"
        
        store.auto_condense(session_id, llm_fn=mock_llm, threshold=20)
        
        history = store.get_condensed_history(session_id)
        assert len(history) > 0

    def test_get_uncompacted_messages(self, store, session_id):
        """测试获取未凝练消息"""
        for i in range(25):
            store.append_message(session_id, "user", "agent-1", _make_parts(f"消息 {i}"))
        
        def mock_llm(prompt: str) -> str:
            return "凝练摘要"
        
        store.auto_condense(session_id, llm_fn=mock_llm, threshold=20)
        
        uncompacted = store.get_uncompacted_messages(session_id)
        assert len(uncompacted) >= 0
