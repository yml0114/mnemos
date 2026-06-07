"""
独立记忆世界 — MCP 服务接口

通过 MCP 协议暴露记忆系统能力，任何兼容 MCP 的 Agent 都可接入。

暴露的工具:
  - mnemos_remember:  写入一条记忆
  - mnemos_recall:    检索记忆（多信号融合）
  - mnemos_forget:    软删除记忆
  - mnemos_revise:    修正信念
  - mnemos_condense:  触发记忆凝练
  - mnemos_stats:     查看记忆统计

暴露的资源:
  - mnemos://entity/{label}:  查看实体关系图谱
  - mnemos://scope/{type}/{id}: 查看范围记忆概览
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from mnemos.core.models import (
    MemoryEntry,
    MemoryQuery,
    MemoryTier,
    ScopeType,
)
from mnemos.retrieval.resonance import ResonanceEngine
from mnemos.storage.palimpsest import PalimpsestStore


# ── 全局单例 ─────────────────────────────────────────────

_store: PalimpsestStore | None = None
_engine: ResonanceEngine | None = None


def _get_store() -> PalimpsestStore:
    global _store
    if _store is None:
        db_path = os.environ.get("MNEMOS_DB_PATH", "mnemos.db")
        _store = PalimpsestStore(db_path)
        _store.connect()
    return _store


def _get_engine() -> ResonanceEngine:
    global _engine
    if _engine is None:
        _engine = ResonanceEngine(_get_store())
    return _engine


# ── MCP 工具定义 ─────────────────────────────────────────


TOOLS = [
    {
        "name": "mnemos_remember",
        "description": "将一条记忆写入记忆世界。记忆会自动归类到印象层(impression)，"
                       "后续可通过凝练升级为模式(pattern)或原则(principle)。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "要记住的内容",
                },
                "title": {
                    "type": "string",
                    "description": "简短标题（可选，默认取内容前80字）",
                },
                "scope_type": {
                    "type": "string",
                    "enum": ["universe", "tenant", "persona", "session"],
                    "description": "记忆归属范围，默认 tenant",
                },
                "scope_id": {
                    "type": "string",
                    "description": "范围标识（用户ID/Agent ID/Session ID）",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "标签列表",
                },
                "entities": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "label": {"type": "string"},
                            "entity_type": {"type": "string", "default": "concept"},
                            "description": {"type": "string"},
                        },
                    },
                    "description": "关联实体列表",
                },
                "related_to": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "关联的记忆ID列表",
                },
            },
            "required": ["content"],
        },
    },
    {
        "name": "mnemos_recall",
        "description": "从记忆世界中检索记忆。支持语义搜索、关键词过滤、实体关联、"
                       "时间范围和范围过滤。多信号融合排序。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索查询文本",
                },
                "keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "关键词列表",
                },
                "entities": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "限定实体标签",
                },
                "tiers": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["impression", "pattern", "principle"]},
                    "description": "限定记忆层次",
                },
                "scope_type": {
                    "type": "string",
                    "enum": ["universe", "tenant", "persona", "session"],
                },
                "scope_id": {"type": "string"},
                "after": {"type": "string", "description": "起始时间 ISO 格式"},
                "before": {"type": "string", "description": "结束时间 ISO 格式"},
                "max_results": {"type": "integer", "default": 20},
            },
            "required": ["query"],
        },
    },
    {
        "name": "mnemos_revise",
        "description": "修正记忆中的信念。旧信念不会被删除，作为历史版本保留。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "entry_id": {
                    "type": "string",
                    "description": "要修正的记忆ID",
                },
                "old_belief_id": {
                    "type": "string",
                    "description": "被修正的旧信念ID",
                },
                "new_content": {
                    "type": "string",
                    "description": "修正后的信念内容",
                },
                "source": {
                    "type": "string",
                    "description": "修正来源（Agent名/对话ID）",
                },
            },
            "required": ["entry_id", "old_belief_id", "new_content"],
        },
    },
    {
        "name": "mnemos_condense",
        "description": "触发记忆凝练：将印象蒸馏为模式，或将模式结晶为原则。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "scope_type": {
                    "type": "string",
                    "enum": ["universe", "tenant", "persona", "session"],
                    "default": "tenant",
                },
                "scope_id": {"type": "string", "default": ""},
            },
            "required": [],
        },
    },
    {
        "name": "mnemos_stats",
        "description": "查看记忆世界统计信息。",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
]


# ── 工具处理器 ───────────────────────────────────────────


async def handle_tool(name: str, arguments: dict[str, Any]) -> list[dict[str, Any]]:
    """MCP 工具分发"""
    handlers = {
        "mnemos_remember": _handle_remember,
        "mnemos_recall": _handle_recall,
        "mnemos_revise": _handle_revise,
        "mnemos_condense": _handle_condense,
        "mnemos_stats": _handle_stats,
    }
    handler = handlers.get(name)
    if handler is None:
        return [{"type": "text", "text": f"Unknown tool: {name}"}]

    result = await handler(arguments)
    return [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}]


async def _handle_remember(args: dict) -> dict:
    """处理记忆写入"""
    store = _get_store()
    now = datetime.now(timezone.utc)

    entities = [
        __import__("mnemos.core.models", fromlist=["EntityRef"]).EntityRef(
            label=e.get("label", ""),
            entity_type=e.get("entity_type", "concept"),
            description=e.get("description", ""),
        )
        for e in args.get("entities", [])
    ]

    entry = MemoryEntry(
        title=args.get("title", args["content"][:80]),
        content=args["content"],
        tier=MemoryTier.IMPRESSION,
        scope=ScopeType(args.get("scope_type", "tenant")),
        scope_id=args.get("scope_id", ""),
        tags=args.get("tags", []),
        entities=entities,
        related_ids=args.get("related_to", []),
        created_at=now,
        last_accessed_at=now,
    )

    entry_id = store.inscribe(entry)
    return {"status": "remembered", "entry_id": entry_id}


async def _handle_recall(args: dict) -> dict:
    """处理记忆检索"""
    engine = _get_engine()

    scopes = []
    if args.get("scope_type") and args.get("scope_id"):
        scopes = [
            __import__("mnemos.core.models", fromlist=["ContextScope"]).ContextScope(
                scope_type=ScopeType(args["scope_type"]),
                scope_id=args["scope_id"],
            )
        ]

    tiers = None
    if args.get("tiers"):
        tiers = [MemoryTier(t) for t in args["tiers"]]

    after = datetime.fromisoformat(args["after"]) if args.get("after") else None
    before = datetime.fromisoformat(args["before"]) if args.get("before") else None

    query = MemoryQuery(
        query_text=args.get("query", ""),
        keywords=args.get("keywords", []),
        entities=args.get("entities", []),
        tiers=tiers or [],
        scopes=scopes,
        after=after,
        before=before,
        max_results=args.get("max_results", 20),
    )

    results = engine.search(query)
    return {
        "query": args.get("query", ""),
        "found": len(results),
        "results": [
            {
                "entry_id": r.entry.entry_id,
                "title": r.entry.title,
                "content": r.entry.content[:300],
                "tier": r.entry.tier.value,
                "resonance": round(r.resonance_score, 4),
                "signals": r.signal_breakdown,
                "entities": [e.label for e in r.entry.entities],
                "tags": r.entry.tags,
                "created_at": r.entry.created_at.isoformat(),
            }
            for r in results
        ],
    }


async def _handle_revise(args: dict) -> dict:
    """处理信念修正"""
    store = _get_store()
    entry = store.by_id(args["entry_id"])
    if entry is None:
        return {"status": "error", "message": f"Entry {args['entry_id']} not found"}

    new_belief = entry.revise_belief(
        old_belief_id=args["old_belief_id"],
        new_content=args["new_content"],
        source=args.get("source", ""),
    )

    # 更新存储
    store.revise(
        entry.entry_id,
        entry.tier,
        {"beliefs_json": json.dumps(
            [b.model_dump() for b in entry.beliefs],
            ensure_ascii=False,
            default=str,
        )},
    )

    return {
        "status": "revised",
        "entry_id": entry.entry_id,
        "new_belief_id": new_belief.belief_id,
        "superseded_count": len(
            [b for b in entry.beliefs if b.superseded_by is not None]
        ),
    }


async def _handle_condense(args: dict) -> dict:
    """处理记忆凝练"""
    from mnemos.condensation.alchemist import AlchemistCondenser

    store = _get_store()
    condenser = AlchemistCondenser(store)
    result = condenser.auto_condense(
        scope_type=ScopeType(args.get("scope_type", "tenant")),
        scope_id=args.get("scope_id", ""),
    )
    return {"status": "condensed", **result}


async def _handle_stats(args: dict) -> dict:
    """处理统计查询"""
    store = _get_store()
    return {"status": "ok", "stats": store.count()}


# ── 服务器入口 ───────────────────────────────────────────


def main() -> None:
    """MCP 服务器入口（通过 stdio 通信）"""
    import asyncio
    import sys

    async def serve() -> None:
        store = _get_store()
        print(f"Mnemos server ready — {store.count()}", file=sys.stderr)

        # 读取 MCP 消息循环
        while True:
            try:
                line = sys.stdin.readline()
                if not line:
                    break

                request = json.loads(line)
                method = request.get("method", "")

                if method == "tools/list":
                    response = {"tools": TOOLS}
                elif method == "tools/call":
                    tool_name = request["params"]["name"]
                    arguments = request["params"].get("arguments", {})
                    content = await handle_tool(tool_name, arguments)
                    response = {"content": content}
                elif method == "initialize":
                    response = {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {
                            "name": "mnemos",
                            "version": "0.1.0",
                        },
                    }
                else:
                    response = {}

                sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
                sys.stdout.flush()

            except json.JSONDecodeError:
                continue
            except Exception as e:
                print(f"Error: {e}", file=sys.stderr)

    asyncio.run(serve())


if __name__ == "__main__":
    main()
