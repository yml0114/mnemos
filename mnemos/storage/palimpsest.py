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
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

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
    touched_at  TEXT NOT NULL,
    memory_type TEXT NOT NULL DEFAULT 'timeless',
    state_key   TEXT NOT NULL DEFAULT '',
    event_start TEXT,
    event_end   TEXT,
    is_active   INTEGER NOT NULL DEFAULT 1,
    temporal_precision TEXT NOT NULL DEFAULT 'day'
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
    decay       REAL NOT NULL DEFAULT 1.0,
    hits        INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    touched_at  TEXT NOT NULL,
    memory_type TEXT NOT NULL DEFAULT 'timeless',
    state_key   TEXT NOT NULL DEFAULT '',
    event_start TEXT,
    event_end   TEXT,
    is_active   INTEGER NOT NULL DEFAULT 1,
    temporal_precision TEXT NOT NULL DEFAULT 'day'
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
    decay       REAL NOT NULL DEFAULT 1.0,
    hits        INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    touched_at  TEXT NOT NULL,
    memory_type TEXT NOT NULL DEFAULT 'timeless',
    state_key   TEXT NOT NULL DEFAULT '',
    event_start TEXT,
    event_end   TEXT,
    is_active   INTEGER NOT NULL DEFAULT 1,
    temporal_precision TEXT NOT NULL DEFAULT 'day'
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

_CREATE_ENTITY_EDGES = """
CREATE TABLE IF NOT EXISTS entity_edges (
    from_id     TEXT NOT NULL,
    to_id       TEXT NOT NULL,
    relation    TEXT NOT NULL DEFAULT 'related',
    weight      REAL NOT NULL DEFAULT 1.0,
    metadata    TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (from_id, to_id, relation)
);
"""

_CREATE_EMBEDDINGS = """
CREATE TABLE IF NOT EXISTS embeddings (
    entry_id    TEXT PRIMARY KEY,
    model       TEXT NOT NULL,
    vector      BLOB NOT NULL,
    dim         INTEGER NOT NULL,
    dtype       TEXT NOT NULL DEFAULT 'float32',
    created_at  TEXT NOT NULL,
    FOREIGN KEY (entry_id) REFERENCES impressions(entry_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_emb_model ON embeddings(model);
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
    tokenize='trigram'
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
CREATE INDEX IF NOT EXISTS idx_pat_decay   ON patterns(decay);
CREATE INDEX IF NOT EXISTS idx_pri_scope   ON principles(scope_type, scope_id);
CREATE INDEX IF NOT EXISTS idx_pri_decay   ON principles(decay);
CREATE INDEX IF NOT EXISTS idx_ent_mem     ON entity_index(memory_id);
CREATE INDEX IF NOT EXISTS idx_ent_label   ON entity_index(label);
CREATE INDEX IF NOT EXISTS idx_bel_mem     ON belief_log(memory_id);
CREATE INDEX IF NOT EXISTS idx_edge_from   ON entity_edges(from_id);
CREATE INDEX IF NOT EXISTS idx_edge_to     ON entity_edges(to_id);
CREATE INDEX IF NOT EXISTS idx_edge_rel    ON entity_edges(relation);
"""

_CREATE_SYNC_LOG = """
CREATE TABLE IF NOT EXISTS sync_log (
    sync_id     TEXT PRIMARY KEY,
    memory_id   TEXT NOT NULL,
    entity_id   TEXT NOT NULL DEFAULT '',
    operation   TEXT NOT NULL CHECK (operation IN ('create', 'update', 'delete')),
    tier        TEXT NOT NULL DEFAULT 'impression',
    payload     TEXT NOT NULL DEFAULT '{}',
    node_id     TEXT NOT NULL DEFAULT 'local',
    vector_clock TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL,
    synced_at   TEXT,
    sync_status TEXT NOT NULL DEFAULT 'pending' CHECK (sync_status IN ('pending', 'inflight', 'conflict', 'done'))
);
CREATE INDEX IF NOT EXISTS idx_sync_mem   ON sync_log(memory_id);
CREATE INDEX IF NOT EXISTS idx_sync_node  ON sync_log(node_id);
CREATE INDEX IF NOT EXISTS idx_sync_stat  ON sync_log(sync_status);
CREATE INDEX IF NOT EXISTS idx_sync_time  ON sync_log(created_at);
"""

_CREATE_MEDIA_ATTACHMENTS = """
CREATE TABLE IF NOT EXISTS media_attachments (
    media_id    TEXT PRIMARY KEY,
    memory_id   TEXT NOT NULL,
    media_type  TEXT NOT NULL CHECK (media_type IN ('image', 'audio', 'video', 'file', 'link')),
    mime_type   TEXT NOT NULL DEFAULT '',
    filename    TEXT NOT NULL DEFAULT '',
    storage_uri TEXT NOT NULL DEFAULT '',
    byte_size   INTEGER NOT NULL DEFAULT 0,
    metadata    TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL,
    FOREIGN KEY (memory_id) REFERENCES impressions(entry_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_media_mem ON media_attachments(memory_id);
"""

