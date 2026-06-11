"""
自修复记忆引擎 — HealerEngine

检测记忆系统中的不一致性并自动修复：
  1. 矛盾信念: 同一实体存在互相冲突的陈述
  2. 冲突状态: state_key 相同但值不同的记忆
  3. 时序异常: 时间戳与宣称时间矛盾
  4. 内容重复: 高度相似的记忆条目

设计哲学:
  一致性检查在写入时触发，也在后台巡检时批量执行。
  轻度不一致自动修复（告警+记录），严重不一致上报等待人工确认。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from mnemos.storage.palimpsest import PalimpsestStore


# ── 辅助 ─────────────────────────────────────────────────


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _gen_id(prefix: str = "inc") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# ── 常量 ─────────────────────────────────────────────────


class InconsistencyType:
    """不一致类型"""
    CONTRADICTORY_BELIEF = "contradictory_belief"
    CONFLICTING_STATE = "conflicting_state"
    TEMPORAL_ANOMALY = "temporal_anomaly"
    DUPLICATE_CONTENT = "duplicate_content"
    MISSING_REFERENCE = "missing_reference"

    _all = {CONTRADICTORY_BELIEF, CONFLICTING_STATE, TEMPORAL_ANOMALY,
            DUPLICATE_CONTENT, MISSING_REFERENCE}


class Severity:
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


# ── 数据模型 ─────────────────────────────────────────────


class Inconsistency:
    """一条不一致记录"""

    def __init__(
        self,
        inconsistency_id: str,
        entry_id_a: str | None,
        entry_id_b: str | None,
        inconsistency_type: str,
        severity: str,
        description: str,
        detail: dict[str, Any] | None = None,
        auto_healed: bool = False,
        suggested_fix: str | None = None,
        created_at: str | None = None,
    ):
        self.inconsistency_id = inconsistency_id
        self.entry_id_a = entry_id_a
        self.entry_id_b = entry_id_b
        self.inconsistency_type = inconsistency_type
        self.severity = severity
        self.description = description
        self.detail = detail or {}
        self.auto_healed = auto_healed
        self.suggested_fix = suggested_fix
        self.created_at = created_at or _now()

    def to_dict(self) -> dict[str, Any]:
        return {
            "inconsistency_id": self.inconsistency_id,
            "entry_id_a": self.entry_id_a,
            "entry_id_b": self.entry_id_b,
            "inconsistency_type": self.inconsistency_type,
            "severity": self.severity,
            "description": self.description,
            "detail": self.detail,
            "auto_healed": self.auto_healed,
            "suggested_fix": self.suggested_fix,
            "created_at": self.created_at,
        }

    def __repr__(self) -> str:
        return (f"<Inconsistency {self.inconsistency_type} "
                f"[{self.severity}] {self.description[:50]}>")


# ── 引擎 ─────────────────────────────────────────────────


class HealerEngine:
    """
    自修复记忆引擎。

    提供两套检测模式：
      - on_write(memory_id, content): 写入时即时检查
      - scan(): 全库巡检（可定时执行）
    """

    def __init__(
        self,
        store: PalimpsestStore,
        auto_heal: bool = True,
    ):
        self._store = store
        self._auto_heal = auto_heal
        self._healers: dict[str, Callable] = {
            InconsistencyType.CONTRADICTORY_BELIEF: self._scan_contradictory_beliefs,
            InconsistencyType.CONFLICTING_STATE: self._scan_conflicting_states,
            InconsistencyType.TEMPORAL_ANOMALY: self._scan_temporal_anomalies,
            InconsistencyType.DUPLICATE_CONTENT: self._scan_duplicate_content,
            InconsistencyType.MISSING_REFERENCE: self._scan_missing_references,
        }
        self._ensure_schema()

    # ── Schema 兼容 ──────────────────────────────────────

    def _ensure_schema(self) -> None:
        """确保 inconsistency_log 表有 suggested_fix 列"""
        conn = self._store.db
        cols = [r[1] for r in conn.execute(
            "PRAGMA table_info(inconsistency_log)"
        ).fetchall()]
        if "auto_healed" not in cols:
            conn.execute(
                "ALTER TABLE inconsistency_log "
                "ADD COLUMN auto_healed INTEGER NOT NULL DEFAULT 0"
            )
        if "dismissed" not in cols:
            conn.execute(
                "ALTER TABLE inconsistency_log "
                "ADD COLUMN dismissed INTEGER NOT NULL DEFAULT 0"
            )
        if "suggested_fix" not in cols:
            conn.execute(
                "ALTER TABLE inconsistency_log "
                "ADD COLUMN suggested_fix TEXT DEFAULT ''"
            )
        if "auto_fix_applied" not in cols:
            conn.execute(
                "ALTER TABLE inconsistency_log "
                "ADD COLUMN auto_fix_applied INTEGER NOT NULL DEFAULT 0"
            )
        conn.commit()

    # ── 写入时检测 ──────────────────────────────────────

    def on_write(self, memory_id: str, tier: str, content: str | None = None) -> list[Inconsistency]:
        """
        在写入一条记忆后，即时检测与其相关的不一致性。

        Returns:
            检测到的 Inconsistency 列表（已持久化到 inconsistency_log）
        """
        findings: list[Inconsistency] = []

        # 1. 检测内容重复
        if content and len(content) > 20:
            dupes = self._check_duplicate_on_write(memory_id, tier, content)
            findings.extend(dupes)

        # 2. 检测矛盾信念（同一 entity 的相关记忆）
        entry = self._store.by_id(memory_id)
        if entry and hasattr(entry, 'entities') and entry.entities:
            for ent in entry.entities:
                label = ent.label if hasattr(ent, 'label') else str(ent)
                conflicts = self._check_belief_conflict(memory_id, tier, label, content or "")
                findings.extend(conflicts)

        # 3. 检测引用完整性
        refs = self._check_references(memory_id, tier)
        findings.extend(refs)

        for inc in findings:
            self._persist(inc)

        return findings

    def _check_duplicate_on_write(
        self, memory_id: str, tier: str, content: str
    ) -> list[Inconsistency]:
        """写入时检测内容重复（模糊匹配前500条）"""
        findings: list[Inconsistency] = []
        table = self._table_name(tier)

        rows = self._store.db.execute(
            f"SELECT entry_id, content FROM {table} "
            f"WHERE is_active=1 AND entry_id!=? AND content!='' "
            f"ORDER BY touched_at DESC LIMIT 500",
            (memory_id,),
        ).fetchall()

        content_lower = content.lower().strip()
        for r in rows:
            existing = (r["content"] or "").lower().strip()
            if not existing or len(existing) < 20:
                continue
            # 简单重叠率检测
            overlap = self._text_overlap(content_lower, existing)
            if overlap > 0.85:
                findings.append(Inconsistency(
                    inconsistency_id=_gen_id("dup"),
                    entry_id_a=memory_id,
                    entry_id_b=r["entry_id"],
                    inconsistency_type=InconsistencyType.DUPLICATE_CONTENT,
                    severity=Severity.WARNING,
                    description=f"内容与 {r['entry_id'][:12]} 高度重复 ({overlap:.0%})",
                    detail={"overlap_ratio": overlap},
                    suggested_fix="考虑合并或删除重复条目",
                ))
                break  # 一次只报一个最相似的
            elif overlap > 0.70:
                findings.append(Inconsistency(
                    inconsistency_id=_gen_id("dup"),
                    entry_id_a=memory_id,
                    entry_id_b=r["entry_id"],
                    inconsistency_type=InconsistencyType.DUPLICATE_CONTENT,
                    severity=Severity.INFO,
                    description=f"内容与 {r['entry_id'][:12]} 部分相似 ({overlap:.0%})",
                    detail={"overlap_ratio": overlap},
                ))
        return findings

    def _check_belief_conflict(
        self, memory_id: str, tier: str, entity_label: str, new_content: str
    ) -> list[Inconsistency]:
        """检测同一实体下的矛盾信念"""
        findings: list[Inconsistency] = []
        table = self._table_name(tier)

        rows = self._store.db.execute(
            f"SELECT entry_id, content, title FROM {table} "
            f"WHERE is_active=1 AND entry_id!=? AND content!='' "
            f"ORDER BY touched_at DESC LIMIT 200",
            (memory_id,),
        ).fetchall()

        for r in rows:
            existing = r["content"] or ""
            if not existing:
                continue
            # 检测明显矛盾的模式
            contradictions = self._detect_contradiction(new_content, existing)
            if contradictions:
                findings.append(Inconsistency(
                    inconsistency_id=_gen_id("contra"),
                    entry_id_a=memory_id,
                    entry_id_b=r["entry_id"],
                    inconsistency_type=InconsistencyType.CONTRADICTORY_BELIEF,
                    severity=Severity.WARNING,
                    description=f"与记忆 {r['entry_id'][:12]} 存在矛盾信念: {contradictions[0]}",
                    detail={
                        "contradictions": contradictions,
                        "entity": entity_label,
                    },
                    suggested_fix="审查并保留更可信的版本",
                ))
        return findings

    def _check_references(self, memory_id: str, tier: str) -> list[Inconsistency]:
        """检测引用完整性：parent_id / related_ids 指向已删除或不存在的条目"""
        findings: list[Inconsistency] = []
        table = self._table_name(tier)

        row = self._store.db.execute(
            f"SELECT entry_id, content FROM {table} WHERE entry_id=?",
            (memory_id,),
        ).fetchone()
        if not row:
            return findings

        content_str = row["content"] or ""
        try:
            import re
            # 查找 [[id]] 格式的引用
            refs = re.findall(r'\[\[([a-f0-9_\-]{8,36})\]\]', content_str)
        except Exception:
            refs = []

        if not refs:
            return findings

        for ref_id in refs:
            exists = False
            for t in ("impressions", "patterns", "principles"):
                r = self._store.db.execute(
                    f"SELECT 1 FROM {t} WHERE entry_id=? AND is_active=1",
                    (ref_id,),
                ).fetchone()
                if r:
                    exists = True
                    break
            if not exists:
                findings.append(Inconsistency(
                    inconsistency_id=_gen_id("ref"),
                    entry_id_a=memory_id,
                    entry_id_b=ref_id,
                    inconsistency_type=InconsistencyType.MISSING_REFERENCE,
                    severity=Severity.WARNING,
                    description=f"条目引用了不存在的记忆 {ref_id[:12]}",
                    detail={"broken_reference": ref_id},
                    suggested_fix="移除该引用或创建指向条目",
                ))
        return findings

    # ── 全库巡检 ────────────────────────────────────────

    def scan(
        self,
        inconsistency_types: list[str] | None = None,
        limit: int = 500,
    ) -> list[Inconsistency]:
        """
        全库巡检，检测所有类型的不一致性。

        Args:
            inconsistency_types: 要检测的类型列表（默认全部）
            limit: 每种类型扫描上限

        Returns:
            所有检测到的 Inconsistency（已持久化）
        """
        types = inconsistency_types or list(InconsistencyType._all)
        all_findings: list[Inconsistency] = []

        for it in types:
            if it in self._healers:
                try:
                    findings = self._healers[it](limit)
                    for inc in findings:
                        self._persist(inc)
                    all_findings.extend(findings)
                except Exception as e:
                    # 单种类型失败不影响其他类型
                    all_findings.append(Inconsistency(
                        inconsistency_id=_gen_id("scan_err"),
                        entry_id_a=None,
                        entry_id_b=None,
                        inconsistency_type=it,
                        severity=Severity.INFO,
                        description=f"巡检 {it} 时出错: {e}",
                        detail={"error": str(e)},
                    ))
        return all_findings

    def _scan_contradictory_beliefs(self, limit: int = 500) -> list[Inconsistency]:
        """扫描矛盾信念：相同 content 前缀+相反表述"""
        findings: list[Inconsistency] = []
        for table in ("impressions", "patterns", "principles"):
            rows = self._store.db.execute(
                f"SELECT entry_id, content FROM {table} "
                f"WHERE is_active=1 AND content!='' "
                f"ORDER BY touched_at DESC LIMIT ?",
                (limit,),
            ).fetchall()

            # 按长度分组比较
            for i, r1 in enumerate(rows):
                c1 = (r1["content"] or "").strip().lower()
                if not c1 or len(c1) < 30:
                    continue
                for r2 in rows[i + 1:]:
                    c2 = (r2["content"] or "").strip().lower()
                    if not c2 or len(c2) < 30:
                        continue
                    # 检测否定词对
                    contradictions = self._detect_contradiction(c1, c2)
                    if contradictions:
                        findings.append(Inconsistency(
                            inconsistency_id=_gen_id("contra"),
                            entry_id_a=r1["entry_id"],
                            entry_id_b=r2["entry_id"],
                            inconsistency_type=InconsistencyType.CONTRADICTORY_BELIEF,
                            severity=Severity.WARNING,
                            description=f"矛盾: {contradictions[0]}",
                            detail={"contradictions": contradictions},
                            suggested_fix="审查矛盾并更新为一致版本",
                        ))
                        if len(findings) >= limit:
                            return findings
        return findings

    def _scan_conflicting_states(self, limit: int = 500) -> list[Inconsistency]:
        """扫描冲突状态：相同 state_key 但不同值"""
        findings: list[Inconsistency] = []
        for table in ("impressions", "patterns", "principles"):
            # 找到所有有 state_key 的条目
            rows = self._store.db.execute(
                f"SELECT entry_id, state_key, content FROM {table} "
                f"WHERE is_active=1 AND state_key!='' AND state_key IS NOT NULL "
                f"ORDER BY state_key, touched_at DESC LIMIT ?",
                (limit,),
            ).fetchall()

            state_groups: dict[str, list[dict[str, Any]]] = {}
            for r in rows:
                sk = r["state_key"]
                if sk not in state_groups:
                    state_groups[sk] = []
                state_groups[sk].append(dict(r))

            for sk, group in state_groups.items():
                if len(group) < 2:
                    continue
                # 同一 state_key 有不同值 → 冲突
                values = set()
                for g in group:
                    val = (g["content"] or "").strip()[:100]
                    if val:
                        values.add(val)
                if len(values) > 1:
                    findings.append(Inconsistency(
                        inconsistency_id=_gen_id("state"),
                        entry_id_a=group[0]["entry_id"],
                        entry_id_b=group[1]["entry_id"],
                        inconsistency_type=InconsistencyType.CONFLICTING_STATE,
                        severity=Severity.WARNING,
                        description=f"state_key '{sk}' 存在 {len(values)} 个不同值",
                        detail={
                            "state_key": sk,
                            "values": list(values),
                            "entries": [g["entry_id"] for g in group],
                        },
                        suggested_fix=f"统一 state_key '{sk}' 的值或使用不同 key",
                    ))
                    if len(findings) >= limit:
                        return findings
        return findings

    def _scan_temporal_anomalies(self, limit: int = 500) -> list[Inconsistency]:
        """扫描时序异常：last_accessed_at 早于 created_at"""
        findings: list[Inconsistency] = []
        for table in ("impressions", "patterns", "principles"):
            rows = self._store.db.execute(
                f"SELECT entry_id, created_at, touched_at FROM {table} "
                f"WHERE is_active=1 AND created_at IS NOT NULL "
                f"AND touched_at IS NOT NULL LIMIT ?",
                (limit,),
            ).fetchall()

            for r in rows:
                try:
                    created = datetime.fromisoformat(r["created_at"])
                    touched = datetime.fromisoformat(r["touched_at"])
                    if touched < created:
                        diff = (created - touched).total_seconds()
                        findings.append(Inconsistency(
                            inconsistency_id=_gen_id("temp"),
                            entry_id_a=r["entry_id"],
                            entry_id_b=None,
                            inconsistency_type=InconsistencyType.TEMPORAL_ANOMALY,
                            severity=Severity.INFO if diff < 3600 else Severity.WARNING,
                            description=f"last_accessed_at 早于 created_at {diff:.0f}s",
                            detail={
                                "created_at": r["created_at"],
                                "touched_at": r["touched_at"],
                                "diff_seconds": diff,
                            },
                            suggested_fix="更新 touched_at 为 created_at 的时间",
                        ))
                        if len(findings) >= limit:
                            return findings
                except (ValueError, TypeError):
                    continue
        return findings

    def _scan_duplicate_content(self, limit: int = 500) -> list[Inconsistency]:
        """扫描内容重复（全库级别）"""
        findings: list[Inconsistency] = []
        for table in ("impressions", "patterns", "principles"):
            rows = self._store.db.execute(
                f"SELECT entry_id, content FROM {table} "
                f"WHERE is_active=1 AND content!='' "
                f"ORDER BY length(content) DESC LIMIT ?",
                (limit,),
            ).fetchall()

            for i, r1 in enumerate(rows):
                c1 = (r1["content"] or "").lower().strip()
                if not c1 or len(c1) < 30:
                    continue
                for r2 in rows[i + 1:]:
                    c2 = (r2["content"] or "").lower().strip()
                    if not c2 or len(c2) < 30:
                        continue
                    overlap = self._text_overlap(c1, c2)
                    if overlap > 0.85:
                        findings.append(Inconsistency(
                            inconsistency_id=_gen_id("dup"),
                            entry_id_a=r1["entry_id"],
                            entry_id_b=r2["entry_id"],
                            inconsistency_type=InconsistencyType.DUPLICATE_CONTENT,
                            severity=Severity.WARNING,
                            description=f"高重复 ({overlap:.0%})",
                            detail={"overlap_ratio": overlap},
                            suggested_fix="合并或删除较旧/不准确的条目",
                        ))
                        if len(findings) >= limit:
                            return findings
        return findings

    def _scan_missing_references(self, limit: int = 500) -> list[Inconsistency]:
        """扫描引用完整性"""
        findings: list[Inconsistency] = []
        import re

        for table in ("impressions", "patterns", "principles"):
            rows = self._store.db.execute(
                f"SELECT entry_id, content FROM {table} "
                f"WHERE is_active=1 AND content!='' "
                f"LIMIT ?", (limit,),
            ).fetchall()

            for r in rows:
                refs = re.findall(r'\[\[([a-f0-9_\-]{8,36})\]\]', r["content"] or "")
                if not refs:
                    continue
                for ref_id in refs:
                    exists = False
                    for t in ("impressions", "patterns", "principles"):
                        rr = self._store.db.execute(
                            f"SELECT 1 FROM {t} WHERE entry_id=? AND is_active=1",
                            (ref_id,),
                        ).fetchone()
                        if rr:
                            exists = True
                            break
                    if not exists:
                        findings.append(Inconsistency(
                            inconsistency_id=_gen_id("ref"),
                            entry_id_a=r["entry_id"],
                            entry_id_b=ref_id,
                            inconsistency_type=InconsistencyType.MISSING_REFERENCE,
                            severity=Severity.WARNING,
                            description=f"引用 {ref_id[:12]} 不存在",
                            detail={"broken_reference": ref_id, "source_table": table},
                            suggested_fix="移除该引用或创建指向条目",
                        ))
                        if len(findings) >= limit:
                            return findings
        return findings

    # ── 自动修复 ────────────────────────────────────────

    def auto_heal(self, inconsistency: Inconsistency) -> bool:
        """
        尝试自动修复一个已知的不一致性。

        Returns:
            True 如果修复成功
        """
        if not self._auto_heal:
            return False

        itype = inconsistency.inconsistency_type

        if itype == InconsistencyType.TEMPORAL_ANOMALY:
            # 修复时序：将 touched_at 设为 created_at
            if inconsistency.entry_id_a:
                for table in ("impressions", "patterns", "principles"):
                    self._store.db.execute(
                        f"UPDATE {table} SET touched_at=created_at WHERE entry_id=?",
                        (inconsistency.entry_id_a,),
                    )
                self._store.db.commit()
                self._mark_healed(inconsistency.inconsistency_id)
                return True

        elif itype == InconsistencyType.MISSING_REFERENCE:
            # 修复方式：标记为已处理（无法自动创建目标条目）
            self._mark_healed(inconsistency.inconsistency_id)
            return True

        elif itype == InconsistencyType.DUPLICATE_CONTENT:
            # 自动合并：停用较旧的条目
            if inconsistency.entry_id_a and inconsistency.entry_id_b:
                # 比较 created_at，保留较新的
                a_row = None
                b_row = None
                for table in ("impressions", "patterns", "principles"):
                    a_row = self._store.db.execute(
                        f"SELECT created_at, entry_id FROM {table} WHERE entry_id=?",
                        (inconsistency.entry_id_a,),
                    ).fetchone()
                    b_row = self._store.db.execute(
                        f"SELECT created_at, entry_id FROM {table} WHERE entry_id=?",
                        (inconsistency.entry_id_b,),
                    ).fetchone()
                    if a_row and b_row:
                        break

                if a_row and b_row:
                    keep = inconsistency.entry_id_a
                    remove = inconsistency.entry_id_b
                    if b_row["created_at"] > a_row["created_at"]:
                        keep, remove = remove, keep
                    for table in ("impressions", "patterns", "principles"):
                        self._store.db.execute(
                            f"UPDATE {table} SET is_active=0 WHERE entry_id=?",
                            (remove,),
                        )
                    self._store.db.commit()
                    self._mark_healed(inconsistency.inconsistency_id)
                    return True

        return False

    def heal_all(self) -> dict[str, Any]:
        """
        尝试修复所有未修复的不一致性。

        Returns:
            {total: int, healed: int, failed: list[str]}
        """
        rows = self._store.db.execute(
            "SELECT * FROM inconsistency_log "
            "WHERE auto_healed=0 AND dismissed=0"
        ).fetchall()

        total = len(rows)
        healed = 0
        failed: list[str] = []

        for r in rows:
            inc = self._row_to_inconsistency(dict(r))
            if self.auto_heal(inc):
                healed += 1
            else:
                failed.append(inc.inconsistency_id)

        return {
            "total": total,
            "healed": healed,
            "failed": failed,
        }

    def _mark_healed(self, inconsistency_id: str) -> None:
        self._store.db.execute(
            "UPDATE inconsistency_log SET auto_healed=1, auto_fix_applied=1 "
            "WHERE issue_id=?",
            (inconsistency_id,),
        )
        self._store.db.commit()

    # ── 查询 ──────────────────────────────────────────────

    def list_inconsistencies(
        self,
        severity: str | None = None,
        inconsistency_type: str | None = None,
        include_healed: bool = False,
        limit: int = 50,
    ) -> list[Inconsistency]:
        """查询不一致记录"""
        conditions: list[str] = []
        params: list[Any] = []

        if severity:
            conditions.append("severity=?")
            params.append(severity)
        if inconsistency_type:
            conditions.append("issue_type=?")
            params.append(inconsistency_type)
        if not include_healed:
            conditions.append("auto_healed=0")
        conditions.append("dismissed=0")

        where = " AND ".join(conditions) if conditions else "1=1"

        rows = self._store.db.execute(
            f"SELECT * FROM inconsistency_log "
            f"WHERE {where} ORDER BY created_at DESC LIMIT ?",
            params + [limit],
        ).fetchall()

        return [self._row_to_inconsistency(dict(r)) for r in rows]

    def stats(self) -> dict[str, Any]:
        """不一致性统计"""
        total = self._store.db.execute(
            "SELECT COUNT(*) FROM inconsistency_log"
        ).fetchone()[0]

        by_type = self._store.db.execute(
            "SELECT issue_type, COUNT(*) as cnt "
            "FROM inconsistency_log GROUP BY issue_type"
        ).fetchall()

        by_severity = self._store.db.execute(
            "SELECT severity, COUNT(*) as cnt "
            "FROM inconsistency_log GROUP BY severity"
        ).fetchall()

        healed = self._store.db.execute(
            "SELECT COUNT(*) FROM inconsistency_log WHERE auto_healed=1"
        ).fetchone()[0]

        return {
            "total": total,
            "healed": healed,
            "unhealed": total - healed,
            "by_type": {r["issue_type"]: r["cnt"] for r in by_type},
            "by_severity": {r["severity"]: r["cnt"] for r in by_severity},
        }

    # ── dismiss ───────────────────────────────────────────

    def dismiss(self, inconsistency_id: str) -> bool:
        """标记一条不一致记录为已忽略"""
        cur = self._store.db.execute(
            "UPDATE inconsistency_log SET dismissed=1 WHERE issue_id=?",
            (inconsistency_id,),
        )
        self._store.db.commit()
        return cur.rowcount > 0

    # ── 内部工具 ─────────────────────────────────────────

    def _detect_contradiction(self, text_a: str, text_b: str) -> list[str]:
        """检测两段文本之间的矛盾表述"""
        contradictions: list[str] = []

        # 否定词对：同一核心内容，一个肯定一个否定
        negation_pairs = [
            ("是", "不是"), ("是", "不是"), ("是", "不是"),
            ("喜欢", "不喜欢"), ("喜欢", "讨厌"),
            ("支持", "反对"), ("支持", "不支持"),
            ("有", "没有"), ("有", "无"),
            ("存在", "不存在"),
            ("在", "不在"),
            ("记得", "不记得"),
            ("能", "不能"),
            ("可以", "不可以"),
            ("会", "不会"),
            ("要", "不要"),
            ("true", "false"),
            ("yes", "no"),
            ("是", "否"),
            ("是", "非"),
        ]

        # 去除 "不" 前缀提取核心词
        def core_verb(t: str) -> str:
            for prefix in ["不", "没", "无", "非"]:
                if t.startswith(prefix) and len(t) > 1:
                    return t[len(prefix):]
            return t

        words_a = set(text_a.split())
        words_b = set(text_b.split())

        # 检查否定词对
        for pos, neg in negation_pairs:
            a_has_pos = pos in text_a
            b_has_pos = pos in text_b
            a_has_neg = neg in text_a
            b_has_neg = neg in text_b

            if (a_has_pos and b_has_neg) or (a_has_neg and b_has_pos):
                contradictions.append(f"'{pos}' vs '{neg}'")

        return contradictions

    def _text_overlap(self, a: str, b: str) -> float:
        """计算两段文本的词集重叠率 (Jaccard)"""
        words_a = set(a.split())
        words_b = set(b.split())
        if not words_a or not words_b:
            return 0.0
        intersection = words_a & words_b
        return len(intersection) / len(words_a | words_b)

    def _table_name(self, tier: str) -> str:
        mapping = {
            "core": "impressions",
            "ephemeral": "impressions",
            "working": "impressions",
            "longterm": "patterns",
            "archetype": "principles",
        }
        return mapping.get(tier, "impressions")

    def _persist(self, inc: Inconsistency) -> None:
        """持久化一条不一致记录到 inconsistency_log"""
        self._store.db.execute(
            """INSERT OR IGNORE INTO inconsistency_log
               (issue_id, memory_id_a, memory_id_b,
                issue_type, severity, description,
                metadata, auto_healed, suggested_fix,
                detected_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                inc.inconsistency_id,
                inc.entry_id_a,
                inc.entry_id_b,
                inc.inconsistency_type,
                inc.severity,
                inc.description,
                json.dumps(inc.detail, ensure_ascii=False),
                1 if inc.auto_healed else 0,
                inc.suggested_fix or "",
                inc.created_at,
            ),
        )
        self._store.db.commit()

    def _row_to_inconsistency(self, row: dict[str, Any]) -> Inconsistency:
        return Inconsistency(
            inconsistency_id=row["issue_id"],
            entry_id_a=row.get("memory_id_a"),
            entry_id_b=row.get("memory_id_b"),
            inconsistency_type=row["issue_type"],
            severity=row.get("severity", Severity.WARNING),
            description=row.get("description", ""),
            detail=json.loads(row.get("metadata", "{}")),
            auto_healed=bool(row.get("auto_healed", 0)),
            suggested_fix=row.get("suggested_fix"),
            created_at=row.get("detected_at"),
        )
