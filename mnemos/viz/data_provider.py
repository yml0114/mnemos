"""
可视化数据提供层

将 PalimpsestStore 的原始数据转换为前端可视化所需的结构。
修复：entities_json 是纯字符串列表，不是 dict 列表。
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

    def _connect(self):
        self._store.connect()

    @staticmethod
    def _parse_entities(raw) -> list[str]:
        """entities_json 可能是 ['A','B'] 或 ['{"label":"A"}'] 格式"""
        if not raw:
            return []
        data = json.loads(raw) if isinstance(raw, str) else raw
        result = []
        for e in data:
            if isinstance(e, dict):
                result.append(e.get("label", ""))
            elif isinstance(e, str):
                result.append(e)
        return [x for x in result if x]

    # ── 记忆星系 ──────────────────────────────────────

    def galaxy(self, limit: int = 200) -> dict[str, Any]:
        self._connect()
        store = self._store

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

        nodes: list[dict] = []
        for r in rows:
            entities = self._parse_entities(r["entities_json"])
            tags = json.loads(r["tags_json"]) if r["tags_json"] else []
            nodes.append({
                "id": r["entry_id"],
                "label": r["title"] or r["entry_id"][:8],
                "tier": r["tier"],
                "scope": r["scope_type"],
                "entities": entities,
                "tags": tags,
                "created_at": r["created_at"],
                "touched_at": r["touched_at"],
                "decay": r["decay"],
                "hits": r["hits"],
                "mass": 1.0 + len(entities) * 0.3 + len(tags) * 0.2,
                "brightness": r["decay"],
            })

        # 构建连线（实体共现）
        links: list[dict] = []
        if nodes:
            entity_map: dict[str, list[str]] = {}
            for n in nodes:
                for ent in n["entities"]:
                    entity_map.setdefault(ent, []).append(n["id"])

            linked_pairs: set[tuple[str, str]] = set()
            for mem_ids in entity_map.values():
                for i in range(len(mem_ids)):
                    for j in range(i + 1, len(mem_ids)):
                        a, b = sorted([mem_ids[i], mem_ids[j]])
                        if (a, b) not in linked_pairs:
                            linked_pairs.add((a, b))
                            links.append({"source": a, "target": b, "type": "entity"})

        timeline = self._build_timeline_clusters(nodes)
        return {"nodes": nodes, "links": links, "timeline": timeline, "total": len(nodes)}

    def _build_timeline_clusters(self, nodes: list[dict]) -> list[dict]:
        if not nodes:
            return []
        clusters: dict[str, list[dict]] = {}
        for n in nodes:
            try:
                key = datetime.fromisoformat(n["created_at"]).strftime("%Y-%m-%d")
            except (ValueError, KeyError):
                key = "unknown"
            clusters.setdefault(key, []).append(n)
        return [
            {"date": k, "count": len(v), "tiers": {
                "impression": sum(1 for x in v if x["tier"] == "impression"),
                "pattern": sum(1 for x in v if x["tier"] == "pattern"),
                "principle": sum(1 for x in v if x["tier"] == "principle"),
            }}
            for k, v in sorted(clusters.items())
        ]

    # ── 信念演化树 ────────────────────────────────────

    def belief_tree(self, memory_id: str | None = None) -> dict[str, Any]:
        self._connect()
        store = self._store

        if memory_id:
            rows = store.db.execute(
                "SELECT * FROM belief_log WHERE memory_id=? ORDER BY adopted_at",
                (memory_id,),
            ).fetchall()
        else:
            rows = store.db.execute(
                "SELECT * FROM belief_log ORDER BY adopted_at DESC LIMIT 100"
            ).fetchall()

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

        return {"trees": trees, "total_beliefs": len(rows),
                "total_revisions": sum(t["revisions"] for t in trees)}

    # ── 实体关系图谱 ──────────────────────────────────

    def entity_graph(self, center_label: str | None = None, limit: int = 50) -> dict[str, Any]:
        self._connect()
        store = self._store

        if center_label:
            # 用 entity_edges（有数据）而非 entity_cooccur
            edges = store.db.execute(
                "SELECT from_id as source, to_id as target, weight "
                "FROM entity_edges WHERE from_id=? OR to_id=? ORDER BY weight DESC LIMIT ?",
                (center_label, center_label, limit),
            ).fetchall()

            node_set = {center_label}
            edge_list = []
            for e in edges:
                node_set.add(e["source"])
                node_set.add(e["target"])
                edge_list.append({"source": e["source"], "target": e["target"], "weight": e["weight"]})

            # 获取实体元信息
            placeholders = ",".join("?" for _ in node_set)
            meta_rows = store.db.execute(
                f"SELECT label, etype, COUNT(*) as mem_count "
                f"FROM entity_index WHERE label IN ({placeholders}) GROUP BY label",
                list(node_set),
            ).fetchall()
            meta = {r["label"]: {"type": r["etype"], "memory_count": r["mem_count"]} for r in meta_rows}

            nodes = [{"id": node_id, "label": node_id, "type": meta.get(node_id, {}).get("type", "concept"),
                       "memory_count": meta.get(node_id, {}).get("memory_count", 0)}
                      for node_id in node_set]
            return {"center": center_label, "nodes": nodes, "edges": edge_list,
                    "total_nodes": len(nodes), "total_edges": len(edge_list)}

        # 全局图谱：用 entity_edges
        rows = store.db.execute(
            "SELECT from_id, to_id, weight FROM entity_edges "
            "ORDER BY weight DESC LIMIT ?", (limit * 2,)
        ).fetchall()

        nodes_set: set[str] = set()
        edges: list[dict] = []
        for r in rows:
            nodes_set.add(r["from_id"])
            nodes_set.add(r["to_id"])
            edges.append({"source": r["from_id"], "target": r["to_id"], "weight": r["weight"]})

        # 获取实体元信息
        entity_labels = list(nodes_set)[:limit]
        if entity_labels:
            placeholders = ",".join("?" for _ in entity_labels)
            meta_rows = store.db.execute(
                f"SELECT DISTINCT label, etype, COUNT(*) as mem_count "
                f"FROM entity_index WHERE label IN ({placeholders}) GROUP BY label",
                entity_labels,
            ).fetchall()
            entity_meta = {r["label"]: {"type": r["etype"], "memory_count": r["mem_count"]}
                           for r in meta_rows}
        else:
            entity_meta = {}

        nodes = [{"id": node_id, "label": node_id, "type": entity_meta.get(node_id, {}).get("type", "concept"),
                   "memory_count": entity_meta.get(node_id, {}).get("memory_count", 0)}
                  for node_id in nodes_set]

        return {"nodes": nodes, "edges": edges, "total_nodes": len(nodes), "total_edges": len(edges)}

    # ── 统计概览 ──────────────────────────────────────

    def overview(self) -> dict[str, Any]:
        self._connect()
        store = self._store
        counts = store.count()

        time_rows = store.db.execute(
            "SELECT substr(created_at,1,10) as day, COUNT(*) as cnt "
            "FROM impressions GROUP BY day ORDER BY day DESC LIMIT 30"
        ).fetchall()

        top_entities = store.db.execute(
            "SELECT label, etype, COUNT(*) as cnt FROM entity_index "
            "GROUP BY label ORDER BY cnt DESC LIMIT 20"
        ).fetchall()

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
            "top_entities": [{"label": r["label"], "type": r["etype"], "count": r["cnt"]}
                             for r in top_entities],
            "decay_distribution": dict(decay_rows) if decay_rows else {},
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    # ── 同步状态 ────────────────────────────────────────

    def sync_status(self) -> dict[str, Any]:
        """同步概览（用于可视化）"""
        self._connect()
        try:
            store = self._store
            rows = store.db.execute(
                "SELECT sync_status, COUNT(*) as cnt FROM sync_log GROUP BY sync_status"
            ).fetchall()
            status = {r["sync_status"]: r["cnt"] for r in rows}
            total = sum(status.values()) if status else 0
            return {
                "total": total,
                "pending": status.get("pending", 0),
                "inflight": status.get("inflight", 0),
                "conflict": status.get("conflict", 0),
                "done": status.get("done", 0),
            }
        except Exception:
            return {"total": 0, "error": "sync_log not available"}

    # ── 多模态图库 ──────────────────────────────────────

    def multimodal_gallery(self, limit: int = 50) -> dict[str, Any]:
        """媒体附件概览"""
        self._connect()
        try:
            store = self._store
            rows = store.db.execute(
                "SELECT attachment_id, memory_id, media_type, file_path, "
                "summary, created_at FROM media_attachments "
                "ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
            by_type: dict[str, int] = {}
            items = []
            for r in rows:
                mt = r["media_type"] or "unknown"
                by_type[mt] = by_type.get(mt, 0) + 1
                items.append(dict(r))
            return {"total": len(items), "by_type": by_type, "items": items}
        except Exception:
            return {"total": 0, "error": "media_attachments not available"}

    # ── 自修复监控 ──────────────────────────────────────

    def heal_overview(self) -> dict[str, Any]:
        """不一致性监控面板"""
        self._connect()
        try:
            store = self._store
            total = store.db.execute(
                "SELECT COUNT(*) FROM inconsistency_log"
            ).fetchone()[0]
            by_type = store.db.execute(
                "SELECT inconsistency_type, COUNT(*) as cnt "
                "FROM inconsistency_log GROUP BY inconsistency_type"
            ).fetchall()
            by_severity = store.db.execute(
                "SELECT severity, COUNT(*) as cnt "
                "FROM inconsistency_log GROUP BY severity"
            ).fetchall()
            healed = store.db.execute(
                "SELECT COUNT(*) FROM inconsistency_log WHERE auto_healed=1"
            ).fetchone()[0]
            recent = store.db.execute(
                "SELECT * FROM inconsistency_log ORDER BY created_at DESC LIMIT 10"
            ).fetchall()
            return {
                "total": total,
                "healed": healed,
                "unhealed": total - healed,
                "by_type": {r["inconsistency_type"]: r["cnt"] for r in by_type},
                "by_severity": {r["severity"]: r["cnt"] for r in by_severity},
                "recent": [dict(r) for r in recent],
            }
        except Exception:
            return {"total": 0, "error": "inconsistency_log not available"}

    # ── 时间线图谱 ──────────────────────────────────────

    def temporal_graph_data(self, max_events: int = 100) -> dict[str, Any]:
        """时间线演化图谱数据（D3 力导向图格式）"""
        self._connect()
        try:
            store = self._store
            events = store.db.execute(
                "SELECT te.* FROM temporal_events te "
                "ORDER BY te.created_at DESC LIMIT ?", (max_events,)
            ).fetchall()
            event_ids = [r["event_id"] for r in events]
            nodes = []
            for r in events:
                nodes.append({
                    "id": r["event_id"],
                    "memory_id": r["memory_id"][:16],
                    "type": r["event_type"],
                    "tier": r.get("tier", ""),
                    "summary": (r.get("summary", "") or "")[:60],
                    "created_at": r.get("created_at", ""),
                })
            edges = []
            if event_ids:
                ph = ",".join("?" * len(event_ids))
                edge_rows = store.db.execute(
                    f"SELECT * FROM temporal_graph_edges "
                    f"WHERE source_event IN ({ph}) AND target_event IN ({ph})",
                    event_ids + event_ids,
                ).fetchall()
                for e in edge_rows:
                    edges.append({
                        "source": e["source_event"],
                        "target": e["target_event"],
                        "relation": e["relation"],
                        "weight": e.get("weight", 1.0),
                    })
            return {"nodes": nodes, "edges": edges, "total_events": len(nodes)}
        except Exception:
            return {"nodes": [], "edges": [], "error": "temporal_events not available"}
