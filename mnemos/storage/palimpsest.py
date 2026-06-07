"""
记忆存储后端 — Palimpsest（重写本）引擎

设计哲学:
  记忆如重写本——旧墨迹不会被擦除，新认知书写于其上。
  查询时既能读到"当前信念"，也能追溯"我们曾相信什么"。

存储选型:
  默认 SQLite + FTS5（零配置启动）
  可选 pgvector（生产环境向量检索）
  实体关系用共现矩阵模拟图谱（避免强制 Neo4j 依赖）

表设计:
  impressions  (L1) — 原始对话片段，可被蒸馏为模式
  patterns     (L2) — 从印象中识别的规律
  principles   (L3) — 可指导行动的核心原则
  entity_index      — 实体→记忆的倒排索引
  entity_cooccur    — 实体共现矩阵（图谱轻量替代）
  belief_history    — 信念修订全量历史
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator

from mnemos.core.models import (
    BeliefRecord,
    EntityRef,
    MemoryEntry,
    MemoryTier,
    ScopeType,
    TemporalAnchor,
)


# ── SQL 定义 ─────────────────────────────────────────────


_CREATE_IMPRESSIONS = """
CREATE TABLE IF NOT EXISTS impressions (
    rowid       INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id    TEXT UNIQUE NOT NULL,
    title       TEXT NOT NULL DEFAULT '',
    content     TEXT NOT NULL,
    scope_type  TEXT NOT NULL DEFAULT 'tenant',
    scope_id    TEXT NOT NULL DEFAULT '',
    tags_json   TEXT NOT NULL DEFAULT '[]',
    parent_id   TEXT,
    related_json TEXT NOT NULL DEFAULT '[]',
    anchors_json TEXT NOT NULL DEFAULT '[]',
    entities_json TEXT NOT NULL DEFAULT '[]',
    beliefs_json TEXT NOT NULL DEFAULT '[]',
    embedding_model TEXT NOT NULL DEFAULT '',
    decay       REAL NOT NULL DEFAULT 1.0,
    hits        INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    touched_at  TEXT NOT NULL
);
"""

_CREATE_PATTERNS = """
CREATE TABLE IF NOT EXISTS patterns (
    entry_id    TEXT PRIMARY KEY,
    title       TEXT NOT NULL DEFAULT '',
    content     TEXT NOT NULL,
    scope_type  TEXT NOT NULL DEFAULT 'tenant',
    scope_id    TEXT NOT NULL DEFAULT '',
    tags_json   TEXT NOT NULL DEFAULT '[]',
    entities_json TEXT NOT NULL DEFAULT '[]',
    beliefs_json TEXT NOT NULL DEFAULT '[]',
    source_json TEXT NOT NULL DEFAULT '[]',
    confidence  TEXT NOT NULL DEFAULT 'tentative',
    created_at  TEXT NOT NULL,
    touched_at  TEXT NOT NULL
);
"""

_CREATE_PRINCIPLES = """
CREATE TABLE IF NOT EXISTS principles (
    entry_id    TEXT PRIMARY KEY,
    title       TEXT NOT NULL DEFAULT '',
    content     TEXT NOT NULL,
    scope_type  TEXT NOT NULL DEFAULT 'universe',
    scope_id    TEXT NOT NULL DEFAULT '',
    tags_json   TEXT NOT NULL DEFAULT '[]',
    entities_json TEXT NOT NULL DEFAULT '[]',
    source_json TEXT NOT NULL DEFAULT '[]',
    confidence  TEXT NOT NULL DEFAULT 'bedrock',
    created_at  TEXT NOT NULL,
    touched_at  TEXT NOT NULL
);
"""

_CREATE_ENTITY_INDEX = """
CREATE TABLE IF NOT EXISTS entity_index (
    entity_id   TEXT NOT NULL,
    label       TEXT NOT NULL,
    etype       TEXT NOT NULL DEFAULT 'concept',
    memory_id   TEXT NOT NULL,
    tier        TEXT NOT NULL DEFAULT 'impression',
    PRIMARY KEY (entity_id, memory_id)
);
"""

_CREATE_ENTITY_COOCCUR = """
CREATE TABLE IF NOT EXISTS entity_cooccur (
    a           TEXT NOT NULL,
    b           TEXT NOT NULL,
    weight      INTEGER NOT NULL DEFAULT 1,
    last_seen   TEXT NOT NULL,
    PRIMARY KEY (a, b)
);
"""

_CREATE_BELIEF_LOG = """
CREATE TABLE IF NOT EXISTS belief_log (
    belief_id   TEXT PRIMARY KEY,
    memory_id   TEXT NOT NULL,
    content     TEXT NOT NULL,
    confidence  TEXT NOT NULL,
    source      TEXT,
    adopted_at  TEXT NOT NULL,
    superseded  TEXT,
    superseded_at TEXT
);
"""

_CREATE_FTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS impression_fts USING fts5(
    entry_id UNINDEXED,
    title,
    content,
    content='impressions',
    content_rowid='rowid',
    tokenize='unicode61'
);
"""

