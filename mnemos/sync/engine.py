"""
同步引擎 — 多进程 SQLite WAL 模式下的记忆同步

设计哲学:
  记忆如河流，从源头流向远方，沿途留下痕迹。
  同步不是复制，而是让不同河段的记忆交汇。
  冲突不可避免，但可以通过策略（末位写入优先）自动化解。

核心能力:
  - push: 将本地变更推送到远程
  - pull: 从远程拉取变更到本地
  - merge: 双向合并（两步：先 pull 再 resolve）
  - resolve: 冲突消解（末位写入优先 / 手动覆盖）

冲突检测:
  同一 memory_id 在两端都被 update/delete 时产生冲突。
  策略:
    lww  — Last-Writer-Wins（比较 created_at 时间戳）
    keep_local  — 保留本地版本
    keep_remote — 保留远程版本
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mnemos.storage.palimpsest import PalimpsestStore, _now


# ── 辅助 ─────────────────────────────────────────────────


def _gen_id(prefix: str = "sync") -> str:
    """生成唯一 ID"""
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _parse_vector_clock(vc_json: str) -> dict[str, int]:
    """解析向量时钟 JSON"""
    try:
        return json.loads(vc_json) if vc_json else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _vector_clock_increment(
    vc: dict[str, int], node_id: str
) -> dict[str, int]:
    """递增指定节点的向量时钟"""
    vc = dict(vc)
    vc[node_id] = vc.get(node_id, 0) + 1
    return vc


def _vector_clock_merge(
    a: dict[str, int], b: dict[str, int]
) -> dict[str, int]:
    """合并两个向量时钟（取各节点最大值）"""
    merged = dict(a)
    for node, ts in b.items():
        merged[node] = max(merged.get(node, 0), ts)
    return merged


def _vector_clock_compare(
    a: dict[str, int], b: dict[str, int]
) -> str:
    """
    比较两个向量时钟。
    返回: 'a领先', 'b领先', 'concurrent', 'equal'
    """
    a_gt_b = False
    b_gt_a = False
    all_nodes = set(a.keys()) | set(b.keys())
    for node in all_nodes:
        va = a.get(node, 0)
        vb = b.get(node, 0)
        if va > vb:
            a_gt_b = True
        elif vb > va:
            b_gt_a = True
    if a_gt_b and not b_gt_a:
        return "a领先"
    if b_gt_a and not a_gt_b:
        return "b领先"
    if a_gt_b and b_gt_a:
        return "concurrent"
    return "equal"


# ── 同步引擎 ─────────────────────────────────────────────


class SyncEngine:
    """
    记忆同步引擎。

    使用示例:
        store = PalimpsestStore("local.db")
        store.connect()
        engine = SyncEngine(store, node_id="laptop")
        engine.push()
        engine.pull("/remote/backup.db")
        engine.merge("/remote/backup.db")
        engine.status()
    """

    # 同步状态常量
    STATUS_PENDING = "pending"
    STATUS_INFLIGHT = "inflight"
    STATUS_CONFLICT = "conflict"
    STATUS_DONE = "done"

    # 操作类型常量
    OP_CREATE = "create"
    OP_UPDATE = "update"
    OP_DELETE = "delete"

    # 同步策略常量
    STRATEGY_LWW = "lww"
    STRATEGY_KEEP_LOCAL = "keep_local"
    STRATEGY_KEEP_REMOTE = "keep_remote"

    # 需要同步的表
    SYNC_TABLES = ("impressions", "patterns", "principles")

    def __init__(
        self,
        store: PalimpsestStore,
        node_id: str | None = None,
    ):
        """
        初始化同步引擎。

        Args:
            store: 本地 PalimpsestStore 实例
            node_id: 本节点标识符，用于向量时钟区分来源
        """
        self._store = store
        self._node_id = node_id or f"node_{uuid.uuid4().hex[:8]}"

    @property
    def node_id(self) -> str:
        return self._node_id

    # ── 日志操作 ──────────────────────────────────────────

    def _log_change(
        self,
        memory_id: str,
        operation: str,
        tier: str,
        payload: dict[str, Any] | None = None,
        entity_id: str = "",
        status: str = STATUS_PENDING,
    ) -> str:
        """向 sync_log 写入一条变更记录"""
        sync_id = _gen_id("change")
        now = _now()
        vc = _vector_clock_increment({}, self._node_id)
        self._store.db.execute(
            """INSERT INTO sync_log
               (sync_id, memory_id, entity_id, operation, tier,
                payload, node_id, vector_clock,
                created_at, synced_at, sync_status)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                sync_id,
                memory_id,
                entity_id,
                operation,
                tier,
                json.dumps(payload or {}, ensure_ascii=False),
                self._node_id,
                json.dumps(vc),
                now,
                None,
                status,
            ),
        )
        self._store.db.commit()
        return sync_id

    def _update_sync_status(
        self,
        sync_id: str,
        status: str,
        synced_at: str | None = None,
    ) -> None:
        """更新同步记录状态"""
        self._store.db.execute(
            "UPDATE sync_log SET sync_status=?, synced_at=? WHERE sync_id=?",
            (status, synced_at or _now(), sync_id),
        )
        self._store.db.commit()

    def _pending_changes(
        self,
        scope_type: str | None = None,
        scope_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """获取所有待同步的变更"""
        query = "SELECT * FROM sync_log WHERE sync_status=?"
        params: list[Any] = [self.STATUS_PENDING]

        if scope_type and scope_id:
            # 需要通过 tier 表查询 scope
            placeholders = ",".join("?" * len(self.SYNC_TABLES))
            query += (
                f" AND memory_id IN ("
                f"  SELECT entry_id FROM ({' UNION '.join([f'SELECT entry_id, scope_type, scope_id FROM {t}' for t in self.SYNC_TABLES])})"
                f")"
            )
            # 简化：通过 tier 表查询
            scope_filter = " OR ".join(
                [f"(tier=? AND memory_id IN (SELECT entry_id FROM {t} WHERE scope_type=? AND scope_id=?))" for t in self.SYNC_TABLES]
            )
            # 重写查询
            subqueries = " UNION ".join(
                [f"SELECT entry_id FROM {t} WHERE scope_type=? AND scope_id=?" for t in self.SYNC_TABLES]
            )
            query = f"SELECT * FROM sync_log WHERE sync_status=? AND memory_id IN ({subqueries})"
            params = [self.STATUS_PENDING] + [scope_type, scope_id] * len(self.SYNC_TABLES)

        query += " ORDER BY created_at ASC"
        rows = self._store.db.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def _apply_remote_change(
        self,
        change: dict[str, Any],
    ) -> str:
        """
        将远程变更应用到本地。

        Returns:
            'applied' | 'conflict' | 'skipped'
        """
        memory_id = change["memory_id"]
        operation = change["operation"]
        tier = change["tier"]
        payload = json.loads(change["payload"]) if change["payload"] else {}
        remote_node = change["node_id"]
        remote_vc = _parse_vector_clock(change.get("vector_clock", "{}"))

        # 检查本地是否也有未同步的变更
        local_pending = self._store.db.execute(
            """SELECT * FROM sync_log
               WHERE memory_id=? AND node_id=? AND sync_status IN (?,?)""",
            (memory_id, self._node_id, self.STATUS_PENDING, self.STATUS_INFLIGHT),
        ).fetchone()

        if local_pending:
            # 本地也有未同步变更 → 冲突
            local_vc = _parse_vector_clock(local_pending["vector_clock"])
            comparison = _vector_clock_compare(local_vc, remote_vc)
            if comparison == "concurrent":
                self._log_change(
                    memory_id,
                    operation,
                    tier,
                    payload,
                    change.get("entity_id", ""),
                    status=self.STATUS_CONFLICT,
                )
                self._update_sync_status(
                    change["sync_id"], self.STATUS_CONFLICT
                )
                return "conflict"

        # 检查远程时间戳是否比本地最新更新
        local_entry = self._store.by_id(memory_id)
        if local_entry:
            local_touched = local_entry.last_accessed_at.isoformat()
            if change["created_at"] <= local_touched:
                # 本地更新，跳过
                self._update_sync_status(
                    change["sync_id"], self.STATUS_DONE, _now()
                )
                return "skipped"

        # 应用变更
        try:
            if operation == self.OP_CREATE:
                self._apply_create(memory_id, tier, payload)
            elif operation == self.OP_UPDATE:
                self._apply_update(memory_id, tier, payload)
            elif operation == self.OP_DELETE:
                self._apply_delete(memory_id, tier)

            self._update_sync_status(
                change["sync_id"], self.STATUS_DONE, _now()
            )
            return "applied"
        except Exception:
            self._update_sync_status(
                change["sync_id"], self.STATUS_CONFLICT, _now()
            )
            return "conflict"

    def _apply_create(
        self, memory_id: str, tier: str, payload: dict[str, Any]
    ) -> None:
        """应用创建操作"""
        from mnemos.core.models import (
            BeliefRecord,
            ConfidenceLevel,
            EntityRef,
            MemoryEntry,
            MemoryTier,
            ScopeType,
        )

        tier_enum = MemoryTier(tier)
        now = _now()

        # 从 payload 构建 MemoryEntry
        entry = MemoryEntry(
            entry_id=memory_id,
            tier=tier_enum,
            title=payload.get("title", ""),
            content=payload.get("content", ""),
            scope=ScopeType(payload.get("scope_type", "tenant")),
            scope_id=payload.get("scope_id", ""),
            tags=payload.get("tags", []),
            parent_id=payload.get("parent_id"),
            related_ids=payload.get("related_ids", []),
            memory_type=payload.get("memory_type", "timeless"),
            state_key=payload.get("state_key", ""),
            is_active=payload.get("is_active", True),
            temporal_precision=payload.get("temporal_precision", "day"),
            created_at=datetime.fromisoformat(payload["created_at"]) if payload.get("created_at") else datetime.now(timezone.utc),
            last_accessed_at=datetime.now(timezone.utc),
        )

        # 实体
        if payload.get("entities"):
            entry.entities = [
                EntityRef(**e) if isinstance(e, dict) else EntityRef(label=str(e))
                for e in payload["entities"]
            ]

        # 信念
        if payload.get("beliefs"):
            entry.beliefs = [
                BeliefRecord(**b) if isinstance(b, dict) else BeliefRecord(content=str(b))
                for b in payload["beliefs"]
            ]

        self._store.inscribe(entry)

    def _apply_update(
        self, memory_id: str, tier: str, payload: dict[str, Any]
    ) -> None:
        """应用更新操作"""
        from mnemos.core.models import MemoryTier

        tier_enum = MemoryTier(tier)
        self._store.revise(memory_id, tier_enum, payload)

    def _apply_delete(self, memory_id: str, tier: str) -> None:
        """应用删除操作（逻辑删除）"""
        from mnemos.core.models import MemoryTier

        tier_enum = MemoryTier(tier)
        now = _now()
        self._store.db.execute(
            f"UPDATE {_table_name(tier_enum)} SET is_active=0, touched_at=? WHERE entry_id=?",
            (now, memory_id),
        )
        self._store.db.commit()

    # ── 核心 API ──────────────────────────────────────────

    def push(
        self,
        scope_type: str | None = None,
        scope_id: str | None = None,
    ) -> dict[str, Any]:
        """
        将本地变更推送到待同步队列。

        扫描本地 sync_log 中状态为 pending 的记录，
        返回待推送的变更摘要。

        Args:
            scope_type: 限定推送范围类型
            scope_id: 限定推送范围 ID

        Returns:
            推送摘要: {pushed: int, conflicts: int, skipped: int}
        """
        pending = self._pending_changes(scope_type, scope_id)

        pushed = 0
        conflicts = 0
        skipped = 0

        for change in pending:
            result = self._apply_remote_change(change)
            if result == "applied":
                pushed += 1
            elif result == "conflict":
                conflicts += 1
            elif result == "skipped":
                skipped += 1

        return {
            "pushed": pushed,
            "conflicts": conflicts,
            "skipped": skipped,
            "total": len(pending),
        }

    def pull(self, remote_db_path: str) -> dict[str, Any]:
        """
        从远程数据库拉取变更到本地。

        打开远程 SQLite 文件，读取其 sync_log 中状态为 pending
        且 node_id 不同于本地的记录，逐条应用到本地。

        Args:
            remote_db_path: 远程 SQLite 数据库路径

        Returns:
            拉取摘要: {applied: int, conflicts: int, skipped: int}
        """
        remote_path = Path(remote_db_path)
        if not remote_path.exists():
            return {
                "applied": 0,
                "conflicts": 0,
                "skipped": 0,
                "error": f"Remote database not found: {remote_db_path}",
            }

        # 以只读模式打开远程数据库
        remote_conn = sqlite3.connect(
            f"file:{remote_path}?mode=ro", uri=True
        )
        remote_conn.row_factory = sqlite3.Row

        try:
            # 读取远程 pending 变更
            rows = remote_conn.execute(
                """SELECT * FROM sync_log
                   WHERE sync_status=? AND node_id!=?
                   ORDER BY created_at ASC""",
                (self.STATUS_PENDING, self._node_id),
            ).fetchall()

            applied = 0
            conflicts = 0
            skipped = 0

            for row in rows:
                change = dict(row)
                result = self._apply_remote_change(change)
                if result == "applied":
                    applied += 1
                elif result == "conflict":
                    conflicts += 1
                elif result == "skipped":
                    skipped += 1

            return {
                "applied": applied,
                "conflicts": conflicts,
                "skipped": skipped,
                "total": len(rows),
            }
        finally:
            remote_conn.close()

    def merge(
        self,
        remote_db_path: str,
        strategy: str = STRATEGY_LWW,
    ) -> dict[str, Any]:
        """
        双向合并：pull + 自动解决冲突。

        1. 先执行 pull 拉取远程变更
        2. 按策略自动解决所有冲突
        3. 将结果标记为 done

        Args:
            remote_db_path: 远程数据库路径
            strategy: 冲突策略 ('lww', 'keep_local', 'keep_remote')

        Returns:
            合并摘要: {pull_result, resolved_count, strategy}
        """
        pull_result = self.pull(remote_db_path)

        # 自动解决所有冲突
        resolved = 0
        conflicts = self.resolve_conflicts()
        for conflict in conflicts:
            self.resolve(conflict["sync_id"], resolution=strategy)
            resolved += 1

        return {
            "pull_result": pull_result,
            "resolved": resolved,
            "strategy": strategy,
        }

    def resolve_conflicts(self) -> list[dict[str, Any]]:
        """
        列出所有未解决的冲突。

        Returns:
            冲突列表: [{sync_id, memory_id, operation, tier, payload, node_id, created_at}]
        """
        rows = self._store.db.execute(
            """SELECT * FROM sync_log
               WHERE sync_status=?
               ORDER BY created_at ASC""",
            (self.STATUS_CONFLICT,),
        ).fetchall()
        return [dict(r) for r in rows]

    def resolve(
        self,
        conflict_id: str,
        resolution: str = "keep_local",
    ) -> dict[str, Any]:
        """
        解决一个冲突。

        Args:
            conflict_id: 冲突记录的 sync_id
            resolution: 解决策略
                - 'keep_local': 保留本地版本
                - 'keep_remote': 保留远程版本
                - 'lww': Last-Writer-Wins（比较时间戳）

        Returns:
            解决结果: {sync_id, resolution, applied}
        """
        conflict = self._store.db.execute(
            "SELECT * FROM sync_log WHERE sync_id=?",
            (conflict_id,),
        ).fetchone()

        if not conflict:
            return {
                "sync_id": conflict_id,
                "error": "Conflict not found",
                "applied": False,
            }

        conflict = dict(conflict)
        memory_id = conflict["memory_id"]
        operation = conflict["operation"]
        tier = conflict["tier"]
        payload = json.loads(conflict["payload"]) if conflict["payload"] else {}
        remote_node = conflict["node_id"]

        if resolution == self.STRATEGY_KEEP_REMOTE:
            # 应用远程版本
            result = self._apply_change_direct(memory_id, operation, tier, payload)
            status = self.STATUS_DONE if result else self.STATUS_CONFLICT

        elif resolution == self.STRATEGY_KEEP_LOCAL:
            # 保留本地，标记远程为已解决（丢弃远程）
            status = self.STATUS_DONE
            result = True

        elif resolution == self.STRATEGY_LWW:
            # Last-Writer-Wins：比较时间戳
            local_entry = self._store.by_id(memory_id)
            local_time = local_entry.last_accessed_at.isoformat() if local_entry else ""
            remote_time = conflict["created_at"]

            if remote_time > local_time:
                # 远程更新，应用远程
                result = self._apply_change_direct(
                    memory_id, operation, tier, payload
                )
            else:
                # 本地更新，保留本地
                result = True
            status = self.STATUS_DONE

        else:
            return {
                "sync_id": conflict_id,
                "error": f"Unknown strategy: {resolution}",
                "applied": False,
            }

        if status == self.STATUS_DONE:
            self._update_sync_status(conflict_id, status, _now())

        return {
            "sync_id": conflict_id,
            "resolution": resolution,
            "applied": result,
        }

    def _apply_change_direct(
        self,
        memory_id: str,
        operation: str,
        tier: str,
        payload: dict[str, Any],
    ) -> bool:
        """直接应用变更（不写 sync_log）"""
        try:
            if operation == self.OP_CREATE:
                self._apply_create(memory_id, tier, payload)
            elif operation == self.OP_UPDATE:
                self._apply_update(memory_id, tier, payload)
            elif operation == self.OP_DELETE:
                self._apply_delete(memory_id, tier)
            return True
        except Exception:
            return False

    def status(self) -> dict[str, Any]:
        """
        同步状态概览。

        Returns:
            状态摘要: {
                pending: int,
                inflight: int,
                conflict: int,
                done: int,
                total: int,
                node_id: str,
                last_sync: str | None,
            }
        """
        stats = {}
        for s in (self.STATUS_PENDING, self.STATUS_INFLIGHT, self.STATUS_CONFLICT, self.STATUS_DONE):
            row = self._store.db.execute(
                "SELECT COUNT(*) FROM sync_log WHERE sync_status=?",
                (s,),
            ).fetchone()
            stats[s] = row[0] if row else 0

        # 最近一次同步时间
        last_row = self._store.db.execute(
            "SELECT MAX(synced_at) FROM sync_log WHERE sync_status=?",
            (self.STATUS_DONE,),
        ).fetchone()
        last_sync = last_row[0] if last_row and last_row[0] else None

        return {
            "pending": stats[self.STATUS_PENDING],
            "inflight": stats[self.STATUS_INFLIGHT],
            "conflict": stats[self.STATUS_CONFLICT],
            "done": stats[self.STATUS_DONE],
            "total": sum(stats.values()),
            "node_id": self._node_id,
            "last_sync": last_sync,
        }

    # ── 变更捕获（供外部调用） ─────────────────────────────

    def record_create(
        self,
        memory_id: str,
        tier: str = "impression",
        payload: dict[str, Any] | None = None,
    ) -> str:
        """
        记录一条创建操作到 sync_log。

        在 PalimpsestStore.inscribe() 之后调用，
        将新写入的记忆记录为待同步变更。

        Args:
            memory_id: 记忆 ID
            tier: 记忆层级
            payload: 完整记忆数据（用于远程重建）

        Returns:
            sync_id
        """
        if payload is None:
            payload = {}
        return self._log_change(
            memory_id, self.OP_CREATE, tier, payload
        )

    def record_update(
        self,
        memory_id: str,
        tier: str = "impression",
        payload: dict[str, Any] | None = None,
    ) -> str:
        """
        记录一条更新操作到 sync_log。

        在 PalimpsestStore.revise() 之后调用。

        Args:
            memory_id: 记忆 ID
            tier: 记忆层级
            payload: 更新字段

        Returns:
            sync_id
        """
        if payload is None:
            payload = {}
        return self._log_change(
            memory_id, self.OP_UPDATE, tier, payload
        )

    def record_delete(
        self,
        memory_id: str,
        tier: str = "impression",
    ) -> str:
        """
        记录一条删除操作到 sync_log。

        Args:
            memory_id: 记忆 ID
            tier: 记忆层级

        Returns:
            sync_id
        """
        return self._log_change(
            memory_id, self.OP_DELETE, tier, {}
        )


# ── 辅助函数 ─────────────────────────────────────────────


def _table_name(tier: Any) -> str:
    """层级枚举 → 表名"""
    from mnemos.core.models import MemoryTier

    return {
        MemoryTier.IMPRESSION: "impressions",
        MemoryTier.PATTERN: "patterns",
        MemoryTier.PRINCIPLE: "principles",
    }[tier]
