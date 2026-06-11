"""
LangChain / LangGraph 记忆集成

让 LangChain 生态的 Agent 一行代码接入 Mnemos 记忆。

用法:
    from mnemos.integrations.langchain import MnemosMemory
    from langchain.agents import create_react_agent

    memory = MnemosMemory(scope_id="agent-001")
    agent = create_react_agent(llm, tools, memory=memory)
"""

from __future__ import annotations

from typing import Any

from mnemos.core.models import MemoryEntry, MemoryQuery, ScopeType
from mnemos.curation import Curator
from mnemos.retrieval.resonance import ResonanceEngine
from mnemos.retrieval.stager import Stager
from mnemos.storage.palimpsest import PalimpsestStore


class MnemosMemory:
    """
    LangChain 兼容的记忆后端。

    支持两种模式:
    - auto_remember=True:  每次 add() 自动去重后写入
    - auto_remember=False: 手动调用 remember()
    """

    def __init__(
        self,
        db_path: str = "mnemos.db",
        scope_type: str = "tenant",
        scope_id: str = "default",
        auto_remember: bool = True,
    ):
        self._store = PalimpsestStore(db_path)
        self._store.connect()
        self._engine = ResonanceEngine(self._store)
        self._curator = Curator(self._store)
        self._stager = Stager()
        self.scope_type = ScopeType(scope_type)
        self.scope_id = scope_id
        self.auto_remember = auto_remember

    # ── LangChain Memory 接口 ──────────────────────

    @property
    def memory_variables(self) -> list[str]:
        return ["history", "context"]

    def load_memory_variables(self, inputs: dict[str, Any]) -> dict[str, Any]:
        """LangChain 调用：加载记忆到上下文"""
        query_text = inputs.get("input", "") or inputs.get("query", "")
        if not query_text:
            return {"history": "", "context": ""}

        results = self._engine.search(MemoryQuery(
            query_text=query_text,
            max_results=20,
        ))

        plan = self._stager.plan(results)
        return {
            "history": self._stager.render_context(plan),
            "context": self._stager.render_system(plan),
        }

    def save_context(self, inputs: dict[str, Any], outputs: dict[str, Any]) -> None:
        """LangChain 调用：保存对话上下文"""
        if not self.auto_remember:
            return
        content = f"用户: {inputs.get('input', '')}\n助手: {outputs.get('output', '')}"
        self.remember(content)

    def clear(self) -> None:
        """清除（软删除，实际只是不加载）"""
        pass  # Mnemos 不做硬删除，记忆保留为底本

    # ── Mnemos 原生接口 ────────────────────────────

    def remember(
        self, content: str, title: str = "", tags: list[str] | None = None
    ) -> dict[str, Any]:
        """智能写入（自动去重）"""
        entry = MemoryEntry(
            title=title or content[:80],
            content=content,
            scope=self.scope_type,
            scope_id=self.scope_id,
            tags=tags or [],
        )
        return self._curator.smart_inscribe(entry)

    def recall(self, query: str, max_results: int = 10) -> list[dict[str, Any]]:
        """检索记忆"""
        results = self._engine.search(MemoryQuery(
            query_text=query,
            max_results=max_results,
        ))
        return [
            {
                "content": r.entry.content,
                "title": r.entry.title,
                "resonance": round(r.resonance_score, 3),
                "tier": r.entry.tier.value,
                "created_at": r.entry.created_at.isoformat(),
            }
            for r in results
        ]

    def inject_context(self, query: str) -> dict[str, Any]:
        """获取分层注入计划（供 Agent 自行拼装 prompt）"""
        results = self._engine.search(MemoryQuery(query_text=query, max_results=20))
        plan = self._stager.plan(results)
        return {
            "system": self._stager.render_system(plan),
            "context": self._stager.render_context(plan),
            "archive": self._stager.render_archive(plan),
            "stats": self._stager.stats(plan),
        }

    def stats(self) -> dict[str, int]:
        return self._store.count()

    def close(self) -> None:
        self._store.close()


# ── LangGraph Checkpointer (可选) ──────────────────


class MnemosCheckpointer:
    """
    LangGraph 检查点保存器。

    将 LangGraph 的状态快照持久化到 Mnemos，
    支持跨会话恢复 Agent 工作流。
    """

    def __init__(self, memory: MnemosMemory):
        self._memory = memory

    def put(self, config: dict, checkpoint: dict, metadata: dict | None = None) -> None:
        """保存检查点"""
        thread_id = config.get("configurable", {}).get("thread_id", "default")
        import json
        self._memory.remember(
            content=json.dumps(checkpoint, ensure_ascii=False, default=str),
            title=f"Checkpoint: {thread_id}",
            tags=["langgraph", "checkpoint", thread_id],
        )

    def get(self, config: dict) -> dict | None:
        """获取最近检查点"""
        thread_id = config.get("configurable", {}).get("thread_id", "default")
        results = self._memory.recall(f"Checkpoint: {thread_id}", max_results=1)
        if results:
            import json
            return json.loads(results[0]["content"])
        return None
