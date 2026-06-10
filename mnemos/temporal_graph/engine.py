"""
时间线回溯引擎 — TemporalGraphEngine

追踪每条记忆的完整演化图谱：
  1. 每次记忆变更记录为一个 TemporalEvent
  2. 事件间建立因果边（evolves_to, caused_by, splits_from, merges_into）
  3. 支持时间线回溯查询（branch/merge/rollback）
  4. 可视化输出 GraphViz / D3 格式

设计哲学:
  记忆不是静止的档案——每一次修改都是新的"事件"。
  事件构成了记忆的演化历史，形成有向无环图(DAG)。
  回溯不是"撤销"，而是理解记忆的来龙去脉。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from mnemos.storage.palimpsest import PalimpsestStore


# ── 辅助 ─────────────────────────────────────────────────


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _gen_id(prefix: str = "evt") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# ── 常量 ─────────────────────────────────────────────────


class EventType:
    CREATED = "created"
    REVISED = "revised"
    CONDENSED = "condensed"
    MERGED = "merged"
    PROMOTED = "promoted"
    HEALED = "healed"
    SYNCED = "synced"
    ROLLED_BACK = "rolled_back"
    SPLIT = "split"

    _all = {CREATED, REVISED, CONDENSED, MERGED, PROMOTED,
            HEALED, SYNCED, ROLLED_BACK, SPLIT}


class EdgeRelation:
    EVOLVES_TO = "evolves_to"
    CAUSED_BY = "caused_by"
    RELATED_TO = "related_to"
    SPLITS_FROM = "splits_from"
    MERGES_INTO = "merges_into"
    ROLLS_BACK = "rolls_back"

    _all = {EVOLVES_TO, CAUSED_BY, RELATED_TO,
            SPLITS_FROM, MERGES_INTO, ROLLS_BACK}


# ── 数据模型 ─────────────────────────────────────────────


class TemporalEvent:
    """一条时间线事件"""

    def __init__(
        self,
        event_id: str,
        memory_id: str,
        event_type: str,
        tier: str,
        changed_fields: list[str] | None = None,
        before_snapshot: dict[str, Any] | None = None,
        after_snapshot: dict[str, Any] | None = None,
        parent_event: str | None = None,
        actor: str = "",
        summary: str = "",
        created_at: str | None = None,
    ):
        self.event_id = event_id
        self.memory_id = memory_id
        self.event_type = event_type
        self.tier = tier
        self.changed_fields = changed_fields or []
        self.before_snapshot = before_snapshot
        self.after_snapshot = after_snapshot
        self.parent_event = parent_event
        self.actor = actor
        self.summary = summary
        self.created_at = created_at or _now()
        # 运行时缓存
        self._children: list[TemporalEvent] = []
        self._edges: list[dict[str, Any]] = []

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "memory_id": self.memory_id,
            "event_type": self.event_type,
            "tier": self.tier,
            "changed_fields": self.changed_fields,
            "parent_event": self.parent_event,
            "actor": self.actor,
            "summary": self.summary,
            "created_at": self.created_at,
        }

    def __repr__(self) -> str:
        return (f"<TemporalEvent {self.event_type} "
                f"mem={self.memory_id[:12]} @ {self.created_at[:19]}>")


# ── 引擎 ─────────────────────────────────────────────────


class TemporalGraphEngine:
    """
    时间线图谱引擎。

    使用示例:
        store = PalimpsestStore("memory.db")
        store.connect()
        tge = TemporalGraphEngine(store)

        # 记录一个创建事件
        tge.record_create(memory_id, tier="core", snapshot={...})

        # 记录一个修改事件
        tge.record_revise(memory_id, tier="core",
                           before={...}, after={...},
                           changed_fields=["content", "tags"])

        # 追溯一条记忆的历史
        history = tge.timeline(memory_id)

        # 获取完整演化图谱（D3 JSON）
        graph = tge.graph()
    """

    def __init__(self, store: PalimpsestStore):
        self._store = store
        self._ensure_schema()

    # ── Schema 兼容 ──────────────────────────────────────

    def _ensure_schema(self) -> None:
        """确保 temporal_events 表有必要列"""
        conn = self._store.db
        cols = [r[1] for r in conn.execute(
            "PRAGMA table_info(temporal_events)"
        ).fetchall()]
        if "summary" not in cols:
            conn.execute(
                "ALTER TABLE temporal_events "
                "ADD COLUMN summary TEXT DEFAULT ''"
            )
        if "before_snapshot" not in cols:
            conn.execute(
                "ALTER TABLE temporal_events "
                "ADD COLUMN before_snapshot TEXT DEFAULT '{}'"
            )
        if "after_snapshot" not in cols:
            conn.execute(
                "ALTER TABLE temporal_events "
                "ADD COLUMN after_snapshot TEXT DEFAULT '{}'"
            )
        conn.commit()

    # ── 记录事件 ────────────────────────────────────────

    def record(
        self,
        memory_id: str,
        event_type: str,
        tier: str,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        changed_fields: list[str] | None = None,
        parent_event: str | None = None,
        actor: str = "",
        summary: str = "",
        auto_link: bool = True,
    ) -> str:
        """
        记录一个时间线事件。

        Args:
            memory_id: 关联的记忆 ID
            event_type: 事件类型 (created/revised/condensed/...)
            tier: 记忆层级
            before: 变更前的快照
            after: 变更后的快照
            changed_fields: 发生变化的字段列表
            parent_event: 父事件 ID（如果有因果关系）
            actor: 触发者标识（agent/user/system）
            summary: 事件摘要
            auto_link: 是否自动与上一个事件建立 evolves_to 边

        Returns:
            event_id
        """
        event_id = _gen_id()
        now = _now()

        self._store.db.execute(
            """INSERT INTO temporal_events
               (event_id, memory_id, event_type, tier,
                changed_fields, before_snapshot, after_snapshot,
                parent_event, actor, summary, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                event_id,
                memory_id,
                event_type,
                tier,
                json.dumps(changed_fields or [], ensure_ascii=False),
                json.dumps(before or {}, ensure_ascii=False),
                json.dumps(after or {}, ensure_ascii=False),
                parent_event,
                actor,
                summary,
                now,
            ),
        )

        # 自动与上一事件建立 evolves_to 边
        if auto_link:
            prev = self._store.db.execute(
                "SELECT event_id FROM temporal_events "
                "WHERE memory_id=? AND event_id!=? "
                "ORDER BY created_at DESC LIMIT 1",
                (memory_id, event_id),
            ).fetchone()
            if prev:
                self._add_edge(
                    source=prev["event_id"],
                    target=event_id,
                    relation=EdgeRelation.EVOLVES_TO,
                )

        self._store.db.commit()
        return event_id

    def record_create(
        self,
        memory_id: str,
        tier: str,
        snapshot: dict[str, Any] | None = None,
        actor: str = "",
    ) -> str:
        """记录记忆创建事件"""
        return self.record(
            memory_id=memory_id,
            event_type=EventType.CREATED,
            tier=tier,
            after=snapshot,
            actor=actor,
            summary=f"创建记忆 {memory_id[:12]}",
            auto_link=False,  # 创建没有前驱
        )

    def record_revise(
        self,
        memory_id: str,
        tier: str,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        changed_fields: list[str] | None = None,
        actor: str = "",
    ) -> str:
        """记录记忆修改事件"""
        fields_str = ", ".join(changed_fields or ["未知字段"])
        return self.record(
            memory_id=memory_id,
            event_type=EventType.REVISED,
            tier=tier,
            before=before,
            after=after,
            changed_fields=changed_fields,
            actor=actor,
            summary=f"修改 {memory_id[:12]}: {fields_str}",
        )

    def record_merge(
        self,
        target_memory_id: str,
        source_memory_ids: list[str],
        tier: str,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        actor: str = "",
    ) -> str:
        """记录记忆合并事件（多个来源合并到一个目标）"""
        event_id = self.record(
            memory_id=target_memory_id,
            event_type=EventType.MERGED,
            tier=tier,
            before=before,
            after=after,
            actor=actor,
            summary=f"合并 {len(source_memory_ids)} 条记忆到 {target_memory_id[:12]}",
        )
        # 为每个源记忆建立 merges_into 边
        for src_id in source_memory_ids:
            src_events = self._store.db.execute(
                "SELECT event_id FROM temporal_events "
                "WHERE memory_id=? ORDER BY created_at DESC LIMIT 1",
                (src_id,),
            ).fetchall()
            for se in src_events:
                self._add_edge(
                    source=se["event_id"],
                    target=event_id,
                    relation=EdgeRelation.MERGES_INTO,
                )
        self._store.db.commit()
        return event_id

    def record_split(
        self,
        source_memory_id: str,
        target_memory_ids: list[str],
        tier: str,
        actor: str = "",
    ) -> str:
        """记录记忆分裂事件（一条记忆分裂为多条）"""
        # 源头记录
        src_event = self._store.db.execute(
            "SELECT event_id FROM temporal_events "
            "WHERE memory_id=? ORDER BY created_at DESC LIMIT 1",
            (source_memory_id,),
        ).fetchone()
        src_event_id = src_event["event_id"] if src_event else None

        split_event_id = _gen_id("split")
        now = _now()

        self._store.db.execute(
            """INSERT INTO temporal_events
               (event_id, memory_id, event_type, tier,
                changed_fields, summary, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (
                split_event_id,
                source_memory_id,
                EventType.SPLIT,
                tier,
                "[]",
                f"分裂为 {len(target_memory_ids)} 条记忆",
                now,
            ),
        )

        if src_event_id:
            self._add_edge(src_event_id, split_event_id, EdgeRelation.EVOLVES_TO)

        for tgt_id in target_memory_ids:
            tgt_event = self.record(
                memory_id=tgt_id,
                event_type=EventType.CREATED,
                tier=tier,
                parent_event=split_event_id,
                actor=actor,
                summary=f"从 {source_memory_id[:12]} 分裂而来",
                auto_link=False,
            )
            self._add_edge(
                split_event_id, tgt_event,
                EdgeRelation.SPLITS_FROM,
            )

        self._store.db.commit()
        return split_event_id

    def record_heal(
        self,
        memory_id: str,
        tier: str,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        actor: str = "healer",
    ) -> str:
        """记录自修复事件"""
        return self.record(
            memory_id=memory_id,
            event_type=EventType.HEALED,
            tier=tier,
            before=before,
            after=after,
            actor=actor,
            summary=f"自修复 {memory_id[:12]}",
        )

    # ── 边管理 ───────────────────────────────────────────

    def _add_edge(
        self,
        source: str,
        target: str,
        relation: str = EdgeRelation.EVOLVES_TO,
        weight: float = 1.0,
    ) -> None:
        """添加一条因果边"""
        self._store.db.execute(
            """INSERT OR IGNORE INTO temporal_graph_edges
               (source_event, target_event, relation, weight, created_at)
               VALUES (?,?,?,?,?)""",
            (source, target, relation, weight, _now()),
        )

    def link_events(
        self,
        source_event_id: str,
        target_event_id: str,
        relation: str = EdgeRelation.RELATED_TO,
    ) -> bool:
        """手动在两个事件之间建立关联边"""
        if relation not in EdgeRelation._all:
            return False
        self._add_edge(source_event_id, target_event_id, relation)
        self._store.db.commit()
        return True

    # ── 查询时间线 ──────────────────────────────────────

    def timeline(
        self,
        memory_id: str,
        include_snapshots: bool = False,
    ) -> list[TemporalEvent]:
        """
        追溯一条记忆的完整演化历史（按时间升序）。

        Args:
            memory_id: 要追溯的记忆 ID
            include_snapshots: 是否包含 before/after 快照

        Returns:
            时间线事件列表（最早的在前）
        """
        rows = self._store.db.execute(
            "SELECT * FROM temporal_events "
            "WHERE memory_id=? ORDER BY created_at ASC",
            (memory_id,),
        ).fetchall()
        return [self._row_to_event(dict(r), include_snapshots) for r in rows]

    def event_detail(self, event_id: str) -> TemporalEvent | None:
        """查询单个事件详情"""
        row = self._store.db.execute(
            "SELECT * FROM temporal_events WHERE event_id=?",
            (event_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_event(dict(row), include_snapshots=True)

    def timeline_by_type(
        self,
        event_type: str,
        limit: int = 100,
    ) -> list[TemporalEvent]:
        """按事件类型查询"""
        rows = self._store.db.execute(
            "SELECT * FROM temporal_events "
            "WHERE event_type=? ORDER BY created_at DESC LIMIT ?",
            (event_type, limit),
        ).fetchall()
        return [self._row_to_event(dict(r)) for r in rows]

    # ── 事件关系 ────────────────────────────────────────

    def event_children(self, event_id: str) -> list[TemporalEvent]:
        """查询一个事件的所有子事件（出边）"""
        rows = self._store.db.execute(
            "SELECT te.* FROM temporal_events te "
            "JOIN temporal_graph_edges e ON te.event_id = e.target_event "
            "WHERE e.source_event=? ORDER BY te.created_at ASC",
            (event_id,),
        ).fetchall()
        return [self._row_to_event(dict(r)) for r in rows]

    def event_parents(self, event_id: str) -> list[TemporalEvent]:
        """查询一个事件的所有父事件（入边）"""
        rows = self._store.db.execute(
            "SELECT te.* FROM temporal_events te "
            "JOIN temporal_graph_edges e ON te.event_id = e.source_event "
            "WHERE e.target_event=? ORDER BY te.created_at ASC",
            (event_id,),
        ).fetchall()
        return [self._row_to_event(dict(r)) for r in rows]

    def event_edges(self, event_id: str) -> list[dict[str, Any]]:
        """查询事件关联的所有边"""
        rows = self._store.db.execute(
            "SELECT * FROM temporal_graph_edges "
            "WHERE source_event=? OR target_event=? "
            "ORDER BY created_at ASC",
            (event_id, event_id),
        ).fetchall()
        return [dict(r) for r in rows]

    # ── 分支与合并检测 ──────────────────────────────────

    def detect_forks(self, since: str | None = None) -> list[dict[str, Any]]:
        """
        检测记忆演化中的分支事件（一条记忆同时衍生出多条）。
        Returns:
            [{source_memory_id, source_event_id,
              fork_event_id, branches: [event_id, ...], created_at}, ...]
        """
        condition = ""
        params: list[Any] = []
        if since:
            condition = "AND e.created_at >= ?"
            params.append(since)

        rows = self._store.db.execute(
            """SELECT e.source_event, e.relation,
                      COUNT(*) as edge_count
               FROM temporal_graph_edges e
               WHERE e.relation=? {cond}
               GROUP BY e.source_event, e.relation
               HAVING COUNT(*) > 1
               ORDER BY edge_count DESC""".format(cond=condition),
            [EdgeRelation.SPLITS_FROM] + params,
        ).fetchall()

        forks: list[dict[str, Any]] = []
        for r in rows:
            src = self.event_detail(r["source_event"])
            branches = self.event_children(r["source_event"])
            forks.append({
                "source_event_id": r["source_event"],
                "source_memory_id": src.memory_id if src else "unknown",
                "branch_count": r["edge_count"],
                "branches": [b.event_id for b in branches],
                "created_at": r.get("created_at", ""),
            })
        return forks

    def detect_merges(self, since: str | None = None) -> list[dict[str, Any]]:
        """
        检测记忆演化中的合并事件。
        Returns:
            [{target_memory_id, target_event_id,
              sources: [event_id, ...], created_at}, ...]
        """
        condition = ""
        params: list[Any] = []
        if since:
            condition = "AND e.created_at >= ?"
            params.append(since)

        rows = self._store.db.execute(
            """SELECT e.target_event, e.relation,
                      COUNT(*) as edge_count
               FROM temporal_graph_edges e
               WHERE e.relation=? {cond}
               GROUP BY e.target_event, e.relation
               HAVING COUNT(*) > 1
               ORDER BY edge_count DESC""".format(cond=condition),
            [EdgeRelation.MERGES_INTO] + params,
        ).fetchall()

        merges: list[dict[str, Any]] = []
        for r in rows:
            tgt = self.event_detail(r["target_event"])
            parents = self.event_parents(r["target_event"])
            merges.append({
                "target_event_id": r["target_event"],
                "target_memory_id": tgt.memory_id if tgt else "unknown",
                "source_count": r["edge_count"],
                "sources": [p.event_id for p in parents],
                "created_at": r.get("created_at", ""),
            })
        return merges

    # ── 回滚 ─────────────────────────────────────────────

    def rollback_to(
        self,
        memory_id: str,
        target_event_id: str,
        actor: str = "user",
    ) -> bool:
        """
        将记忆回滚到指定事件后的状态。

        读取 target_event 的 after_snapshot，将其恢复为记忆的当前内容。
        并记录 ROLLED_BACK 事件。

        Returns:
            True 如果回滚成功
        """
        event = self.event_detail(target_event_id)
        if not event:
            return False
        if event.memory_id != memory_id:
            return False

        snapshot = event.after_snapshot
        if not snapshot:
            return False

        # 获取当前状态快照
        current_entry = self._store.by_id(memory_id)
        current_snapshot = {}
        if current_entry:
            current_snapshot = {
                "content": current_entry.content if hasattr(current_entry, 'content') else "",
                "title": current_entry.title if hasattr(current_entry, 'title') else "",
                "tags": list(current_entry.tags) if hasattr(current_entry, 'tags') else [],
            }

        # 应用 snapshot 到存储
        tier = event.tier
        table = self._table_name(tier)
        updates: list[str] = []
        params: list[Any] = []

        for field in ("content", "title"):
            if field in snapshot:
                updates.append(f"{field}=?")
                params.append(snapshot[field])

        if updates:
            params.append(memory_id)
            self._store.db.execute(
                f"UPDATE {table} SET {', '.join(updates)} WHERE entry_id=?",
                params,
            )

        # 记录回滚事件
        self.record(
            memory_id=memory_id,
            event_type=EventType.ROLLED_BACK,
            tier=tier,
            before=current_snapshot,
            after=snapshot,
            changed_fields=list(snapshot.keys()),
            parent_event=target_event_id,
            actor=actor,
            summary=f"回滚到事件 {target_event_id[:12]}",
        )

        self._store.db.commit()
        return True

    # ── 全图查询 ───────────────────────────────────────

    def graph(
        self,
        memory_id: str | None = None,
        max_events: int = 200,
    ) -> dict[str, Any]:
        """
        获取演化图谱，格式兼容 D3 力导向图。

        Args:
            memory_id: 限定到某条记忆（None=全部）
            max_events: 最大事件数

        Returns:
            {nodes: [{id, memory_id, type, tier, summary, created_at}],
             edges: [{source, target, relation, weight}]}
        """
        if memory_id:
            nodes = self._store.db.execute(
                "SELECT * FROM temporal_events "
                "WHERE memory_id=? ORDER BY created_at ASC LIMIT ?",
                (memory_id, max_events),
            ).fetchall()
        else:
            nodes = self._store.db.execute(
                "SELECT * FROM temporal_events "
                "ORDER BY created_at DESC LIMIT ?",
                (max_events,),
            ).fetchall()

        event_ids = [r["event_id"] for r in nodes]

        if event_ids:
            placeholders = ",".join("?" * len(event_ids))
            edges = self._store.db.execute(
                f"SELECT * FROM temporal_graph_edges "
                f"WHERE source_event IN ({placeholders}) "
                f"AND target_event IN ({placeholders})",
                event_ids + event_ids,
            ).fetchall()
        else:
            edges = []

        return {
            "nodes": [
                {
                    "id": r["event_id"],
                    "memory_id": r["memory_id"][:16],
                    "type": r["event_type"],
                    "tier": r.get("tier", ""),
                    "summary": (r.get("summary", "") or "")[:60],
                    "created_at": r.get("created_at", ""),
                }
                for r in nodes
            ],
            "edges": [
                {
                    "source": e["source_event"],
                    "target": e["target_event"],
                    "relation": e["relation"],
                    "weight": e.get("weight", 1.0),
                }
                for e in edges
            ],
        }

    def graphviz(self) -> str:
        """输出 GraphViz DOT 格式"""
        g = self.graph(max_events=100)
        lines = ["digraph TemporalGraph {"]
        lines.append("  rankdir=LR;")
        lines.append("  node [shape=box, style=rounded];")

        for n in g["nodes"]:
            label = f"{n['type']}\\n{n['summary']}"
            lines.append(f'  "{n["id"][:16]}" [label="{label}"];')

        for e in g["edges"]:
            style = "solid"
            if e["relation"] == "related_to":
                style = "dashed"
            elif e["relation"] in ("splits_from", "rolls_back"):
                style = "dotted"
            lines.append(
                f'  "{e["source"][:16]}" -> "{e["target"][:16]}" '
                f'[label="{e["relation"]}", style={style}];'
            )

        lines.append("}")
        return "\n".join(lines)

    # ── 统计 ──────────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        """时间线图谱统计"""
        total_events = self._store.db.execute(
            "SELECT COUNT(*) FROM temporal_events"
        ).fetchone()[0]

        by_type = self._store.db.execute(
            "SELECT event_type, COUNT(*) as cnt "
            "FROM temporal_events GROUP BY event_type"
        ).fetchall()

        total_edges = self._store.db.execute(
            "SELECT COUNT(*) FROM temporal_graph_edges"
        ).fetchone()[0]

        unique_memories = self._store.db.execute(
            "SELECT COUNT(DISTINCT memory_id) FROM temporal_events"
        ).fetchone()[0]

        return {
            "total_events": total_events,
            "total_edges": total_edges,
            "unique_memories": unique_memories,
            "by_type": {r["event_type"]: r["cnt"] for r in by_type},
        }

    # ── 内部工具 ─────────────────────────────────────────

    def _table_name(self, tier: str) -> str:
        mapping = {
            "core": "impressions",
            "ephemeral": "impressions",
            "working": "impressions",
            "longterm": "patterns",
            "archetype": "principles",
        }
        return mapping.get(tier, "impressions")

    def _row_to_event(
        self, row: dict[str, Any], include_snapshots: bool = False
    ) -> TemporalEvent:
        before = json.loads(row.get("before_snapshot", "{}")) if include_snapshots else None
        after = json.loads(row.get("after_snapshot", "{}")) if include_snapshots else None
        return TemporalEvent(
            event_id=row["event_id"],
            memory_id=row["memory_id"],
            event_type=row["event_type"],
            tier=row.get("tier", ""),
            changed_fields=json.loads(row.get("changed_fields", "[]")),
            before_snapshot=before,
            after_snapshot=after,
            parent_event=row.get("parent_event"),
            actor=row.get("actor", ""),
            summary=row.get("summary", ""),
            created_at=row.get("created_at"),
        )