_FTS_TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS fts_ins AFTER INSERT ON impressions BEGIN
    INSERT INTO impression_fts(rowid, entry_id, title, content)
    VALUES (new.rowid, new.entry_id, new.title, new.content);
END;
CREATE TRIGGER IF NOT EXISTS fts_del AFTER DELETE ON impressions BEGIN
    INSERT INTO impression_fts(impression_fts, rowid, entry_id, title, content)
    VALUES ('delete', old.rowid, old.entry_id, old.title, old.content);
END;
CREATE TRIGGER IF NOT EXISTS fts_upd AFTER UPDATE ON impressions BEGIN
    INSERT INTO impression_fts(impression_fts, rowid, entry_id, title, content)
    VALUES ('delete', old.rowid, old.entry_id, old.title, old.content);
    INSERT INTO impression_fts(rowid, entry_id, title, content)
    VALUES (new.rowid, new.entry_id, new.title, new.content);
END;
"""

_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_imp_scope   ON impressions(scope_type, scope_id);
CREATE INDEX IF NOT EXISTS idx_imp_time    ON impressions(created_at);
CREATE INDEX IF NOT EXISTS idx_imp_decay   ON impressions(decay);
CREATE INDEX IF NOT EXISTS idx_pat_scope   ON patterns(scope_type, scope_id);
CREATE INDEX IF NOT EXISTS idx_pri_scope   ON principles(scope_type, scope_id);
CREATE INDEX IF NOT EXISTS idx_ent_mem     ON entity_index(memory_id);
CREATE INDEX IF NOT EXISTS idx_ent_label   ON entity_index(label);
CREATE INDEX IF NOT EXISTS idx_bel_mem     ON belief_log(memory_id);
"""

ALL_SCHEMA = "\n".join([
    _CREATE_IMPRESSIONS, _CREATE_PATTERNS, _CREATE_PRINCIPLES,
    _CREATE_ENTITY_INDEX, _CREATE_ENTITY_COOCCUR, _CREATE_BELIEF_LOG,
    _CREATE_FTS, _FTS_TRIGGERS, _INDEXES,
])


# ── 存储引擎 ─────────────────────────────────────────────


