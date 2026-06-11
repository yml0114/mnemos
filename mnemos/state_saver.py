# -*- coding: utf-8 -*-
"""
State Saver Registry — 管理子 Agent 状态的保存与恢复
"""

from __future__ import annotations

from typing import Any, Callable, Dict


class StateSaverRegistry:
    """
    注册表：允许子 Agent 注册其状态保存/恢复回调
    """

    def __init__(self) -> None:
        self._savers: Dict[str, Callable[[], Any]] = {}
        self._restorers: Dict[str, Callable[[Any], None]] = {}

    def register(self, name: str, save_fn: Callable[[], Any], restore_fn: Callable[[Any], None]) -> None:
        """注册一个状态保存器"""
        self._savers[name] = save_fn
        self._restorers[name] = restore_fn

    def unregister(self, name: str) -> None:
        self._savers.pop(name, None)
        self._restorers.pop(name, None)

    def run_all_savers(self) -> Dict[str, Any]:
        """调用所有已注册的 save 回调，收集状态"""
        states: Dict[str, Any] = {}
        for name, save_fn in self._savers.items():
            try:
                states[name] = save_fn()
            except Exception as e:
                states[name] = {"_error": str(e)}
        return states

    def restore_all(self, states: Dict[str, Any]) -> None:
        """调用恢复回调，传入对应的状态"""
        for name, state in states.items():
            restore_fn = self._restorers.get(name)
            if restore_fn:
                try:
                    restore_fn(state)
                except Exception:
                    # ignore errors in restore
                    pass
