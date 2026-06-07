"""
可视化数据提供层

将 PalimpsestStore 的原始数据转换为前端可视化所需的结构：
- 记忆星系（3D 粒子布局）
- 信念演化链
- 实体关系图
- 统计概览
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from mnemos.storage.palimpsest import PalimpsestStore


class DashboardProvider:
    """从存储引擎提取可视化数据"""

    def __init__(self, store: PalimpsestStore):
        self._store = store

    # ── 记忆星系 ──────────────────────────────────────

    def galaxy(self, limit: int = 200) -> dict[str, Any]:
        """
        构建记忆星系数据。

        每条记忆是一个星体：
        - 印象 = 闪烁粒子
        - 模式 = 光环行星
        - 原则 = 恒星

        实体共现关系形成引力连线。
        """
        store = self._store
        store.connect()

        # 收集所有印象
        rows = store.db.execute(
            "SELECT entry_id, title, tier, scope_type, "
            "entities_json, tags_json, created_at, touched_at, decay, hits "
            "FROM ("
            "  SELECT entry_id, title, 'impression' as tier, scope_type, "
            "  entities_json, tags_json, created_at, touched_at, decay, hits "
            "  FROM impressions "
            "  UNION ALL "
            "  SELECT entry_id, title, 'pattern' as tier, scope_type, "
            "  entities_json, tags_json, created_at, touched_at, 1.0 as decay, 0 as hits "
            "  FROM patterns "
            "  UNION ALL "
            "  SELECT entry_id, title, 'principle' as tier, scope_type, "
            "  entities_json, tags_json, created_at, touched_at, 1.0 as decay, 0 as hits "
            "  FROM principles "
            ") ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()

        # 构建节点
        nodes: list[dict] = []
        for r in rows:
            entities = json.loads(r["entities_json"]) if r["entities_json"] else []
            tags = json.loads(r["tags_json"]) if r["tags_json"] else []
            nodes.append({
                "id": r["entry_id"],
                "label": r["title"] or r["entry_id"][:8],
                "tier": r["tier"],
                "scope": r["scope_type"],
                "entities": [e.get("label", "") for e in entities],
                "tags": tags,
                "created_at": r["created_at"],
                "touched_at": r["touched_at"],
                "decay": r["decay"],
                "hits": r["hits"],
                # 3D 位置由前端分配，这里只给权重参数
                "mass": 1.0 + len(entities) * 0.3 + len(tags) * 0.2,
                "brightness": r["decay"],
            })

        # 构建连线（实体共现）
        links: list[dict] = []
        if nodes:
            entity_map: dict[str, list[str]] = {}
            for n in nodes:
                for ent in n["entities"]:
                    if ent not in entity_map:
                        entity_map[ent] = []
                    entity_map[ent].append(n["id"])

            linked_pairs: set[tuple[str, str]] = set()
            for mem_ids in entity_map.values():
                for i in range(len(mem_ids)):
                    for j in range(i + 1, len(mem_ids)):
                        a, b = sorted([mem_ids[i], mem_ids[j]])
                        if (a, b) not in linked_pairs:
                            linked_pairs.add((a, b))
                            links.append({"source": a, "target": b, "type": "entity"})

        # 时间聚类
        timeline = self._build_timeline_clusters(nodes)

        return {
            "nodes": nodes,
            "links": links,
            "timeline": timeline,
            "total": len(nodes),
        }

    def _build_timeline_clusters(self, nodes: list[dict]) -> list[dict]:
        """按时间将记忆分组聚类"""
        if not nodes:
            return []
        clusters: dict[str, list[dict]] = {}
        for n in nodes:
            try:
                dt = datetime.fromisoformat(n["created_at"])
                key = dt.strftime("%Y-%m-%d")
            except (ValueError, KeyError):
                key = "unknown"
            clusters.setdefault(key, []).append(n)

        return [
            {
                "date": k,
                "count": len(v),
                "tiers": {
                    "impression": sum(1 for x in v if x["tier"] == "impression"),
                    "pattern": sum(1 for x in v if x["tier"] == "pattern"),
                    "principle": sum(1 for x in v if x["tier"] == "principle"),
                },
            }
            for k, v in sorted(clusters.items())
        ]

    # ── 信念演化树 ────────────────────────────────────

    def belief_tree(self, memory_id: str | None = None) -> dict[str, Any]:
        """
        构建信念演化树。

        每条信念链展示：
        旧信念 → 被推翻 → 新信念 → 强化 → 更确信
        """
        store = self._store
        store.connect()

        if memory_id:
            rows = store.db.execute(
                "SELECT * FROM belief_log WHERE memory_id=? ORDER BY adopted_at",
                (memory_id,),
            ).fetchall()
        else:
            rows = store.db.execute(
                "SELECT * FROM belief_log ORDER BY adopted_at DESC LIMIT 100"
            ).fetchall()

        # 按 memory_id 分组
        chains: dict[str, list[dict]] = {}
        for r in rows:
            mid = r["memory_id"]
            chains.setdefault(mid, []).append({
                "belief_id": r["belief_id"],
                "content": r["content"],
                "confidence": r["confidence"],
                "source": r["source"],
                "adopted_at": r["adopted_at"],
                "superseded_by": r["superseded"],
                "superseded_at": r["superseded_at"],
                "is_active": r["superseded"] is None,
            })

        # 构建树结构
        trees = []
        for mid, chain in chains.items():
            memory = store.by_id(mid)
            title = memory.title if memory else mid[:8]
            trees.append({
                "memory_id": mid,
                "title": title,
                "chain": chain,
                "revisions": sum(1 for b in chain if b["superseded_by"]),
                "active_belief": next(
                    (b for b in chain if b["is_active"]), chain[-1] if chain else None
                ),
            })

        return {
            "trees": trees,
            "total_beliefs": len(rows),
            "total_revisions": sum(t["revisions"] for t in trees),
        }

    # ── 实体关系图谱 ──────────────────────────────────

    def entity_graph(self, center_label: str | None = None, limit: int = 50) -> dict[str, Any]:
        """
        构建实体关系图谱。

        节点 = 实体
        边 = 共现关系（权重 = 共现次数）
        """
        store = self._store
        store.connect()

        if center_label:
            graph = store.entity_graph(center_label, limit)
            return {
                "center": center_label,
                "nodes": graph["nodes"],
                "edges": graph["edges"],
                "total_nodes": len(graph["nodes"]),
                "total_edges": len(graph["edges"]),
            }

        # 全局图谱：取共现权重最高的
        rows = store.db.execute(
            "SELECT a, b, weight, last_seen FROM entity_cooccur "
            "ORDER BY weight DESC LIMIT ?",
            (limit * 2,),
        ).fetchall()

        nodes_set: set[str] = set()
        edges: list[dict] = []
        for r in rows:
            nodes_set.add(r["a"])
            nodes_set.add(r["b"])
            edges.append({
                "source": r["a"],
                "target": r["b"],
                "weight": r["weight"],
                "last_seen": r["last_seen"],
            })

        # 获取实体元信息
        entity_labels = list(nodes_set)[:limit]
        placeholders = ",".join("?" for _ in entity_labels)
        meta_rows = store.db.execute(
            f"SELECT DISTINCT label, etype, COUNT(*) as mem_count "
            f"FROM entity_index WHERE label IN ({placeholders}) "
            f"GROUP BY label",
            entity_labels,
        ).fetchall()

        entity_meta = {
            r["label"]: {"type": r["etype"], "memory_count": r["mem_count"]}
            for r in meta_rows
        }

        nodes = [
            {
                "id": label,
                "label": label,
                "type": entity_meta.get(label, {}).get("type", "concept"),
                "memory_count": entity_meta.get(label, {}).get("memory_count", 0),
            }
            for label in nodes_set
        ]

        return {
            "nodes": nodes,
            "edges": edges,
            "total_nodes": len(nodes),
            "total_edges": len(edges),
        }

    # ── 统计概览 ──────────────────────────────────────

    def overview(self) -> dict[str, Any]:
        """记忆世界统计仪表盘"""
        store = self._store
        store.connect()
        counts = store.count()

        # 时间分布
        time_rows = store.db.execute(
            "SELECT substr(created_at,1,10) as day, COUNT(*) as cnt "
            "FROM impressions GROUP BY day ORDER BY day DESC LIMIT 30"
        ).fetchall()

        # 实体分布
        top_entities = store.db.execute(
            "SELECT label, etype, COUNT(*) as cnt FROM entity_index "
            "GROUP BY label ORDER BY cnt DESC LIMIT 20"
        ).fetchall()

        # 衰减分布
        decay_rows = store.db.execute(
            "SELECT "
            "  SUM(CASE WHEN decay >= 0.8 THEN 1 ELSE 0 END) as fresh, "
            "  SUM(CASE WHEN decay >= 0.5 AND decay < 0.8 THEN 1 ELSE 0 END) as active, "
            "  SUM(CASE WHEN decay >= 0.2 AND decay < 0.5 THEN 1 ELSE 0 END) as fading, "
            "  SUM(CASE WHEN decay < 0.2 THEN 1 ELSE 0 END) as forgotten "
            "FROM impressions"
        ).fetchone()

        return {
            "counts": counts,
            "timeline": [{"date": r["day"], "count": r["cnt"]} for r in reversed(time_rows)],
            "top_entities": [
                {"label": r["label"], "type": r["etype"], "count": r["cnt"]}
                for r in top_entities
            ],
            "decay_distribution": dict(decay_rows) if decay_rows else {},
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