class PalimpsestStore:
    """
    记忆重写本 — 核心存储引擎。

    使用示例:
        store = PalimpsestStore("memory.db")
        store.connect()
        store.inscribe(entry)
        results = store.search("关键词")
        store.close()
    """

    def __init__(self, path: str | Path = ":memory:"):
        self._path = Path(path)
        self._conn: sqlite3.Connection | None = None

    # ── 生命周期 ──────────────────────────────────────

    def connect(self) -> sqlite3.Connection:
        """建立连接并初始化表结构"""
        if self._conn is not None:
            return self._conn
        self._conn = sqlite3.connect(str(self._path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(ALL_SCHEMA)
        return self._conn

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    @property
    def db(self) -> sqlite3.Connection:
        return self.connect()

    def __enter__(self) -> "PalimpsestStore":
        self.connect()
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    # ── 写入 ──────────────────────────────────────────

    def inscribe(self, entry: MemoryEntry) -> str:
        """将一条记忆写入对应层次"""
        now = _now()
        row = _serialize_impression(entry, now)

        if entry.tier == MemoryTier.IMPRESSION:
            self.db.execute(
                """INSERT INTO impressions
                   (entry_id, title, content, scope_type, scope_id,
                    tags_json, parent_id, related_json,
                    anchors_json, entities_json, beliefs_json,
                    embedding_model, decay, hits, created_at, touched_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                row,
            )
            self._index_entities(entry.entry_id, "impression", entry.entities)
            self._update_cooccur(entry.entities, now)
            self._log_beliefs(entry.entry_id, entry.beliefs)

        elif entry.tier == MemoryTier.PATTERN:
            self.db.execute(
                """INSERT INTO patterns
                   (entry_id, title, content, scope_type, scope_id,
                    tags_json, entities_json, beliefs_json,
                    source_json, confidence, created_at, touched_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                _serialize_pattern(entry, now),
            )
            self._index_entities(entry.entry_id, "pattern", entry.entities)

        elif entry.tier == MemoryTier.PRINCIPLE:
            self.db.execute(
                """INSERT INTO principles
                   (entry_id, title, content, scope_type, scope_id,
                    tags_json, entities_json, source_json,
                    confidence, created_at, touched_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                _serialize_principle(entry, now),
            )
            self._index_entities(entry.entry_id, "principle", entry.entities)

        self.db.commit()
        return entry.entry_id

    def revise(
        self, entry_id: str, tier: MemoryTier,
        updates: dict[str, Any]
    ) -> bool:
        """修改已有记忆的内容或信念"""
        table = _table(tier)
        allowed = {"title", "content", "decay", "tags_json",
                   "entities_json", "beliefs_json", "confidence"}
        safe = {k: v for k, v in updates.items() if k in allowed}
        if not safe:
            return False
        sets = ", ".join(f"{k}=?" for k in safe)
        self.db.execute(
            f"UPDATE {table} SET {sets} WHERE entry_id=?",
            list(safe.values()) + [entry_id],
        )
        if "beliefs_json" in safe:
            beliefs = [BeliefRecord(**b) for b in json.loads(safe["beliefs_json"])]
            self._log_beliefs(entry_id, beliefs)
        self.db.commit()
        return True

    # ── 查询 ──────────────────────────────────────────

    def by_id(self, entry_id: str) -> MemoryEntry | None:
        """按 ID 精确召回"""
        for table, tier in [("impressions", MemoryTier.IMPRESSION),
                            ("patterns", MemoryTier.PATTERN),
                            ("principles", MemoryTier.PRINCIPLE)]:
            row = self.db.execute(
                f"SELECT * FROM {table} WHERE entry_id=?", (entry_id,)
            ).fetchone()
            if row:
                return _deserialize(dict(row), tier)
        return None

    def fts(self, query: str, limit: int = 20) -> list[MemoryEntry]:
        """全文搜索。FTS5 先尝试；中文回退 LIKE。"""
        rows = self.db.execute(
            """SELECT i.* FROM impressions i
               JOIN impression_fts f ON i.rowid = f.rowid
               WHERE impression_fts MATCH ?
               ORDER BY rank LIMIT ?""",
            (query, limit),
        ).fetchall()
        if rows:
            return [_deserialize(dict(r), MemoryTier.IMPRESSION) for r in rows]

        # CJK 回退：LIKE 搜索
        rows = self.db.execute(
            "SELECT * FROM impressions WHERE content LIKE ? OR title LIKE ? "
            "ORDER BY created_at DESC LIMIT ?",
            (f"%{query}%", f"%{query}%", limit),
        ).fetchall()
        return [_deserialize(dict(r), MemoryTier.IMPRESSION) for r in rows]

    def by_scope(
        self, scope_type: ScopeType, scope_id: str,
        tiers: list[MemoryTier] | None = None, limit: int = 50
    ) -> list[MemoryEntry]:
        """按归属范围召回"""
        if tiers is None:
            tiers = list(MemoryTier)
        results: list[MemoryEntry] = []
        for tier in tiers:
            rows = self.db.execute(
                f"SELECT * FROM {_table(tier)} "
                "WHERE scope_type=? AND scope_id=? "
                "ORDER BY created_at DESC LIMIT ?",
                (scope_type.value, scope_id, limit),
            ).fetchall()
            results.extend(_deserialize(dict(r), tier) for r in rows)
        results.sort(key=lambda e: e.created_at, reverse=True)
        return results[:limit]

    def by_entity(self, label: str, limit: int = 20) -> list[MemoryEntry]:
        """按实体标签召回关联记忆"""
        rows = self.db.execute(
            """SELECT DISTINCT memory_id, tier FROM entity_index
               WHERE label LIKE ? LIMIT ?""",
            (f"%{label}%", limit),
        ).fetchall()
        results: list[MemoryEntry] = []
        for r in rows:
            entry = self.by_id(r["memory_id"])
            if entry:
                results.append(entry)
        return results

    def by_time(
        self, after: datetime | None = None,
        before: datetime | None = None, limit: int = 50
    ) -> list[MemoryEntry]:
        """按时间范围召回"""
        conds: list[str] = []
        params: list[Any] = []
        if after:
            conds.append("created_at >= ?")
            params.append(after.isoformat())
        if before:
            conds.append("created_at <= ?")
            params.append(before.isoformat())
        where = " AND ".join(conds) if conds else "1=1"
        params.append(limit)
        rows = self.db.execute(
            f"SELECT * FROM impressions WHERE {where} ORDER BY created_at DESC LIMIT ?",
            params,
        ).fetchall()
        return [_deserialize(dict(r), MemoryTier.IMPRESSION) for r in rows]

    def traverse(
        self, entry_id: str, depth: int = 2
    ) -> list[MemoryEntry]:
        """沿关联链遍历相关记忆（BFS）"""
        seen: set[str] = {entry_id}
        frontier = [entry_id]
        results: list[MemoryEntry] = []

        for _ in range(depth):
            next_frontier: list[str] = []
            for eid in frontier:
                entry = self.by_id(eid)
                if entry:
                    results.append(entry)
                    for rid in entry.related_ids:
                        if rid not in seen:
                            seen.add(rid)
                            next_frontier.append(rid)
            frontier = next_frontier
            if not frontier:
                break
        return results

    def entity_graph(
        self, label: str, limit: int = 20
    ) -> dict[str, Any]:
        """获取实体关系图谱"""
        rows = self.db.execute(
            """SELECT a, b, weight, last_seen FROM entity_cooccur
               WHERE a=? OR b=? ORDER BY weight DESC LIMIT ?""",
            (label, label, limit),
        ).fetchall()
        nodes: set[str] = {label}
        edges: list[dict] = []
        for r in rows:
            nodes.add(r["a"])
            nodes.add(r["b"])
            edges.append({
                "source": r["a"], "target": r["b"],
                "weight": r["weight"],
                "last_seen": r["last_seen"],
            })
        return {
            "center": label,
            "nodes": [{"id": n, "label": n} for n in nodes],
            "edges": edges,
        }

    def belief_chain(self, memory_id: str) -> list[dict]:
        """查看一条记忆的信念演变链"""
        rows = self.db.execute(
            "SELECT * FROM belief_log WHERE memory_id=? ORDER BY adopted_at",
            (memory_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ── 维护 ──────────────────────────────────────────

    def decay_stale(self, rate: float = 0.01) -> int:
        """对长期未访问的记忆施加衰减"""
        c = self.db.execute(
            "UPDATE impressions SET decay = MAX(0, decay - ?) WHERE touched_at < ?",
            (rate, _now()),
        )
        self.db.commit()
        return c.rowcount

    def purge_dead(self, before: datetime) -> int:
        """清除衰减归零的旧记忆"""
        c = self.db.execute(
            "DELETE FROM impressions WHERE decay <= 0 AND created_at < ?",
            (before.isoformat(),),
        )
        self.db.commit()
        return c.rowcount

    def count(self) -> dict[str, int]:
        """返回各层计数"""
        return {
            "impressions": self.db.execute(
                "SELECT COUNT(*) FROM impressions"
            ).fetchone()[0],
            "patterns": self.db.execute(
                "SELECT COUNT(*) FROM patterns"
            ).fetchone()[0],
            "principles": self.db.execute(
                "SELECT COUNT(*) FROM principles"
            ).fetchone()[0],
            "entities": self.db.execute(
                "SELECT COUNT(DISTINCT entity_id) FROM entity_index"
            ).fetchone()[0],
            "cooccur_pairs": self.db.execute(
                "SELECT COUNT(*) FROM entity_cooccur"
            ).fetchone()[0],
            "beliefs": self.db.execute(
                "SELECT COUNT(*) FROM belief_log"
            ).fetchone()[0],
        }

    # ── 内部辅助 ──────────────────────────────────────

    def _index_entities(
        self, memory_id: str, tier: str, entities: list[EntityRef]
    ) -> None:
        for e in entities:
            self.db.execute(
                "INSERT OR REPLACE INTO entity_index "
                "(entity_id, label, etype, memory_id, tier) VALUES (?,?,?,?,?)",
                (e.entity_id, e.label, e.entity_type, memory_id, tier),
            )

    def _update_cooccur(
        self, entities: list[EntityRef], now: str
    ) -> None:
        labels = [e.label for e in entities]
        for i in range(len(labels)):
            for j in range(i + 1, len(labels)):
                a, b = sorted([labels[i], labels[j]])
                self.db.execute(
                    "INSERT INTO entity_cooccur (a, b, weight, last_seen) "
                    "VALUES (?,?,1,?) ON CONFLICT(a,b) DO UPDATE SET "
                    "weight=weight+1, last_seen=?",
                    (a, b, now, now),
                )

    def _log_beliefs(
        self, memory_id: str, beliefs: list[BeliefRecord]
    ) -> None:
        for b in beliefs:
            self.db.execute(
                "INSERT OR REPLACE INTO belief_log "
                "(belief_id, memory_id, content, confidence, source, "
                "adopted_at, superseded, superseded_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (
                    b.belief_id, memory_id, b.content, b.confidence.value,
                    b.source, b.adopted_at.isoformat(),
                    b.superseded_by,
                    b.superseded_at.isoformat() if b.superseded_at else None,
                ),
            )


# ── 序列化辅助 ───────────────────────────────────────────


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _table(tier: MemoryTier) -> str:
    return {
        MemoryTier.IMPRESSION: "impressions",
        MemoryTier.PATTERN: "patterns",
        MemoryTier.PRINCIPLE: "principles",
    }[tier]


def _serialize_impression(entry: MemoryEntry, now: str) -> tuple:
    return (
        entry.entry_id, entry.title, entry.content,
        entry.scope.value, entry.scope_id,
        _json(entry.tags),
        entry.parent_id,
        _json(entry.related_ids),
        _json([a.model_dump(mode="json") for a in entry.anchors]),
        _json([e.model_dump(mode="json") for e in entry.entities]),
        _json([b.model_dump(mode="json") for b in entry.beliefs]),
        entry.embedding_model,
        entry.decay_factor,
        entry.access_count,
        entry.created_at.isoformat(),
        now,
    )


def _serialize_pattern(entry: MemoryEntry, now: str) -> tuple:
    return (
        entry.entry_id, entry.title, entry.content,
        entry.scope.value, entry.scope_id,
        _json(entry.tags),
        _json([e.model_dump(mode="json") for e in entry.entities]),
        _json([b.model_dump(mode="json") for b in entry.beliefs]),
        _json(entry.related_ids),
        entry.beliefs[0].confidence.value if entry.beliefs else "tentative",
        entry.created_at.isoformat(),
        now,
    )


def _serialize_principle(entry: MemoryEntry, now: str) -> tuple:
    return (
        entry.entry_id, entry.title, entry.content,
        entry.scope.value, entry.scope_id,
        _json(entry.tags),
        _json([e.model_dump(mode="json") for e in entry.entities]),
        _json(entry.related_ids),
        entry.beliefs[0].confidence.value if entry.beliefs else "bedrock",
        entry.created_at.isoformat(),
        now,
    )


def _deserialize(row: dict, tier: MemoryTier) -> MemoryEntry:
    """数据库行 → MemoryEntry"""
    created = datetime.fromisoformat(row["created_at"])
    touched = datetime.fromisoformat(row.get("touched_at", row["created_at"]))

    entry = MemoryEntry(
        entry_id=row["entry_id"],
        tier=tier,
        title=row.get("title", ""),
        content=row.get("content", ""),
        scope=ScopeType(row.get("scope_type", "tenant")),
        scope_id=row.get("scope_id", ""),
        tags=_from_json(row.get("tags_json", "[]")),
        entities=[EntityRef(**e) for e in _from_json(row.get("entities_json", "[]"))],
        beliefs=[BeliefRecord(**b) for b in _from_json(row.get("beliefs_json", "[]"))],
        related_ids=_from_json(row.get("related_json", row.get("source_json", "[]"))),
        parent_id=row.get("parent_id"),
        created_at=created,
        last_accessed_at=touched,
        access_count=row.get("hits", row.get("access_count", 0)),
        decay_factor=row.get("decay", 1.0),
    )

    if tier == MemoryTier.IMPRESSION:
        if "anchors_json" in row:
            entry.anchors = [
                TemporalAnchor(**a) for a in _from_json(row["anchors_json"])
            ]
        if "related_json" in row:
            entry.related_ids = _from_json(row["related_json"])

    return entry


def _json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)


def _from_json(text: str) -> Any:
    return json.loads(text) if text else []
