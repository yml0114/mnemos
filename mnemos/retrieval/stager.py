"""
渐进式上下文注入器 — Stager（分期者）

设计理念:
  不是把所有相关记忆一股脑塞进上下文窗口（昂贵+噪音），
  而是按相关性分层、按需注入，类似 agentmemory 的 progressive context injection。

分层策略:
  Layer 0 (core): 最相关的 top-3 条记忆，直接注入系统提示
  Layer 1 (context): 次相关的 5 条，作为上下文附加
  Layer 2 (archive): 其余结果，以摘要形式提供引用

Token 效率:
  相比全量注入，可削减 70-90% 的 Token 消耗。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mnemos.core.models import MemoryEntry, SearchResult


@dataclass
class StagedMemory:
    """分层注入的记忆"""
    entry: MemoryEntry
    resonance: float
    layer: int  # 0=core, 1=context, 2=archive
    formatted: str = ""


@dataclass
class InjectionPlan:
    """上下文注入计划，带 Token 估算"""
    core: list[StagedMemory] = field(default_factory=list)
    context: list[StagedMemory] = field(default_factory=list)
    archive: list[StagedMemory] = field(default_factory=list)
    estimated_tokens: int = 0
    baseline_tokens: int = 0  # 全量注入的 Token 数
    reduction_pct: float = 0.0

    @property
    def total_memories(self) -> int:
        return len(self.core) + len(self.context) + len(self.archive)


class Stager:
    """
    渐进式上下文注入器。

    使用示例:
        stager = Stager()
        plan = stager.plan(results)
        system_prompt = stager.render_system(plan)
        context_prompt = stager.render_context(plan)
        archive_note = stager.render_archive(plan)
    """

    # 分层阈值
    CORE_THRESHOLD = 0.7       # 共振得分 >= 0.7 → 核心层
    CONTEXT_THRESHOLD = 0.35   # 共振得分 >= 0.35 → 上下文层
    CORE_MAX = 3               # 核心层最多 3 条
    CONTEXT_MAX = 5            # 上下文层最多 5 条

    # Token 估算系数 (粗略: 1 个中文字符 ≈ 2 tokens, 1 个英文单词 ≈ 1.3 tokens)
    CHARS_PER_TOKEN = 0.5

    def __init__(
        self,
        core_threshold: float = 0.7,
        context_threshold: float = 0.35,
        core_max: int = 3,
        context_max: int = 5,
    ):
        self.CORE_THRESHOLD = core_threshold
        self.CONTEXT_THRESHOLD = context_threshold
        self.CORE_MAX = core_max
        self.CONTEXT_MAX = context_max

    def plan(self, results: list[SearchResult]) -> InjectionPlan:
        """根据共振得分生成分层注入计划"""
        if not results:
            return InjectionPlan()

        plan = InjectionPlan()
        sorted_results = sorted(results, key=lambda r: r.resonance_score, reverse=True)

        # 计算基线 Token（全量注入）
        plan.baseline_tokens = self._estimate_tokens(
            "\n".join(r.entry.content for r in sorted_results)
        )

        core_count = 0
        context_count = 0

        for r in sorted_results:
            score = r.resonance_score
            staged = StagedMemory(
                entry=r.entry,
                resonance=score,
                layer=2,  # 默认归档层
            )

            if score >= self.CORE_THRESHOLD and core_count < self.CORE_MAX:
                staged.layer = 0
                staged.formatted = self._format_core(staged)
                plan.core.append(staged)
                core_count += 1
            elif score >= self.CONTEXT_THRESHOLD and context_count < self.CONTEXT_MAX:
                staged.layer = 1
                staged.formatted = self._format_context(staged)
                plan.context.append(staged)
                context_count += 1
            else:
                staged.formatted = self._format_archive(staged)
                plan.archive.append(staged)

        # 估算最终 Token（格式化文本可能比原始内容更长，
        # 因为注入了 [TIER] 前缀等标记；缩减率最低为 0）
        plan.estimated_tokens = self._estimate_tokens(self.render_full(plan))
        if plan.baseline_tokens > 0:
            plan.reduction_pct = max(0.0, round(
                (1 - plan.estimated_tokens / plan.baseline_tokens) * 100, 1
            ))

        return plan

    def render_system(self, plan: InjectionPlan) -> str:
        """生成系统提示注入（仅核心层）"""
        if not plan.core:
            return ""

        parts = ["[MEMORY — 核心记忆]\n以下是你已知的关键信息，请基于这些信息回应："]
        for i, m in enumerate(plan.core):
            parts.append(f"\n记忆{i+1} (共振: {m.resonance:.0%}): {m.entry.content}")
        return "\n".join(parts)

    def render_context(self, plan: InjectionPlan) -> str:
        """生成上下文注入（核心 + 上下文层）"""
        parts = []
        if plan.core:
            parts.append("[相关记忆]")
            for i, m in enumerate(plan.core):
                parts.append(f"• {m.entry.title}: {m.entry.content[:200]}")
        if plan.context:
            for i, m in enumerate(plan.context):
                parts.append(f"• {m.entry.title}: {m.entry.content[:150]}")
        return "\n".join(parts)

    def render_archive(self, plan: InjectionPlan) -> str:
        """生成归档引用（仅标题 + 摘要）"""
        if not plan.archive:
            return ""
        parts = ["[历史参考]"]
        for m in plan.archive[:10]:
            parts.append(f"· {m.entry.title} ({m.entry.created_at.strftime('%m-%d')})")
        return "\n".join(parts)

    def render_full(self, plan: InjectionPlan) -> str:
        """生成完整注入文本（用于 Token 估算）"""
        parts = []
        parts.append(self.render_system(plan))
        parts.append(self.render_context(plan))
        parts.append(self.render_archive(plan))
        return "\n".join(p for p in parts if p)

    def stats(self, plan: InjectionPlan) -> dict[str, Any]:
        """注入统计"""
        return {
            "core_count": len(plan.core),
            "context_count": len(plan.context),
            "archive_count": len(plan.archive),
            "estimated_tokens": plan.estimated_tokens,
            "baseline_tokens": plan.baseline_tokens,
            "reduction_pct": plan.reduction_pct,
        }

    # ── 内部 ──────────────────────────────────────

    def _format_core(self, m: StagedMemory) -> str:
        e = m.entry
        parts = [f"[{e.tier.value.upper()}] {e.content}"]
        beliefs = e.current_beliefs()
        if beliefs:
            parts.append(f"置信度: {beliefs[0].confidence.value}")
        return "\n".join(parts)

    def _format_context(self, m: StagedMemory) -> str:
        e = m.entry
        return f"[{e.tier.value}] {e.title}: {e.content[:200]}"

    def _format_archive(self, m: StagedMemory) -> str:
        e = m.entry
        return f"· {e.title} ({e.created_at.strftime('%Y-%m-%d')})"

    def _estimate_tokens(self, text: str) -> int:
        """粗略 Token 估算"""
        return int(len(text) * self.CHARS_PER_TOKEN)
