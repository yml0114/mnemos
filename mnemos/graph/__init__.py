"""
知识图谱引擎 — KnowledgeGraph

对标 Mem0 Graph Memory (2026-06):
- 实体间显式关系追踪（区别于 entity_cooccur 的隐式共现）
- 加权边 + 时间戳 + 关系标签
- 多跳推理（BFS 深度遍历 + 最短路径）
- 共现推断（从记忆条目自动推断实体关系）
- 社区检测（连通分量聚类）

使用示例:
    from mnemos.storage.palimpsest import PalimpsestStore
    from mnemos.graph import KnowledgeGraph

    store = PalimpsestStore("memory.db")
    store.connect()
    kg = KnowledgeGraph(store)

    # 添加显式关系
    kg.add_edge("陈策", "赵构", relation="协作", weight=2.0)

    # 从记忆条目推断关系
    kg.infer_edges_from_entries(entries)

    # 多跳遍历
    path = kg.shortest_path("陈策", "岳飞")

    # 社区检测
    communities = kg.entity_communities()

    # 自然语言摘要
    summary = kg.summarize("陈策")
"""

from __future__ import annotations

import json
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class KnowledgeGraph:
    """
    知识图谱引擎 — 实体间关系追踪与推理。

    在 entity_cooccur（隐式共现）之上构建显式关系层：
    - entity_edges 表存储带标签、权重、时间戳的显式边
    - co-occurrence 推断自动从记忆条目中发现关系
    - 社区检测揭示实体聚类结构
    """

    def __init__(self, store: Any) -> None:
        """
        初始化知识图谱。

        Args:
            store: PalimpsestStore 实例（已连接或未连接均可）
        """
        self._store = store
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        """确保 entity_edges 表存在（兼容已有数据库）"""
        conn = self._store.connect()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS entity_edges (
                from_id     TEXT NOT NULL,
                to_id       TEXT NOT NULL,
                relation    TEXT NOT NULL DEFAULT 'related',
                weight      REAL NOT NULL DEFAULT 1.0,
                metadata    TEXT NOT NULL DEFAULT '{}',
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL,
                PRIMARY KEY (from_id, to_id, relation)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_edge_from ON entity_edges(from_id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_edge_to ON entity_edges(to_id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_edge_relation ON entity_edges(relation)
        """)
        conn.commit()

    # ── 边操作 ──────────────────────────────────────────

    def add_edge(
        self,
        entity_a: str,
        entity_b: str,
        relation: str = "related",
        weight: float = 1.0,
        metadata: dict | None = None,
    ) -> None:
        """
        添加或增强两个实体之间的关系边。

        如果边已存在，权重累加（类似共现增强）。

        Args:
            entity_a: 起始实体名称
            entity_b: 目标实体名称
            relation: 关系标签（如 "协作", "对立", "同属"）
            weight: 初始权重（累加模式）
            metadata: 附加元数据
        """
        now = _now()
        meta_json = json.dumps(metadata or {}, ensure_ascii=False)

        # 规范化：字典序排列确保双向边合并
        a, b = sorted([entity_a, entity_b])

        self._store.connect().execute(
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
            (a, b, relation, weight, meta_json, now, now),
        )
        self._store.connect().commit()

    def remove_edge(
        self,
        entity_a: str,
        entity_b: str,
        relation: str | None = None,
    ) -> int:
        """
        删除实体间的边。

        Args:
            entity_a: 起始实体
            entity_b: 目标实体
            relation: 关系标签，None 时删除所有关系

        Returns:
            删除的边数
        """
        a, b = sorted([entity_a, entity_b])
        conn = self._store.connect()

        if relation is None:
            cursor = conn.execute(
                "DELETE FROM entity_edges WHERE from_id=? AND to_id=?",
                (a, b),
            )
        else:
            cursor = conn.execute(
                "DELETE FROM entity_edges WHERE from_id=? AND to_id=? AND relation=?",
                (a, b, relation),
            )
        conn.commit()
        return cursor.rowcount

    def get_edges(self, entity_id: str) -> list[dict[str, Any]]:
        """
        获取与某个实体相连的所有边。

        Args:
            entity_id: 实体名称

        Returns:
            边列表，每条边包含 source, target, relation, weight, metadata, created_at
        """
        rows = self._store.connect().execute(
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
        entity_a: str,
        entity_b: str,
        delta: float,
    ) -> None:
        """
        增减边权重（正数增强，负数削弱）。

        Args:
            entity_a: 起始实体
            entity_b: 目标实体
            delta: 权重变化量
        """
        a, b = sorted([entity_a, entity_b])
        now = _now()
        self._store.connect().execute(
            """UPDATE entity_edges
               SET weight = MAX(0, weight + ?), updated_at = ?
               WHERE from_id=? AND to_id=?""",
            (delta, now, a, b),
        )
        self._store.connect().commit()

    # ── 多跳遍历 ──────────────────────────────────────────

    def neighbors(
        self,
        entity_id: str,
        max_depth: int = 2,
        min_weight: float = 0.0,
    ) -> dict[int, list[dict[str, Any]]]:
        """
        BFS 多跳遍历：从实体出发，按深度层级返回邻居。

        Args:
            entity_id: 起始实体
            max_depth: 最大跳数
            min_weight: 最小边权重过滤

        Returns:
            {depth: [edge_dict, ...]} 按深度分组（depth 为 int）
        """
        conn = self._store.connect()
        visited: set[str] = {entity_id}
        frontier = [entity_id]
        result: dict[int, list[dict[str, Any]]] = {}

        for depth in range(1, max_depth + 1):
            next_frontier: list[str] = []
            edges_at_depth: list[dict[str, Any]] = []

            for eid in frontier:
                rows = conn.execute(
                    """SELECT from_id, to_id, relation, weight, metadata,
                              created_at, updated_at
                       FROM entity_edges
                       WHERE (from_id=? OR to_id=?) AND weight >= ?
                       ORDER BY weight DESC""",
                    (eid, eid, min_weight),
                ).fetchall()

                for r in rows:
                    neighbor = r["to_id"] if r["from_id"] == eid else r["from_id"]
                    if neighbor not in visited:
                        visited.add(neighbor)
                        next_frontier.append(neighbor)

                    edges_at_depth.append({
                        "source": r["from_id"],
                        "target": r["to_id"],
                        "relation": r["relation"],
                        "weight": r["weight"],
                        "metadata": json.loads(r["metadata"]) if r["metadata"] else {},
                        "depth": depth,
                    })

            if edges_at_depth:
                result[depth] = edges_at_depth
            frontier = next_frontier
            if not frontier:
                break

        return result

    def shortest_path(
        self,
        entity_a: str,
        entity_b: str,
        max_depth: int = 6,
    ) -> list[str] | None:
        """
        BFS 最短路径：找到两个实体之间的最短连接。

        Args:
            entity_a: 起始实体
            entity_b: 目标实体
            max_depth: 最大搜索深度

        Returns:
            路径列表 [entity_a, ..., entity_b]，无路径返回 None
        """
        if entity_a == entity_b:
            return [entity_a]

        conn = self._store.connect()
        visited: dict[str, str | None] = {entity_a: None}  # child -> parent
        frontier = [entity_a]

        for _ in range(max_depth):
            next_frontier: list[str] = []
            for eid in frontier:
                rows = conn.execute(
                    """SELECT from_id, to_id FROM entity_edges
                       WHERE from_id=? OR to_id=?""",
                    (eid, eid),
                ).fetchall()

                for r in rows:
                    neighbor = r["to_id"] if r["from_id"] == eid else r["from_id"]
                    if neighbor not in visited:
                        visited[neighbor] = eid
                        next_frontier.append(neighbor)
                        if neighbor == entity_b:
                            # 回溯路径
                            path = [entity_b]
                            current = entity_b
                            while visited.get(current) is not None:
                                current = visited[current]
                                path.append(current)
                            path.reverse()
                            return path

            frontier = next_frontier
            if not frontier:
                break

        return None

    def related_entities(
        self,
        entity_id: str,
        min_weight: float = 0.1,
    ) -> list[dict[str, Any]]:
        """
        获取与实体相关的所有邻居，按权重降序排列。

        综合 entity_edges（显式）和 entity_cooccur（隐式）的信号。

        Args:
            entity_id: 实体名称
            min_weight: 最小权重阈值

        Returns:
            排序后的相关实体列表
        """
        conn = self._store.connect()
        scores: dict[str, dict[str, Any]] = {}

        # 显式边
        rows = conn.execute(
            """SELECT from_id, to_id, relation, weight, metadata
               FROM entity_edges
               WHERE (from_id=? OR to_id=?) AND weight >= ?
               ORDER BY weight DESC""",
            (entity_id, entity_id, min_weight),
        ).fetchall()

        for r in rows:
            neighbor = r["to_id"] if r["from_id"] == entity_id else r["from_id"]
            if neighbor not in scores:
                scores[neighbor] = {
                    "entity": neighbor,
                    "explicit_weight": 0.0,
                    "cooccur_weight": 0,
                    "relations": [],
                    "total_weight": 0.0,
                }
            scores[neighbor]["explicit_weight"] += r["weight"]
            scores[neighbor]["relations"].append(r["relation"])

        # 隐式共现
        rows = conn.execute(
            """SELECT a, b, weight FROM entity_cooccur
               WHERE a=? OR b=?
               ORDER BY weight DESC""",
            (entity_id, entity_id),
        ).fetchall()

        for r in rows:
            neighbor = r["b"] if r["a"] == entity_id else r["a"]
            if neighbor not in scores:
                scores[neighbor] = {
                    "entity": neighbor,
                    "explicit_weight": 0.0,
                    "cooccur_weight": 0,
                    "relations": [],
                    "total_weight": 0.0,
                }
            scores[neighbor]["cooccur_weight"] = r["weight"]

        # 合成总权重：显式边 0.6 + 共现 0.4（归一化）
        max_cooccur = max(
            (s["cooccur_weight"] for s in scores.values()),
            default=1.0,
        ) or 1.0

        for s in scores.values():
            cooccur_norm = s["cooccur_weight"] / max_cooccur
            s["total_weight"] = s["explicit_weight"] * 0.6 + cooccur_norm * 0.4
            s["relations"] = list(set(s["relations"]))  # 去重

        ranked = sorted(
            [s for s in scores.values() if s["total_weight"] >= min_weight],
            key=lambda x: x["total_weight"],
            reverse=True,
        )

        return ranked

    # ── 共现推断 ──────────────────────────────────────────

    def infer_edges_from_entries(
        self,
        entries: list[Any],
        base_weight: float = 1.0,
    ) -> int:
        """
        从记忆条目中推断实体关系（共现推断）。

        当两个实体出现在同一条记忆中时，建立/增强它们之间的边。
        关系标签默认为 "co_occur"，可通过 metadata 传递上下文信息。

        Args:
            entries: MemoryEntry 列表
            base_weight: 每次共现的基础权重增量

        Returns:
            新建或增强的边数
        """
        edges_created = 0

        for entry in entries:
            entities = entry.entities if hasattr(entry, "entities") else []
            if len(entities) < 2:
                continue

            labels = [e.label for e in entities]

            # 同一实体不自连
            # 所有实体对之间建立共现边
            for i in range(len(labels)):
                for j in range(i + 1, len(labels)):
                    a, b = sorted([labels[i], labels[j]])
                    if a == b:
                        continue

                    # 查询现有边
                    existing = self._store.connect().execute(
                        """SELECT weight FROM entity_edges
                           WHERE from_id=? AND to_id=? AND relation='co_occur'""",
                        (a, b),
                    ).fetchone()

                    if existing:
                        # 增强：共现越多关系越强
                        delta = base_weight * (1.0 / (1.0 + existing["weight"] * 0.1))
                        self._store.connect().execute(
                            """UPDATE entity_edges
                               SET weight = weight + ?, updated_at = ?
                               WHERE from_id=? AND to_id=? AND relation='co_occur'""",
                            (delta, _now(), a, b),
                        )
                    else:
                        # 新建边
                        metadata = json.dumps({
                            "source_entry": entry.entry_id,
                            "source_title": getattr(entry, "title", ""),
                        }, ensure_ascii=False)
                        now = _now()
                        self._store.connect().execute(
                            """INSERT INTO entity_edges
                               (from_id, to_id, relation, weight, metadata,
                                created_at, updated_at)
                               VALUES (?, ?, 'co_occur', ?, ?, ?, ?)""",
                            (a, b, base_weight, metadata, now, now),
                        )
                    edges_created += 1

        self._store.connect().commit()
        return edges_created

    # ── 社区检测 ──────────────────────────────────────────

    def entity_communities(
        self,
        min_weight: float = 0.5,
    ) -> list[list[str]]:
        """
        社区检测：基于连通分量的实体聚类。

        使用 BFS/Union-Find 找出所有连通子图，每个子图即一个社区。
        低权重边（< min_weight）被剪枝，避免噪声。

        Args:
            min_weight: 最小边权重阈值

        Returns:
            社区列表，每个社区是实体名称列表
        """
        conn = self._store.connect()
        rows = conn.execute(
            """SELECT from_id, to_id, weight FROM entity_edges
               WHERE weight >= ?""",
            (min_weight,),
        ).fetchall()

        # Union-Find
        parent: dict[str, str] = {}

        def find(x: str) -> str:
            while parent.get(x, x) != x:
                parent[x] = parent.get(parent[x], parent[x])  # 路径压缩
                x = parent[x]
            return x

        def union(x: str, y: str) -> None:
            rx, ry = find(x), find(y)
            if rx != ry:
                parent[rx] = ry

        for r in rows:
            a, b = r["from_id"], r["to_id"]
            parent.setdefault(a, a)
            parent.setdefault(b, b)
            union(a, b)

        # 收集连通分量
        components: dict[str, list[str]] = defaultdict(list)
        for node in parent:
            root = find(node)
            components[root].append(node)

        # 按大小降序排列，过滤单节点社区
        communities = sorted(
            [sorted(members) for members in components.values() if len(members) >= 2],
            key=len,
            reverse=True,
        )

        return communities

    # ── 共现矩阵 ──────────────────────────────────────────

    def co_occurrence_matrix(self) -> dict[str, dict[str, float]]:
        """
        构建实体共现矩阵（稀疏表示）。

        合并 entity_edges 和 entity_cooccur 的权重。

        Returns:
            {entity_a: {entity_b: weight, ...}, ...}
        """
        matrix: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        conn = self._store.connect()

        # 显式边
        rows = conn.execute(
            "SELECT from_id, to_id, weight FROM entity_edges"
        ).fetchall()
        for r in rows:
            matrix[r["from_id"]][r["to_id"]] += r["weight"]
            matrix[r["to_id"]][r["from_id"]] += r["weight"]

        # 隐式共现
        rows = conn.execute(
            "SELECT a, b, weight FROM entity_cooccur"
        ).fetchall()
        for r in rows:
            matrix[r["a"]][r["b"]] += float(r["weight"])
            matrix[r["b"]][r["a"]] += float(r["weight"])

        # 转为普通 dict
        return {k: dict(v) for k, v in matrix.items()}

    # ── 自然语言摘要 ──────────────────────────────────────

    def summarize(self, entity_id: str) -> str:
        """
        生成实体关系的自然语言摘要。

        Args:
            entity_id: 实体名称

        Returns:
            中文自然语言描述
        """
        edges = self.get_edges(entity_id)
        if not edges:
            return f"「{entity_id}」目前没有已知的关系。"

        # 按关系分组
        by_relation: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for e in edges:
            by_relation[e["relation"]].append(e)

        lines = [f"「{entity_id}」的关系概览："]

        for relation, group in by_relation.items():
            # 排序：按权重降序
            group.sort(key=lambda x: x["weight"], reverse=True)
            others = []
            for e in group:
                neighbor = e["target"] if e["source"] == entity_id else e["source"]
                others.append(neighbor)

            if len(others) <= 3:
                others_str = "、".join(others)
            else:
                others_str = "、".join(others[:3]) + f" 等 {len(others)} 个实体"

            lines.append(f"  · {relation}：{others_str}")

        # 补充共现统计
        cooccur_rows = self._store.connect().execute(
            """SELECT COUNT(*) as cnt FROM entity_cooccur
               WHERE a=? OR b=?""",
            (entity_id, entity_id),
        ).fetchone()
        cooccur_count = cooccur_rows["cnt"] if cooccur_rows else 0

        if cooccur_count > 0:
            lines.append(f"  · 共现关系：与 {cooccur_count} 个实体在记忆中共同出现")

        total_explicit = len(edges)
        lines.append(f"\n共 {total_explicit} 条显式关系。")

        return "\n".join(lines)

    # ── 图谱导出 ──────────────────────────────────────────

    def to_networkx(self) -> Any:
        """
        导出为 NetworkX 图对象（可选依赖）。

        Returns:
            networkx.Graph

        Raises:
            ImportError: 如果未安装 networkx
        """
        try:
            import networkx as nx
        except ImportError:
            raise ImportError(
                "需要安装 networkx: pip install networkx"
            )

        G = nx.Graph()
        conn = self._store.connect()
        rows = conn.execute(
            "SELECT from_id, to_id, relation, weight FROM entity_edges"
        ).fetchall()

        for r in rows:
            G.add_edge(
                r["from_id"],
                r["to_id"],
                relation=r["relation"],
                weight=r["weight"],
            )

        return G

    def to_dict(self, center: str | None = None, limit: int = 100) -> dict[str, Any]:
        """
        导出为前端可视化格式。

        Args:
            center: 中心实体（None 时返回全局图）
            limit: 最大边数

        Returns:
            {nodes: [...], edges: [...], total_nodes, total_edges}
        """
        conn = self._store.connect()

        if center:
            rows = conn.execute(
                """SELECT from_id, to_id, relation, weight, created_at
                   FROM entity_edges
                   WHERE from_id=? OR to_id=?
                   ORDER BY weight DESC
                   LIMIT ?""",
                (center, center, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT from_id, to_id, relation, weight, created_at
                   FROM entity_edges
                   ORDER BY weight DESC
                   LIMIT ?""",
                (limit,),
            ).fetchall()

        nodes_set: set[str] = set()
        edges: list[dict[str, Any]] = []
        for r in rows:
            nodes_set.add(r["from_id"])
            nodes_set.add(r["to_id"])
            edges.append({
                "source": r["from_id"],
                "target": r["to_id"],
                "relation": r["relation"],
                "weight": r["weight"],
                "created_at": r["created_at"],
            })

        # 获取实体元信息
        entity_labels = list(nodes_set)
        nodes = []
        if entity_labels:
            placeholders = ",".join("?" for _ in entity_labels)
            meta_rows = conn.execute(
                f"""SELECT DISTINCT label, etype, COUNT(*) as mem_count
                    FROM entity_index WHERE label IN ({placeholders})
                    GROUP BY label""",
                entity_labels,
            ).fetchall()
            meta = {r["label"]: {"type": r["etype"], "memory_count": r["mem_count"]} for r in meta_rows}
            nodes = [
                {
                    "id": label,
                    "label": label,
                    "type": meta.get(label, {}).get("type", "concept"),
                    "memory_count": meta.get(label, {}).get("memory_count", 0),
                }
                for label in entity_labels
            ]

        return {
            "center": center,
            "nodes": nodes,
            "edges": edges,
            "total_nodes": len(nodes),
            "total_edges": len(edges),
        }

    # ── 统计 ──────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        """
        知识图谱统计概览。

        Returns:
            {total_edges, total_entities, avg_weight, relation_types, ...}
        """
        conn = self._store.connect()

        total_edges = conn.execute(
            "SELECT COUNT(*) FROM entity_edges"
        ).fetchone()[0]

        total_entities = conn.execute(
            """SELECT COUNT(DISTINCT eid) FROM (
                SELECT from_id as eid FROM entity_edges
                UNION
                SELECT to_id as eid FROM entity_edges
            )"""
        ).fetchone()[0]

        avg_weight_row = conn.execute(
            "SELECT AVG(weight) FROM entity_edges"
        ).fetchone()
        avg_weight = avg_weight_row[0] if avg_weight_row[0] else 0.0

        relation_rows = conn.execute(
            """SELECT relation, COUNT(*) as cnt, AVG(weight) as avg_w
               FROM entity_edges GROUP BY relation ORDER BY cnt DESC"""
        ).fetchall()

        return {
            "total_edges": total_edges,
            "total_entities": total_entities,
            "avg_weight": round(avg_weight, 3),
            "relations": [
                {"relation": r["relation"], "count": r["cnt"], "avg_weight": round(r["avg_w"], 3)}
                for r in relation_rows
            ],
        }