_CREATE_MEDIA_EMBEDDINGS = """
CREATE TABLE IF NOT EXISTS media_embeddings (
    media_id    TEXT PRIMARY KEY,
    model       TEXT NOT NULL,
    vector      BLOB NOT NULL,
    dim         INTEGER NOT NULL,
    dtype       TEXT NOT NULL DEFAULT 'float32',
    modality    TEXT NOT NULL DEFAULT 'image',
    created_at  TEXT NOT NULL,
    FOREIGN KEY (media_id) REFERENCES media_attachments(media_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_media_emb_mod ON media_embeddings(model);
"""

_CREATE_INCONSISTENCY_LOG = """
CREATE TABLE IF NOT EXISTS inconsistency_log (
    issue_id    TEXT PRIMARY KEY,
    memory_id_a TEXT NOT NULL,
    memory_id_b TEXT,
    issue_type  TEXT NOT NULL CHECK (issue_type IN (
        'contradiction', 'duplication', 'outdated', 'orphan', 'conflict', 'schema_drift'
    )),
    severity    TEXT NOT NULL DEFAULT 'low' CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    description TEXT NOT NULL DEFAULT '',
    resolution  TEXT NOT NULL DEFAULT 'pending' CHECK (resolution IN ('pending', 'auto_fixed', 'superseded', 'dismissed')),
    resolved_at TEXT,
    detected_at TEXT NOT NULL,
    metadata    TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_incon_res  ON inconsistency_log(resolution);
CREATE INDEX IF NOT EXISTS idx_incon_type ON inconsistency_log(issue_type);
"""

_CREATE_TEMPORAL_EVENTS = """
CREATE TABLE IF NOT EXISTS temporal_events (
    event_id    TEXT PRIMARY KEY,
    memory_id   TEXT NOT NULL,
    event_type  TEXT NOT NULL DEFAULT 'observation',
    timestamp   TEXT NOT NULL,
    end_time    TEXT,
    precision   TEXT NOT NULL DEFAULT 'day',
    confidence  REAL NOT NULL DEFAULT 1.0,
    state_before TEXT,
    state_after TEXT,
    metadata    TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL,
    FOREIGN KEY (memory_id) REFERENCES impressions(entry_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_temp_ev_mem  ON temporal_events(memory_id);
CREATE INDEX IF NOT EXISTS idx_temp_ev_type ON temporal_events(event_type);
CREATE INDEX IF NOT EXISTS idx_temp_ev_ts   ON temporal_events(timestamp);
"""

_CREATE_TEMPORAL_GRAPH = """
CREATE TABLE IF NOT EXISTS temporal_graph_edges (
    from_event  TEXT NOT NULL,
    to_event    TEXT NOT NULL,
    relation    TEXT NOT NULL DEFAULT 'causes',
    weight      REAL NOT NULL DEFAULT 1.0,
    metadata    TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL,
    PRIMARY KEY (from_event, to_event, relation),
    FOREIGN KEY (from_event) REFERENCES temporal_events(event_id) ON DELETE CASCADE,
    FOREIGN KEY (to_event)   REFERENCES temporal_events(event_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_tge_from ON temporal_graph_edges(from_event);
CREATE INDEX IF NOT EXISTS idx_tge_to   ON temporal_graph_edges(to_event);
"""

