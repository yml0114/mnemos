# -*- coding: utf-8 -*-
"""
SystemContext — 上下文管理器核心实现

基于 OpenCode 理念设计：
- Context Epoch: 基线不变的时间段
- Mid‑Conversation System Message: 变更通知
- Checkpoint / Restore: 会话恢复
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .registry import ContextRegistry
from .types import (
    ContextEpoch,
    ContextSnapshot,
    MidConversationSystemMessage,
    RegisteredSource,
)


# 内部状态容器
@dataclass
class _InternalState:
    current_epoch: ContextEpoch | None = None
    current_snapshot: dict[str, ContextSnapshot] = field(default_factory=dict)
    pending_updates: list[ContextSnapshot] = field(default_factory=list)


class SystemContextImpl:
    """
    系统上下文管理器

    职责：
    1. 管理 Context Source 注册
    2. 观察源值变化
    3. 生成 Mid‑Conversation 系统消息
    4. 维护 Context Epoch 生命周期
    5. 提供 checkpoint / restore 用于会话持久化
    """

    def __init__(self, store: Any = None):
        """
        Args:
            store: 可选，用于持久化 snapshot 和 epoch
        """
        self._store = store
        self._state_saver = None  # StateSaverRegistry TBD
        self._registry = ContextRegistry()
        self._state = _InternalState()

    # ── Registry access ─────────────────────────────────────────

    @property
    def registry(self) -> ContextRegistry:
        return self._registry

    # ── Source 管理 ─────────────────────────────────────────────

    def register(
        self,
        key: str,
        source_factory,
        *,
        scope_type: str | None = None,
        scope_id: str = "",
        priority: int = 0,
        description: str = "",
    ) -> None:
        """委托给注册表"""
        self._registry.register(
            key,
            source_factory,
            scope_type=scope_type,
            scope_id=scope_id,
            priority=priority,
            description=description,
        )

    def get_sources(self, scope_type: str | None = None, scope_id: str = "") -> list:
        return self._registry.get_sources(scope_type=scope_type, scope_id=scope_id)

    def get_source(self, key: str):
        return self._registry.get_source(key)

    # ── Observation ─────────────────────────────────────────────

    def _observe_source(self, source) -> ContextSnapshot:
        """内部：观察单个 source 创建快照"""
        value = source.loader()
        rendered = source.renderer(value)

        # 计算值哈希
        value_json = str(sorted(value.items())).encode("utf-8")
        value_hash = hashlib.sha256(value_json).hexdigest()[:16]

        snap = ContextSnapshot(
            source_key=source.key,
            value_hash=value_hash,
            rendered=rendered,
            admitted_at=datetime.now(),
        )
        return snap

    # ── Reconciliation ─────────────────────────────────────────

    def reconcile(self) -> list[MidConversationSystemMessage]:
        """
        探测所有 source 值的变化

        将 pending_updates 更新为最新观察值，并返回自上次 admit 以来有变化的 source 列表
        """
        sources = self.get_sources()
        messages: list[MidConversationSystemMessage] = []

        # 观察所有源，构建新的 pending snapshot 映射
        new_pending = {}
        for source in sources:
            current = self._observe_source(source)
            new_pending[source.key] = current

            previous = self._state.current_snapshot.get(source.key)
            if previous and not current.diff(previous):
                continue  # 无变化（相对于基线）

            # 有变化 → 生成 mid‑conversation 消息
            msg = MidConversationSystemMessage(
                source_key=source.key,
                change_type="updated" if previous else "created",
                new_value_summary=current.rendered.split("\n")[0][:100],
                rendered=current.rendered,
                timestamp=datetime.now(),
            )
            messages.append(msg)

        self._state.pending_updates = list(new_pending.values())
        return messages

    # ── Produce ────────────────────────────────────────────────

    def produce(self, *, include_pending: bool = False) -> str:
        """
        渲染完整的 system context 文本

        Args:
            include_pending: 是否在输出中包含 pending 更新（用于立即显示变更）

        Returns:
            完整的文本（多个源拼接）
        """
        parts: list[str] = []

        # 基线部分：全部使用 current snapshot 中的值
        if self._state.current_epoch:
            parts.append(f"Baseline Context (Epoch {self._state.current_epoch.epoch_id.hex[:8]}):")
            for key, snap in sorted(self._state.current_snapshot.items()):
                parts.append(f"\n[{key}]\n{snap.rendered}")
        else:
            # 无 epoch，第一次 produce → 用当前 pending（即当前观察值）建立基线
            if self._state.pending_updates:
                parts.append("Baseline Context (initial):")
                for snap in sorted(self._state.pending_updates, key=lambda s: s.source_key):
                    parts.append(f"\n[{snap.source_key}]\n{snap.rendered}")
            else:
                parts.append("Baseline Context: (empty)")

        # 可能还有 pending mid‑conversation 消息
        if include_pending and self._state.pending_updates:
            parts.append("\n\n[Pending Updates]")
            for snap in self._state.pending_updates:
                diff = snap.rendered if snap.source_key not in self._state.current_snapshot else "(modified)"
                parts.append(f"\n[{snap.source_key}] {diff}")

        return "\n".join(parts)

    # ── Admit & Compact ────────────────────────────────────────

    def admit(self) -> None:
        """
        在安全 provider‑turn 边界调用：将 pending 值 admit 为新基线

        效果：
        - 将 pending_updates 复制到 current_snapshot
        - 更新当前 epoch 的 baseline_snapshot
        - 清空 pending_updates
        """
        if not self._state.pending_updates:
            return

        # 覆盖当前基线
        for snap in self._state.pending_updates:
            self._state.current_snapshot[snap.source_key] = snap

        if self._state.current_epoch:
            self._state.current_epoch.baseline_snapshot = self._state.current_snapshot.copy()

        self._state.pending_updates = []

    def compact(self) -> ContextEpoch:
        """
        压缩会话：创建新 epoch，重置基线，清空所有 mid‑conversation 消息

        旧 epoch 应该先持久化到 store（此处简化）
        """
        import uuid
        new_epoch = ContextEpoch(
            epoch_id=uuid.uuid4(),
            started_at=datetime.now(),
            baseline_snapshot=self._state.current_snapshot.copy(),
            mid_conversation_messages=[],
        )
        self._state.current_epoch = new_epoch
        self._state.pending_updates = []
        return new_epoch

    # ── Checkpoint / Restore ───────────────────────────────────

    def checkpoint(self) -> dict[str, Any]:
        """
        导出 checkpoint 数据

        结构：
        {
            "epoch_id": "hex",
            "started_at": "iso",
            "baseline_snapshot": {
                key: {value_hash, rendered, admitted_at, version}
            },
            "mid_conversation_messages": []
        }
        """
        epoch = self._state.current_epoch
        if epoch is None:
            return {}

        data = {
            "epoch_id": epoch.epoch_id.hex,
            "started_at": epoch.started_at.isoformat(),
            "baseline_snapshot": {
                k: {
                    "value_hash": v.value_hash,
                    "rendered": v.rendered,
                    "admitted_at": v.admitted_at.isoformat(),
                    "version": v.version,
                }
                for k, v in self._state.current_snapshot.items()
            },
            "mid_conversation_messages": epoch.mid_conversation_messages,
        }
        if self._state_saver:
            data["subagent_states"] = self._state_saver.run_all_savers()
        return data

    def restore(self, data: dict[str, Any]) -> None:
        """从 checkpoint 数据恢复状态"""
        from uuid import UUID

        if not data:
            self._state = _InternalState()
            return

        epoch_id = UUID(hex=data["epoch_id"])
        started_at = datetime.fromisoformat(data["started_at"])

        baseline = {}
        for k, v in data.get("baseline_snapshot", {}).items():
            baseline[k] = ContextSnapshot(
                source_key=k,
                value_hash=v["value_hash"],
                rendered=v["rendered"],
                admitted_at=datetime.fromisoformat(v["admitted_at"]),
                version=v["version"],
            )

        epoch = ContextEpoch(
            epoch_id=epoch_id,
            started_at=started_at,
            baseline_snapshot=baseline,
            mid_conversation_messages=data.get("mid_conversation_messages", []),
        )

        self._state = _InternalState(
            current_epoch=epoch,
            current_snapshot=baseline.copy(),
            pending_updates=[],
        )
        if self._state_saver and "subagent_states" in data:
            self._state_saver.restore_all(data["subagent_states"])

    # ── Convenience ────────────────────────────────────────────

    def list_sources(self) -> list[str]:
        """列出所有已注册的 source key"""
        return list(self._registry.list_registered().keys())