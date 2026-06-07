"""
CrewAI 记忆集成

让 CrewAI 的 Crew/Agent 使用 Mnemos 作为持久记忆后端。

用法:
    from mnemos.integrations.crewai import MnemosCrewMemory
    from crewai import Crew, Agent

    memory = MnemosCrewMemory(scope_id="my-crew")
    crew = Crew(agents=[...], tasks=[...], memory=memory)
"""

from __future__ import annotations

from typing import Any


class MnemosCrewMemory:
    """
    CrewAI 兼容的记忆后端。

    实现 CrewAI 的 Memory 接口：
    - short_term: 当前任务上下文
    - long_term: 跨任务持久记忆（走 Mnemos）
    - entity: 实体关系记忆
    """

    def __init__(
        self,
        db_path: str = "mnemos.db",
        scope_id: str = "default",
    ):
        # 延迟导入，避免强制依赖
        from mnemos.storage.palimpsest import PalimpsestStore
        from mnemos.retrieval.resonance import ResonanceEngine
        from mnemos.retrieval.stager import Stager
        from mnemos.curation import Curator
        from mnemos.core.models import MemoryEntry, MemoryQuery, ScopeType

        self._store = PalimpsestStore(db_path)
        self._store.connect()
        self._engine = ResonanceEngine(self._store)
        self._stager = Stager()
        self._curator = Curator(self._store)
        self._scope_type = ScopeType.TENANT
        self._scope_id = scope_id

        # CrewAI 兼容
        self.short_term: list[str] = []
        self._MemoryEntry = MemoryEntry
        self._MemoryQuery = MemoryQuery

    # ── CrewAI Memory 接口 ─────────────────────────

    def search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """CrewAI 标准接口：搜索记忆"""
        results = self._engine.search(self._MemoryQuery(
            query_text=query,
            max_results=limit,
        ))
        return [
            {
                "id": r.entry.entry_id,
                "content": r.entry.content,
                "metadata": {
                    "title": r.entry.title,
                    "tier": r.entry.tier.value,
                    "resonance": round(r.resonance_score, 3),
                    "tags": r.entry.tags,
                },
            }
            for r in results
        ]

    def save(self, content: str, metadata: dict | None = None) -> str:
        """CrewAI 标准接口：保存记忆"""
        from mnemos.core.models import MemoryEntry

        entry = MemoryEntry(
            title=metadata.get("title", content[:80]) if metadata else content[:80],
            content=content,
            scope=self._scope_type,
            scope_id=self._scope_id,
            tags=metadata.get("tags", []) if metadata else [],
        )
        result = self._curator.smart_inscribe(entry)
        return result["entry_id"]

    def get_context(self, query: str) -> str:
        """获取当前任务相关的记忆上下文（注入到 Agent prompt）"""
        results = self._engine.search(self._MemoryQuery(
            query_text=query,
            max_results=15,
        ))
        plan = self._stager.plan(results)
        return self._stager.render_system(plan)

    def remember_task(self, task_description: str, result: str) -> None:
        """记录任务执行结果"""
        content = f"[任务] {task_description}\n[结果] {result}"
        self.save(content, {"tags": ["crewai", "task_result"]})

    def remember_agent_thought(self, agent_name: str, thought: str) -> None:
        """记录 Agent 思考过程"""
        content = f"[{agent_name}] {thought}"
        self.save(content, {"tags": ["crewai", "agent_thought", agent_name]})

    # ── 统计 ──────────────────────────────────────

    def stats(self) -> dict[str, int]:
        return self._store.count()

    def reset(self) -> None:
        """重置短期记忆"""
        self.short_term = []

    def close(self) -> None:
        self._store.close()