ALL_SCHEMA = "\n".join([
    _CREATE_IMPRESSIONS, _CREATE_PATTERNS, _CREATE_PRINCIPLES,
    _CREATE_ENTITY_INDEX, _CREATE_ENTITY_COOCCUR, _CREATE_ENTITY_EDGES,
    _CREATE_BELIEF_LOG,
    _CREATE_EMBEDDINGS, _CREATE_FTS, _FTS_TRIGGERS, _INDEXES,
    _CREATE_SYNC_LOG,
    _CREATE_MEDIA_ATTACHMENTS, _CREATE_MEDIA_EMBEDDINGS,
    _CREATE_INCONSISTENCY_LOG,
    _CREATE_TEMPORAL_EVENTS, _CREATE_TEMPORAL_GRAPH,
    """
    CREATE TABLE IF NOT EXISTS sessions (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        last_message_id TEXT,
        condensed_up_to TEXT,
        metadata TEXT NOT NULL DEFAULT '{}'
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS messages (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
        role TEXT NOT NULL CHECK(role IN ('user','assistant','system')),
        agent_id TEXT NOT NULL DEFAULT '',
        tokens INTEGER NOT NULL DEFAULT 0,
        finish_reason TEXT,
        time_created TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS parts (
        id TEXT PRIMARY KEY,
        message_id TEXT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
        type TEXT NOT NULL CHECK(type IN ('text','reasoning','tool_input','tool_output','tool_error')),
        content TEXT NOT NULL,
        metadata TEXT NOT NULL DEFAULT '{}'
    );
    """,
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS conversation_fts USING fts5(
        part_id UNINDEXED,
        message_id UNINDEXED,
        session_id UNINDEXED,
        content,
        tokenize='trigram'
    );
    """,
    """
    CREATE TRIGGER IF NOT EXISTS conversation_fts_ins AFTER INSERT ON parts BEGIN
        INSERT INTO conversation_fts(rowid, part_id, message_id, session_id, content)
        VALUES (new.rowid, new.id, new.message_id,
                (SELECT session_id FROM messages WHERE id = new.message_id),
                new.content);
    END;
    CREATE TRIGGER IF NOT EXISTS conversation_fts_upd AFTER UPDATE ON parts BEGIN
        INSERT INTO conversation_fts(conversation_fts, rowid, part_id, message_id, session_id, content)
        VALUES ('delete', old.rowid, old.id, old.message_id,
                (SELECT session_id FROM messages WHERE id = old.message_id),
                old.content);
        INSERT INTO conversation_fts(rowid, part_id, message_id, session_id, content)
        VALUES (new.rowid, new.id, new.message_id,
                (SELECT session_id FROM messages WHERE id = new.message_id),
                new.content);
    END;
    CREATE TRIGGER IF NOT EXISTS conversation_fts_del AFTER DELETE ON parts BEGIN
        INSERT INTO conversation_fts(conversation_fts, rowid, part_id, message_id, session_id, content)
        VALUES ('delete', old.rowid, old.id, old.message_id,
                (SELECT session_id FROM messages WHERE id = old.message_id),
                old.content);
    END;
    """,
    """
    CREATE TABLE IF NOT EXISTS condensations (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
        start_time TEXT NOT NULL,
        end_time TEXT NOT NULL,
        message_count INTEGER NOT NULL,
        summary TEXT NOT NULL,
        impression_id TEXT,
        created_at TEXT NOT NULL
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_cond_session ON condensations(session_id);
    """,
    """
    CREATE TABLE IF NOT EXISTS message_entities (
        part_id TEXT NOT NULL REFERENCES parts(id) ON DELETE CASCADE,
        entity_id TEXT NOT NULL,
        relevance REAL NOT NULL DEFAULT 0.0,
        PRIMARY KEY(part_id, entity_id)
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_msg_session ON messages(session_id);
    CREATE INDEX IF NOT EXISTS idx_msg_agent ON messages(agent_id);
    CREATE INDEX IF NOT EXISTS idx_part_message ON parts(message_id);
    CREATE INDEX IF NOT EXISTS idx_part_type ON parts(type);
    CREATE INDEX IF NOT EXISTS idx_msg_ent_entity ON message_entities(entity_id);
    """,
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

        # 兼容性迁移：旧表无 decay/hits 列时添加（无论表是新创建还是已存在都尝试）
        for tbl in ("patterns", "principles"):
            cols = [
                r[1] for r in self._conn.execute(
                    f"PRAGMA table_info({tbl})"
                ).fetchall()
            ]
            if "decay" not in cols:
                self._conn.execute(f"ALTER TABLE {tbl} ADD COLUMN decay REAL NOT NULL DEFAULT 1.0")
            if "hits" not in cols:
                self._conn.execute(f"ALTER TABLE {tbl} ADD COLUMN hits INTEGER NOT NULL DEFAULT 0")

        # 兼容性迁移：sessions 表加 condensed_up_to 列 + condensations 表
        session_cols = [
            r[1] for r in self._conn.execute("PRAGMA table_info(sessions)").fetchall()
        ]
        if "condensed_up_to" not in session_cols:
            self._conn.execute("ALTER TABLE sessions ADD COLUMN condensed_up_to TEXT")
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS condensations (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                message_count INTEGER NOT NULL,
                summary TEXT NOT NULL,
                impression_id TEXT,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_cond_session ON condensations(session_id);
        """)
        self._conn.commit()

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
        """将一条记忆写入对应层次（自动时序标注 + 旧状态失效）"""
        # 时序标注
        from mnemos.temporal import Chronos
        chronos = Chronos()
        chronos.annotate(entry)

        # 状态互斥：关闭同 state_key 的旧状态
        if entry.memory_type.value == "state" and entry.state_key:
            old_states = self._find_active_states(entry.scope_id, entry.state_key)
            if old_states:
                deactivated = chronos.deactivate_states(old_states, entry)
                for eid in deactivated:
                    self._set_inactive(eid)

        now = _now()
        row = _serialize_impression(entry, now)

        if entry.tier == MemoryTier.IMPRESSION:
            self.db.execute(
                """INSERT INTO impressions
                   (entry_id, title, content, scope_type, scope_id,
                    tags_json, parent_id, related_json,
                    anchors_json, entities_json, beliefs_json,
                    embedding_model, decay, hits, created_at, touched_at,
                    memory_type, state_key, event_start, event_end,
                    is_active, temporal_precision)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,
                           ?,?,?,?,?,?)""",
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
                    source_json, confidence, decay, hits,
                    created_at, touched_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                _serialize_pattern(entry, now),
            )
            self._index_entities(entry.entry_id, "pattern", entry.entities)

        elif entry.tier == MemoryTier.PRINCIPLE:
            self.db.execute(
                """INSERT INTO principles
                   (entry_id, title, content, scope_type, scope_id,
                    tags_json, entities_json, source_json,
                    confidence, decay, hits, created_at, touched_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
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
                   "entities_json", "beliefs_json", "confidence", "hits"}
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

    @staticmethod
    def _sanitize_fts5(query: str) -> str:
        """清理 FTS5 特殊字符，避免语法错误。"""
        # FTS5 保留字符: * ( ) [ ] - + " 以及 AND OR NOT NEAR
        # 策略：移除所有 FTS5 语法字符，保留纯文本
        special = set('*()[]-+"%')
        cleaned = "".join(c for c in query if c not in special)
        # 去掉可能残留的 AND/OR/NOT 大写词（简单处理：拆词重拼）
        tokens = cleaned.split()
        safe = [t for t in tokens if t.upper() not in ("AND", "OR", "NOT", "NEAR")]
        return " ".join(safe) if safe else cleaned.strip() or "*"

    def fts(self, query: str, limit: int = 20) -> list[MemoryEntry]:
        """全文搜索。FTS5 先尝试；中文回退 LIKE。"""
        safe_query = self._sanitize_fts5(query)
        rows = self.db.execute(
            """SELECT i.* FROM impressions i
               JOIN impression_fts f ON i.rowid = f.rowid
               WHERE impression_fts MATCH ?
               ORDER BY rank LIMIT ?""",
            (safe_query, limit),
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
        """按归属范围召回，按 decay × resonance 混合排序（活跃优先）"""
        if tiers is None:
            tiers = list(MemoryTier)
        results: list[MemoryEntry] = []
        for tier in tiers:
            rows = self.db.execute(
                f"SELECT * FROM {_table(tier)} "
                "WHERE scope_type=? AND scope_id=? "
                "ORDER BY decay DESC, touched_at DESC LIMIT ?",
                (scope_type.value, scope_id, limit),
            ).fetchall()
            results.extend(_deserialize(dict(r), tier) for r in rows)
        # decay 排序：未衰减的记忆（高频使用）优先
        results.sort(key=lambda e: (e.decay_factor, e.last_accessed_at), reverse=True)
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

    def by_decay(
        self, min_decay: float = 0.0, max_decay: float = 0.3,
        limit: int = 50
    ) -> list[MemoryEntry]:
        """按衰减程度召回（定位即将被遗忘的记忆）"""
        results: list[MemoryEntry] = []
        for table, tier in [
            ("impressions", MemoryTier.IMPRESSION),
            ("patterns", MemoryTier.PATTERN),
            ("principles", MemoryTier.PRINCIPLE),
        ]:
            rows = self.db.execute(
                f"SELECT * FROM {table} WHERE decay >= ? AND decay <= ? "
                "ORDER BY decay ASC, touched_at DESC LIMIT ?",
                (min_decay, max_decay, limit),
            ).fetchall()
            results.extend(_deserialize(dict(r), tier) for r in rows)
        return results[:limit]

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

    def touch(self, entry_id: str, tier: MemoryTier) -> None:
        """标记为被访问，刷新衰减 + 增加访问计数"""
        now = _now()
        table = _table(tier)
        self.db.execute(
            f"UPDATE {table} SET hits = hits + 1, "
            f"decay = MIN(1.0, decay + 0.05), "
            f"touched_at = ? WHERE entry_id = ?",
            (now, entry_id),
        )
        self.db.commit()

    def decay_stale(self, rate: float = 0.01) -> int:
        """对长期未访问的记忆施加衰减（全三层）"""
        now = _now()
        total = 0
        for table in ("impressions", "patterns", "principles"):
            c = self.db.execute(
                f"UPDATE {table} SET decay = MAX(0.0, decay - ?) WHERE touched_at < ?",
                (rate, now),
            )
            total += c.rowcount
        self.db.commit()
        return total

    def purge_dead(self, before: datetime) -> int:
        """清除衰减归零的旧记忆（全三层）"""
        cutoff = before.isoformat()
        total = 0
        for table in ("impressions", "patterns", "principles"):
            c = self.db.execute(
                f"DELETE FROM {table} WHERE decay <= 0 AND created_at < ?",
                (cutoff,),
            )
            total += c.rowcount
        self.db.commit()
        return total

    # ── 会话历史 (MiMo 融合) ──────────────────────────────

    def create_session(self, project_id: str, metadata: dict | None = None) -> str:
        """创建新会话，返回 session_id"""
        import uuid
        session_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        meta = json.dumps(metadata or {})
        self.db.execute(
            """INSERT INTO sessions (id, project_id, created_at, last_message_id, metadata)
               VALUES (?, ?, ?, ?, ?)""",
            (session_id, project_id, now, None, meta)
        )
        self.db.commit()
        return session_id

    def get_session(self, session_id: str) -> dict | None:
        row = self.db.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
        return dict(row) if row else None

    def list_sessions(self, project_id: str | None = None, limit: int = 50) -> list[dict]:
        if project_id:
            rows = self.db.execute(
                "SELECT * FROM sessions WHERE project_id=? ORDER BY created_at DESC LIMIT ?",
                (project_id, limit)
            ).fetchall()
        else:
            rows = self.db.execute(
                "SELECT * FROM sessions ORDER BY created_at DESC LIMIT ?",
                (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def append_message(self, session_id: str, role: str, agent_id: str,
                       parts: list[dict], tokens: int = 0, finish_reason: str | None = None) -> str:
        """向会话追加消息（原子：插入消息+parts+更新会话last）"""
        import uuid
        message_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        # Insert message
        self.db.execute(
            """INSERT INTO messages (id, session_id, role, agent_id, tokens, finish_reason, time_created)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (message_id, session_id, role, agent_id, tokens, finish_reason, now)
        )
        # Insert parts
        for part in parts:
            part_id = str(uuid.uuid4())
            self.db.execute(
                """INSERT INTO parts (id, message_id, type, content, metadata)
                   VALUES (?, ?, ?, ?, ?)""",
                (part_id, message_id, part['type'], part['content'], json.dumps(part.get('metadata', {})))
            )
        # Update session's last_message_id
        self.db.execute(
            "UPDATE sessions SET last_message_id=? WHERE id=?", (message_id, session_id)
        )
        self.db.commit()
        return message_id

    def get_message(self, message_id: str) -> dict | None:
        row = self.db.execute("SELECT * FROM messages WHERE id=?", (message_id,)).fetchone()
        if not row:
            return None
        msg = dict(row)
        parts = self.db.execute("SELECT * FROM parts WHERE message_id=?", (message_id,)).fetchall()
        msg['parts'] = [dict(p) for p in parts]
        return msg

    def list_messages(self, session_id: str, limit: int = 100, offset: int = 0) -> list[dict]:
        rows = self.db.execute(
            """SELECT * FROM messages
               WHERE session_id=?
               ORDER BY time_created ASC
               LIMIT ? OFFSET ?""",
            (session_id, limit, offset)
        ).fetchall()
        result = []
        for r in rows:
            msg = dict(r)
            parts = self.db.execute("SELECT * FROM parts WHERE message_id=?", (msg['id'],)).fetchall()
            msg['parts'] = [dict(p) for p in parts]
            result.append(msg)
        return result

    def conversation_search(self, query: str, session_id: str | None = None,
                           scope: str = 'project', project_id: str | None = None,
                           kind: str | None = None, tool_name: str | None = None,
                           time_after: str | None = None, time_before: str | None = None,
                           limit: int = 50) -> list[dict]:
        """FTS5 搜索对话片段，返回 BM25 评分 + 高亮"""
        safe_query = self._sanitize_fts5(query) if hasattr(self, '_sanitize_fts5') else query
        params = []
        where = ["conversation_fts MATCH ?"]
        params.append(safe_query)

        if session_id:
            where.append("f.session_id = ?")
            params.append(session_id)
        elif scope == 'project' and project_id:
            where.append("f.session_id IN (SELECT id FROM sessions WHERE project_id = ?)")
            params.append(project_id)

        sql = """
            SELECT
                f.part_id,
                f.message_id,
                f.session_id,
                p.type AS kind,
                m.agent_id,
                snippet(conversation_fts, 3, '<<', '>>', '...', 32) AS snippet,
                bm25(conversation_fts) AS score,
                m.time_created
            FROM conversation_fts f
            JOIN parts p ON f.part_id = p.id
            JOIN messages m ON f.message_id = m.id
            WHERE """ + " AND ".join(where) + """
            ORDER BY score
            LIMIT ?
        """
        params.append(limit)
        rows = self.db.execute(sql, params).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d['score'] = -d['score']  # 正向分数
            results.append(d)
        return results

    def around_message(self, message_id: str, before: int = 5, after: int = 5) -> list[dict]:
        """获取消息的前后上下文（包含完整消息）"""
        msg = self.db.execute(
            "SELECT session_id, time_created FROM messages WHERE id=?", (message_id,)
        ).fetchone()
        if not msg:
            return []
        session_id = msg['session_id']
        target_time = msg['time_created']

        before_rows = self.db.execute(
            """SELECT * FROM messages
               WHERE session_id=? AND time_created < ?
               ORDER BY time_created DESC LIMIT ?""",
            (session_id, target_time, before)
        ).fetchall()
        after_rows = self.db.execute(
            """SELECT * FROM messages
               WHERE session_id=? AND time_created > ?
               ORDER BY time_created ASC LIMIT ?""",
            (session_id, target_time, after)
        ).fetchall()
        # 组合：前段反序 + 当前 + 后段
        all_msgs = list(reversed([dict(r) for r in before_rows])) + [dict(self.db.execute("SELECT * FROM messages WHERE id=?", (message_id,)).fetchone())] + [dict(r) for r in after_rows]
        # 加载每个消息的 parts
        for m in all_msgs:
            parts = self.db.execute("SELECT * FROM parts WHERE message_id=?", (m['id'],)).fetchall()
            m['parts'] = [dict(p) for p in parts]
        return all_msgs

    def link_message_entities(self, part_id: str, entity_id: str, relevance: float = 0.0) -> None:
        """关联 part 与实体（用于后续图谱检索）"""
        self.db.execute(
            """INSERT OR REPLACE INTO message_entities (part_id, entity_id, relevance)
               VALUES (?, ?, ?)""",
            (part_id, entity_id, relevance)
        )
        self.db.commit()

    def get_entity_mentions(self, entity_id: str, limit: int = 50) -> list[dict]:
        """查询实体出现的片段（含消息上下文）"""
        rows = self.db.execute(
            """SELECT p.id as part_id, p.message_id, p.content, m.session_id
               FROM message_entities me
               JOIN parts p ON me.part_id = p.id
               JOIN messages m ON p.message_id = m.id
               WHERE me.entity_id = ?
               ORDER BY me.relevance DESC
               LIMIT ?""",
            (entity_id, limit)
        ).fetchall()
        return [dict(r) for r in rows]

    # ── 自动凝练（无限上下文核心）──────────────────────────

    def get_uncompacted_messages(self, session_id: str, threshold: int = 20) -> list[dict]:
        """获取未凝练的消息（超过 threshold 条的旧消息需要凝练）

        返回需要凝练的最旧消息列表。用凝练记录中的 message_count 累计跳过，
        避免时间戳精度问题。
        """
        session = self.db.execute(
            "SELECT condensed_up_to FROM sessions WHERE id=?", (session_id,)
        ).fetchone()
        if not session:
            return []

        # 获取所有消息（按时间 ASC + ID ASC 保证稳定排序）
        all_rows = self.db.execute(
            """SELECT * FROM messages
               WHERE session_id=? ORDER BY time_created ASC, id ASC""",
            (session_id,)
        ).fetchall()

        total = len(all_rows)
        if total <= threshold:
            return []

        # 计算已凝练的消息总数
        condensed_count_row = self.db.execute(
            "SELECT COALESCE(SUM(message_count), 0) as c FROM condensations WHERE session_id=?",
            (session_id,)
        ).fetchone()
        condensed_count = condensed_count_row['c']

        # 跳过已凝练的消息，取剩余的
        unprocessed = all_rows[condensed_count:]

        # 需要凝练的消息数 = 未处理总数 - threshold
        to_condense_count = len(unprocessed) - threshold
        if to_condense_count <= 0:
            return []

        messages = []
        for r in unprocessed[:to_condense_count]:
            msg = dict(r)
            parts = self.db.execute(
                "SELECT * FROM parts WHERE message_id=?", (msg['id'],)
            ).fetchall()
            msg['parts'] = [dict(p) for p in parts]
            messages.append(msg)
        return messages

    def auto_condense(self, session_id: str, llm_fn, threshold: int = 20) -> dict | None:
        """
        自动凝练：对话满 threshold 轮 → LLM 摘要 → 写入永久记忆。

        Args:
            session_id: 会话 ID
            llm_fn: 回调函数 llm_fn(prompt: str) -> str，接收摘要请求，返回摘要文本
            threshold: 保留最近 N 条消息不凝练

        Returns:
            凝练记录 dict，或 None（未达到阈值）
        """
        messages = self.get_uncompacted_messages(session_id, threshold)
        if not messages:
            return None

        # 构造摘要请求
        conversation_text = []
        for msg in messages:
            role = msg['role']
            parts_text = []
            for p in msg.get('parts', []):
                parts_text.append(p['content'])
            content = '\n'.join(parts_text)
            if content.strip():
                conversation_text.append(f"[{role}]: {content}")

        if not conversation_text:
            return None

        prompt = (
            "请将以下对话压缩为简洁摘要，保留关键事实、决策、用户偏好和重要上下文。"
            "不要遗漏任何对后续对话有价值的信息。\n\n"
            f"对话内容（{len(messages)} 条消息）：\n"
            + '\n'.join(conversation_text)
        )

        # 调用 LLM 生成摘要
        try:
            summary = llm_fn(prompt)
        except Exception:
            # LLM 调用失败时降级：用前 3 条消息的首行拼接
            summary = "（LLM 摘要失败，降级为截断）\n"
            for msg in messages[:3]:
                for p in msg.get('parts', []):
                    if p['type'] == 'text':
                        summary += p['content'][:200] + "\n"
                        break

        # 写入永久记忆（impression）
        impression_id = uuid.uuid4().hex[:16]
        now = datetime.now(timezone.utc).isoformat()

        entry = MemoryEntry(
            entry_id=impression_id,
            tier=MemoryTier.IMPRESSION,
            content=summary,
            title=f"会话凝练: {session_id[:8]}",
            scope=ScopeType.TENANT,
            tags=["condensation", "auto", f"session:{session_id}"],
            entities=[],
        )
        self.inscribe(entry)

        # 记录凝练记录
        condensation_id = str(uuid.uuid4())
        start_time = messages[0]['time_created']
        end_time = messages[-1]['time_created']

        self.db.execute(
            """INSERT INTO condensations (id, session_id, start_time, end_time,
               message_count, summary, impression_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (condensation_id, session_id, start_time, end_time,
             len(messages), summary, impression_id, now)
        )

        # 更新 session 的凝练截止时间
        self.db.execute(
            "UPDATE sessions SET condensed_up_to=? WHERE id=?",
            (end_time, session_id)
        )
        self.db.commit()

        return {
            'id': condensation_id,
            'session_id': session_id,
            'message_count': len(messages),
            'impression_id': impression_id,
            'summary_preview': summary[:200],
        }

    def get_condensed_history(self, session_id: str) -> list[dict]:
        """获取会话的所有凝练记录"""
        rows = self.db.execute(
            """SELECT * FROM condensations
               WHERE session_id=? ORDER BY start_time ASC""",
            (session_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_full_context(self, session_id: str, recent_n: int = 20,
                         search_query: str | None = None, search_limit: int = 10) -> dict:
        """
        获取完整上下文 = 凝练摘要 + 最近 N 条原始消息 + FTS5 相关片段。
        这就是"无限上下文"的查询入口。
        """
        # 1. 凝练摘要
        condensations = self.get_condensed_history(session_id)

        # 2. 最近 N 条消息（原始）
        recent = self.db.execute(
            """SELECT * FROM messages
               WHERE session_id=?
               ORDER BY time_created DESC LIMIT ?""",
            (session_id, recent_n)
        ).fetchall()
        recent_msgs = []
        for r in reversed(recent):
            msg = dict(r)
            parts = self.db.execute(
                "SELECT * FROM parts WHERE message_id=?", (msg['id'],)
            ).fetchall()
            msg['parts'] = [dict(p) for p in parts]
            recent_msgs.append(msg)

        # 3. FTS5 相关片段（如果有查询）
        related = []
        if search_query:
            related = self.conversation_search(
                search_query, session_id=session_id, limit=search_limit
            )

        return {
            'condensations': condensations,
            'recent_messages': recent_msgs,
            'related_snippets': related,
        }

    # ── 嵌入向量持久化 ──────────────────────────────

    @staticmethod
    def _serialize_vector(vec: np.ndarray) -> bytes:
        """numpy array → bytes (float32 little-endian)"""
        return vec.astype(np.float32).tobytes()

    @staticmethod
    def _deserialize_vector(data: bytes, dim: int) -> np.ndarray:
        """bytes → numpy array"""
        return np.frombuffer(data, dtype=np.float32).reshape(-1) if dim else np.array([], dtype=np.float32)

    def save_embedding(self, entry_id: str, model: str, vector: np.ndarray) -> None:
        """将嵌入向量持久化到 SQLite"""
        dim = int(vector.size)
        blob = self._serialize_vector(vector)
        now = _now()
        self.db.execute(
            "INSERT OR REPLACE INTO embeddings "
            "(entry_id, model, vector, dim, dtype, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (entry_id, model, blob, dim, "float32", now),
        )
        self.db.commit()

    def load_embedding(self, entry_id: str) -> np.ndarray | None:
        """从持久化存储中加载单条嵌入向量"""
        row = self.db.execute(
            "SELECT vector, dim FROM embeddings WHERE entry_id=?",
            (entry_id,),
        ).fetchone()
        if row is None:
            return None
        return self._deserialize_vector(row["vector"], row["dim"])

    def load_embeddings_batch(self, entry_ids: list[str]) -> dict[str, np.ndarray]:
        """批量加载嵌入向量，返回 {entry_id: vector}"""
        if not entry_ids:
            return {}
        # SQLite 参数限制 999，分批查询
        result: dict[str, np.ndarray] = {}
        batch_size = 500
        for i in range(0, len(entry_ids), batch_size):
            chunk = entry_ids[i : i + batch_size]
            placeholders = ",".join("?" * len(chunk))
            rows = self.db.execute(
                f"SELECT entry_id, vector, dim FROM embeddings "
                f"WHERE entry_id IN ({placeholders})",
                chunk,
            ).fetchall()
            for row in rows:
                result[row["entry_id"]] = self._deserialize_vector(
                    row["vector"], row["dim"]
                )
        return result

    def delete_embedding(self, entry_id: str) -> None:
        """删除一条嵌入向量"""
        self.db.execute(
            "DELETE FROM embeddings WHERE entry_id=?", (entry_id,)
        )
        self.db.commit()

    def delete_embeddings_batch(self, entry_ids: list[str]) -> None:
        """批量删除嵌入向量"""
        if not entry_ids:
            return
        batch_size = 500
        for i in range(0, len(entry_ids), batch_size):
            chunk = entry_ids[i : i + batch_size]
            placeholders = ",".join("?" * len(chunk))
            self.db.execute(
                f"DELETE FROM embeddings WHERE entry_id IN ({placeholders})",
                chunk,
            )
        self.db.commit()

    def embedding_stats(self) -> dict[str, Any]:
        """返回嵌入向量统计信息"""
        row = self.db.execute(
            "SELECT COUNT(*) as count, model, AVG(dim) as avg_dim "
            "FROM embeddings GROUP BY model"
        ).fetchall()
        if not row:
            return {"count": 0, "models": []}
        return {
            "count": sum(r["count"] for r in row),
            "models": [
                {"model": r["model"], "count": r["count"], "avg_dim": r["avg_dim"]}
                for r in row
            ],
        }

    def count(self) -> dict[str, int]:
        """返回各层计数"""
        emb_row = self.db.execute(
            "SELECT COUNT(*) FROM embeddings"
        ).fetchone()
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
            "embeddings": emb_row[0] if emb_row else 0,
        }

    def all(self, limit: int = 1000) -> list[MemoryEntry]:
        """返回所有印象层记忆（用于嵌入召回池）"""
        rows = self.db.execute(
            "SELECT * FROM impressions ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [_deserialize(dict(r), MemoryTier.IMPRESSION) for r in rows]

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

    def _find_active_states(self, scope_id: str, state_key: str) -> list[MemoryEntry]:
        """查找同 scope + state_key 的活跃状态记忆"""
        rows = self.db.execute(
            "SELECT * FROM impressions WHERE scope_id=? AND state_key=? AND is_active=1",
            (scope_id, state_key),
        ).fetchall()
        return [_deserialize(dict(r), MemoryTier.IMPRESSION) for r in rows]

    def _set_inactive(self, entry_id: str) -> None:
        """将一条记忆标记为已失效"""
        now = _now()
        self.db.execute(
            "UPDATE impressions SET is_active=0, event_end=?, touched_at=? WHERE entry_id=?",
            (now, now, entry_id),
        )

    # ── 实体关系边操作 ──────────────────────────────────────

    def link_entities_together(
        self,
        entity_a_id: str,
        entity_b_id: str,
        relation: str = "related",
        weight: float = 1.0,
        metadata_json: str = "{}",
    ) -> None:
        """创建或增强两个实体之间的显式关系边"""
        a, b = sorted([entity_a_id, entity_b_id])
        now = _now()
        self.db.execute(
            """INSERT INTO entity_edges
               (from_id, to_id, relation, weight, metadata, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(from_id, to_id, relation) DO UPDATE SET
               weight = weight + excluded.weight,
               updated_at = excluded.updated_at,
               metadata = CASE
                   WHEN excluded.metadata != '{}' THEN excluded.metadata
                   ELSE entity_edges.metadata
               END""",
            (a, b, relation, weight, metadata_json, now, now),
        )
        self.db.commit()

    def get_entity_edges(self, entity_id: str) -> list[dict[str, Any]]:
        """获取与某个实体相连的所有显式关系边"""
        rows = self.db.execute(
            """SELECT from_id, to_id, relation, weight, metadata,
                      created_at, updated_at
               FROM entity_edges
               WHERE from_id=? OR to_id=?
               ORDER BY weight DESC""",
            (entity_id, entity_id),
        ).fetchall()
        return [
            {
                "source": r["from_id"],
                "target": r["to_id"],
                "relation": r["relation"],
                "weight": r["weight"],
                "metadata": json.loads(r["metadata"]) if r["metadata"] else {},
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
            }
            for r in rows
        ]

    def update_edge_weight(
        self,
        from_id: str,
        to_id: str,
        delta: float,
    ) -> None:
        """增减边权重（正数增强，负数削弱，不低于0）"""
        a, b = sorted([from_id, to_id])
        now = _now()
        self.db.execute(
            """UPDATE entity_edges
               SET weight = MAX(0.0, weight + ?), updated_at = ?
               WHERE from_id=? AND to_id=?""",
            (delta, now, a, b),
        )
        self.db.commit()


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
        entry.memory_type.value,
        entry.state_key,
        entry.event_start.isoformat() if entry.event_start else None,
        entry.event_end.isoformat() if entry.event_end else None,
        1 if entry.is_active else 0,
        entry.temporal_precision,
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
        entry.decay_factor,
        entry.access_count,
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
        entry.decay_factor,
        entry.access_count,
        entry.created_at.isoformat(),
        now,
    )


def _deserialize(row: dict, tier: MemoryTier) -> MemoryEntry:
    """数据库行 → MemoryEntry"""
    from mnemos.core.models import MemoryType

    created = datetime.fromisoformat(row["created_at"])
    touched = datetime.fromisoformat(row.get("touched_at", row["created_at"]))
    # 统一补 UTC 时区 — 避免 naive vs aware 比较
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    if touched.tzinfo is None:
        touched = touched.replace(tzinfo=timezone.utc)

    # memory_type 防御：旧数据可能有 "self" 等非法值，fallback 到 timeless
    raw_mt = row.get("memory_type", "timeless")
    try:
        memory_type = MemoryType(raw_mt)
    except ValueError:
        memory_type = MemoryType.TIMELESS
    event_start = None
    event_end = None
    if row.get("event_start"):
        event_start = datetime.fromisoformat(row["event_start"])
    if row.get("event_end"):
        event_end = datetime.fromisoformat(row["event_end"])

    entry = MemoryEntry(
        entry_id=row["entry_id"],
        tier=tier,
        title=row.get("title", ""),
        content=row.get("content", ""),
        scope=ScopeType(row.get("scope_type", "tenant")),
        scope_id=row.get("scope_id", ""),
        tags=_from_json(row.get("tags_json", "[]")),
        entities=[EntityRef(**e) if isinstance(e, dict) else EntityRef(label=str(e)) for e in _from_json(row.get("entities_json", "[]"))],
        beliefs=[BeliefRecord(**b) for b in _from_json(row.get("beliefs_json", "[]"))],
        related_ids=_from_json(row.get("related_json", row.get("source_json", "[]"))),
        parent_id=row.get("parent_id"),
        created_at=created,
        last_accessed_at=touched,
        access_count=row.get("hits", row.get("access_count", 0)),
        decay_factor=row.get("decay", 1.0),
        memory_type=memory_type,
        state_key=row.get("state_key", ""),
        event_start=event_start,
        event_end=event_end,
        is_active=bool(row.get("is_active", 1)),
        temporal_precision=row.get("temporal_precision", "day"),
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
