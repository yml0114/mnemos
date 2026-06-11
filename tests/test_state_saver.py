"""Tests for mnemos.state_saver module."""

import pytest
from mnemos.state_saver import StateSaverRegistry


class TestStateSaverRegistry:
    """Tests for StateSaverRegistry."""

    def test_register_and_run_savers(self):
        """注册 save/restore 回调并执行"""
        registry = StateSaverRegistry()
        
        # 注册一个简单的 saver
        def save_fn():
            return {"count": 42}
        
        def restore_fn(state):
            pass
        
        registry.register("test", save_fn, restore_fn)
        
        # 执行所有 savers
        states = registry.run_all_savers()
        assert "test" in states
        assert states["test"] == {"count": 42}

    def test_unregister(self):
        """取消注册"""
        registry = StateSaverRegistry()
        
        def save_fn():
            return "data"
        
        def restore_fn(state):
            pass
        
        registry.register("test", save_fn, restore_fn)
        registry.unregister("test")
        
        states = registry.run_all_savers()
        assert "test" not in states

    def test_run_all_savers_with_error(self):
        """save 回调抛出异常时应捕获"""
        registry = StateSaverRegistry()
        
        def bad_save():
            raise ValueError("save error")
        
        def restore_fn(state):
            pass
        
        registry.register("bad", bad_save, restore_fn)
        
        states = registry.run_all_savers()
        assert "bad" in states
        assert states["bad"] == {"_error": "save error"}

    def test_restore_all(self):
        """恢复状态"""
        registry = StateSaverRegistry()
        restored = {}
        
        def save_fn():
            return "data"
        
        def restore_fn(state):
            restored["value"] = state
        
        registry.register("test", save_fn, restore_fn)
        registry.restore_all({"test": "restored_data"})
        
        assert restored["value"] == "restored_data"

    def test_restore_all_with_error(self):
        """restore 回调抛出异常时应静默忽略"""
        registry = StateSaverRegistry()
        
        def save_fn():
            return "data"
        
        def bad_restore(state):
            raise ValueError("restore error")
        
        registry.register("bad", save_fn, bad_restore)
        
        # 不应抛出异常
        registry.restore_all({"bad": "data"})

    def test_restore_missing_name(self):
        """恢复不存在的名称不应报错"""
        registry = StateSaverRegistry()
        registry.restore_all({"nonexistent": "data"})

    def test_multiple_registries(self):
        """多个注册表互不影响"""
        reg1 = StateSaverRegistry()
        reg2 = StateSaverRegistry()
        
        reg1.register("a", lambda: "1", lambda s: None)
        reg2.register("b", lambda: "2", lambda s: None)
        
        states1 = reg1.run_all_savers()
        states2 = reg2.run_all_savers()
        
        assert "a" in states1
        assert "b" not in states1
        assert "b" in states2
        assert "a" not in states2
