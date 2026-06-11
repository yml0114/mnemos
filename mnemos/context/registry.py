# -*- coding: utf-8 -*-
"""
Context Source 注册表 — 管理源的生命周期与作用域
"""

from __future__ import annotations

from typing import Callable

from .types import ContextSource, RegisteredSource


class ContextRegistry:
    """系统上下文源注册表"""

    def __init__(self) -> None:
        self._registry: dict[str, RegisteredSource] = {}

    # ── Registration ───────────────────────────────────────────

    def register(
        self,
        key: str,
        source_factory: Callable[[], ContextSource],
        *,
        scope_type: str | None = None,
        scope_id: str = "",
        priority: int = 0,
        description: str = "",
    ) -> None:
        """注册一个 Context Source"""
        if key in self._registry:
            raise ValueError(f"Context source '{key}' already registered")
        self._registry[key] = RegisteredSource(
            source_factory=source_factory,
            scope_type=scope_type,
            scope_id=scope_id,
            priority=priority,
            description=description,
        )

    def unregister(self, key: str) -> None:
        """移除注册"""
        self._registry.pop(key, None)

    # ── Discovery ──────────────────────────────────────────────

    def list_registered(self) -> dict[str, RegisteredSource]:
        """列出所有已注册源（浅拷贝）"""
        return dict(self._registry)

    def get_sources(
        self,
        scope_type: str | None = None,
        scope_id: str = "",
    ) -> list[ContextSource]:
        """获取匹配的 Context Source 实例，按优先级排序"""
        matches = []
        for reg in self._registry.values():
            if scope_type and reg.scope_type and reg.scope_type != scope_type:
                continue
            if scope_id and reg.scope_id and reg.scope_id != scope_id:
                continue
            matches.append(reg)
        matches.sort(key=lambda r: (r.priority, r.source_factory.__name__))
        return [reg.create() for reg in matches]

    def get_source(self, key: str) -> ContextSource | None:
        """获取指定 key 的源（创建新实例）"""
        reg = self._registry.get(key)
        if reg is None:
            return None
        return reg.create()

    # ── Helper ────────────────────────────────────────────────

    def clear(self) -> None:
        """清空注册表（主要用于测试）"""
        self._registry.clear()
