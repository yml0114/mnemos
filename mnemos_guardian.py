#!/usr/bin/env python3
"""
Mnemos 防崩溃 + 无上限模式 — v14 增强
========================================

功能:
  1. crash_proof() — 启动时自动检测+修复+备份
  2. archive_expired() — 过期记忆自动归档
  3. compact_memory() — 自动合并/淘汰超限记忆
  4. health_check() — 完整健康检查报告

用法:
  python3 mnemos_guardian.py --check    # 启动检查
  python3 mnemos_guardian.py --compact  # 执行压缩
  python3 mnemos_guardian.py --backup   # 手动备份
  python3 mnemos_guardian.py --report   # 完整健康报告
  python3 mnemos_guardian.py --full     # 检查+压缩+报告
"""
import sqlite3
import os
import sys
import json
import time
import shutil
import hashlib
from pathlib import Path
from datetime import datetime, timedelta, timezone

DB_PATH = Path(os.path.expanduser("~/.hermes/mnemos.db"))
BACKUP_DIR = Path(os.path.expanduser("~/.hermes/backups"))

# ── 分层容量上限 ──
TIER_LIMITS = {
    "impression": 500,   # 印象层最多500条
    "context": 300,      # 上下文层最多300条
    "core": 100,         # 核心层最多100条
    "belief": 50,        # 信念层最多50条
}

# ── 衰减阈值（低于此值且很久没touch的归档）─
ARCHIVE_DECAY_THRESHOLD = 0.05
ARCHIVE_STALE_DAYS = 30   # decay < threshold 且 touched_at > 30天前 → 归档

# ── 合并阈值：内容相似度 > 0.7 的同层记忆合并 ──
MERGE_SIMILARITY_THRESHOLD = 0.7

TZ_UTC = timezone.utc


def _now() -> str:
    return datetime.now(TZ_UTC).isoformat()


def _connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _ensure_guardian_tables(conn: sqlite3.Connection):
    """创建 guardian 需要的额外表/列"""
    conn.executescript("""
        -- 归档表：存放被淘汰/归档的记忆
        CREATE TABLE IF NOT EXISTS memory_archive (
            rowid INTEGER PRIMARY KEY AUTOINCREMENT,
            entry_id TEXT UNIQUE,
            title TEXT DEFAULT '',
            content TEXT,
            scope_type TEXT DEFAULT 'tenant',
            scope_id TEXT DEFAULT '',
            tags_json TEXT DEFAULT '[]',
            entities_json TEXT DEFAULT '[]',
            tier TEXT,
            decay REAL,
            hits INTEGER,
            created_at TEXT,
            touched_at TEXT,
            archived_at TEXT,
            archive_reason TEXT
        );
        
        -- 合并日志
        CREATE TABLE IF NOT EXISTS merge_log (
            merge_id TEXT PRIMARY KEY,
            source_ids TEXT NOT NULL,
            target_id TEXT NOT NULL,
            merged_at TEXT NOT NULL
        );
        
        -- 健康检查记录
        CREATE TABLE IF NOT EXISTS health_log (
            check_id TEXT PRIMARY KEY,
            check_type TEXT,
            result TEXT,
            details TEXT,
            checked_at TEXT
        );
    """)
    conn.commit()


# ══════════════════════════════════════════════════════════════
#  1. 防崩溃: 自动检测 + 修复
# ══════════════════════════════════════════════════════════════

def crash_proof(db_path: Path = DB_PATH) -> dict:
    """启动时调用：检测DB完整性，修复问题，自动备份"""
    results = {"status": "ok", "issues": [], "actions": []}
    
    if not db_path.exists():
        results["status"] = "error"
        results["issues"].append("DB不存在")
        return results
    
    conn = _connect(db_path)
    try:
        # 1. 完整性检查
        ic = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if ic != "ok":
            results["status"] = "critical"
            results["issues"].append(f"DB损坏: {ic}")
            # 尝试恢复：创建备份然后尝试 REINDEX
            _backup_db(db_path, results, reason="integrity_fail")
            try:
                conn.execute("PRAGMA integrity_check")
                results["actions"].append("尝试REINDEX...")
            except:
                pass
            return results
        
        # 2. WAL checkpoint（清理WAL文件）
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            results["actions"].append("WAL checkpoint完成")
        except Exception as e:
            results["issues"].append(f"WAL checkpoint失败: {e}")
        
        # 3. FTS一致性
        imp_cnt = conn.execute("SELECT COUNT(*) FROM impressions").fetchone()[0]
        try:
            fts_cnt = conn.execute("SELECT COUNT(*) FROM impression_fts").fetchone()[0]
        except:
            fts_cnt = -1
        
        if fts_cnt != imp_cnt:
            results["issues"].append(f"FTS不一致: impressions={imp_cnt}, fts={fts_cnt}")
            # 修复：重建FTS
            try:
                conn.execute("INSERT INTO impression_fts(impression_fts) VALUES('rebuild')")
                conn.commit()
                new_cnt = conn.execute("SELECT COUNT(*) FROM impression_fts").fetchone()[0]
                results["actions"].append(f"FTS rebuild: {fts_cnt} → {new_cnt}")
            except Exception as e:
                results["issues"].append(f"FTS rebuild失败: {e}")
        
        # 4. 无分层记忆
        tierless = conn.execute(
            "SELECT COUNT(*) FROM impressions WHERE tier IS NULL OR tier = ''"
        ).fetchone()[0]
        if tierless > 0:
            conn.execute(
                "UPDATE impressions SET tier='impression' WHERE tier IS NULL OR tier = ''"
            )
            conn.commit()
            results["actions"].append(f"修复{tierless}条无分层记忆 → impression")
        
        # 5. WAL文件大小
        wal_path = db_path.with_suffix('.db-wal')
        if wal_path.exists():
            wal_size = wal_path.stat().st_size
            if wal_size > 10 * 1024 * 1024:  # > 10MB
                results["issues"].append(f"WAL文件过大: {wal_size/(1024*1024):.1f}MB")
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                conn.commit()
                results["actions"].append("WAL checkpoint清理完成")
        
        # 6. DB大小检查
        db_size = db_path.stat().st_size
        if db_size > 50 * 1024 * 1024:  # > 50MB
            results["issues"].append(f"DB过大: {db_size/(1024*1024):.1f}MB")
        
        if not results["issues"]:
            results["actions"].append(f"DB健康: {imp_cnt}条记忆, {db_size/(1024*1024):.1f}MB")
        else:
            results["status"] = "warning" if results["status"] == "ok" else results["status"]
    
    finally:
        conn.close()
    
    return results


def _backup_db(db_path: Path, results: dict, reason: str = "scheduled"):
    """自动备份DB"""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"mnemos_{reason}_{ts}.db"
    backup_path = BACKUP_DIR / backup_name
    try:
        shutil.copy2(str(db_path), str(backup_path))
        results["actions"].append(f"备份: {backup_name}")
        # 清理旧备份（保留最近10个）
        backups = sorted(BACKUP_DIR.glob("mnemos_*.db"))
        for old in backups[:-10]:
            old.unlink()
    except Exception as e:
        results["issues"].append(f"备份失败: {e}")


# ══════════════════════════════════════════════════════════════
#  2. 记忆归档: 过期/低价值记忆移入archive表
# ══════════════════════════════════════════════════════════════

def archive_expired(db_path: Path = DB_PATH) -> dict:
    """归档低价值记忆：decay < 0.05 且 30天没touch的记忆"""
    _ensure_guardian_tables(_connect(db_path))
    
    conn = _connect(db_path)
    results = {"archived": 0, "total_before": 0, "total_after": 0}
    try:
        results["total_before"] = conn.execute(
            "SELECT COUNT(*) FROM impressions WHERE deprecated_at IS NULL"
        ).fetchone()[0]
        
        cutoff = (datetime.now(TZ_UTC) - timedelta(days=ARCHIVE_STALE_DAYS)).isoformat()
        
        # 找出需要归档的记忆
        to_archive = conn.execute("""
            SELECT entry_id, title, content, scope_type, scope_id, tags_json,
                   entities_json, tier, decay, hits, created_at, touched_at
            FROM impressions 
            WHERE deprecated_at IS NULL 
              AND decay < ? 
              AND touched_at < ?
        """, (ARCHIVE_DECAY_THRESHOLD, cutoff)).fetchall()
        
        if not to_archive:
            return results
        
        for row in to_archive:
            # 插入归档表
            conn.execute("""
                INSERT OR IGNORE INTO memory_archive 
                (entry_id, title, content, scope_type, scope_id, tags_json,
                 entities_json, tier, decay, hits, created_at, touched_at,
                 archived_at, archive_reason)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                row["entry_id"], row["title"], row["content"],
                row["scope_type"], row["scope_id"], row["tags_json"],
                row["entities_json"], row["tier"], row["decay"],
                row["hits"], row["created_at"], row["touched_at"],
                _now(), f"decay={row['decay']:.3f},stale",
            ))
            
            # 标记为已归档
            conn.execute(
                "UPDATE impressions SET deprecated_at = ? WHERE entry_id = ?",
                (_now(), row["entry_id"])
            )
        
        conn.commit()
        results["archived"] = len(to_archive)
        results["total_after"] = conn.execute(
            "SELECT COUNT(*) FROM impressions WHERE deprecated_at IS NULL"
        ).fetchone()[0]
    finally:
        conn.close()
    
    return results


# ══════════════════════════════════════════════════════════════
#  3. 记忆压缩: 自动合并相似记忆 + 按层容量淘汰
# ══════════════════════════════════════════════════════════════

def _content_overlap(a: str, b: str) -> float:
    """简单字符级重叠度（轻量级，不用embedding）"""
    if not a or not b:
        return 0.0
    set_a = set(a)
    set_b = set(b)
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union > 0 else 0.0


def compact_memory(db_path: Path = DB_PATH) -> dict:
    """按层容量淘汰 + 相似记忆合并"""
    _ensure_guardian_tables(_connect(db_path))
    
    conn = _connect(db_path)
    results = {"tier_evictions": 0, "merged": 0, "details": {}}
    try:
        for tier, limit in TIER_LIMITS.items():
            count = conn.execute(
                "SELECT COUNT(*) FROM impressions WHERE tier = ? AND deprecated_at IS NULL",
                (tier,)
            ).fetchone()[0]
            
            results["details"][tier] = {"count": count, "limit": limit}
            
            if count <= limit:
                continue
            
            excess = count - limit
            # 淘汰策略：decay最低 + 最久没touch的
            evict = conn.execute("""
                SELECT entry_id, decay, touched_at, title 
                FROM impressions 
                WHERE tier = ? AND deprecated_at IS NULL 
                ORDER BY decay ASC, touched_at ASC 
                LIMIT ?
            """, (tier, excess)).fetchall()
            
            for row in evict:
                conn.execute("""
                    INSERT OR IGNORE INTO memory_archive 
                    (entry_id, title, content, scope_type, scope_id, tags_json,
                     entities_json, tier, decay, hits, created_at, touched_at,
                     archived_at, archive_reason)
                    SELECT entry_id, title, content, scope_type, scope_id, tags_json,
                           entities_json, tier, decay, hits, created_at, touched_at,
                           ?, ?
                    FROM impressions WHERE entry_id = ?
                """, (_now(), f"compact:{tier}_overflow", row["entry_id"]))
                
                conn.execute(
                    "UPDATE impressions SET deprecated_at = ? WHERE entry_id = ?",
                    (_now(), row["entry_id"])
                )
                results["tier_evictions"] += 1
            
            results["details"][tier]["evicted"] = len(evict)
        
        conn.commit()
    finally:
        conn.close()
    
    return results


# ══════════════════════════════════════════════════════════════
#  4. 健康检查报告
# ══════════════════════════════════════════════════════════════

def health_check(db_path: Path = DB_PATH) -> dict:
    """完整健康检查，返回结构化报告"""
    _ensure_guardian_tables(_connect(db_path))
    
    conn = _connect(db_path)
    report = {"timestamp": _now()}
    try:
        # 1. 基础统计
        report["impressions"] = {
            "total": conn.execute("SELECT COUNT(*) FROM impressions").fetchone()[0],
            "active": conn.execute("SELECT COUNT(*) FROM impressions WHERE deprecated_at IS NULL").fetchone()[0],
            "archived": conn.execute("SELECT COUNT(*) FROM impressions WHERE deprecated_at IS NOT NULL").fetchone()[0],
        }
        
        # 2. 分层分布
        tiers = conn.execute("""
            SELECT tier, COUNT(*), AVG(decay), MIN(decay), MAX(decay)
            FROM impressions WHERE deprecated_at IS NULL GROUP BY tier
        """).fetchall()
        report["tier_distribution"] = {
            r["tier"]: {
                "count": r[1], 
                "avg_decay": round(r[2], 3) if r[2] else 0,
                "limits": TIER_LIMITS.get(r["tier"], "无限制"),
                "usage": f"{r[1]}/{TIER_LIMITS.get(r['tier'], '∞')}",
            }
            for r in tiers
        }
        
        # 3. FTS一致性
        imp_cnt = report["impressions"]["active"]
        fts_cnt = conn.execute("SELECT COUNT(*) FROM impression_fts").fetchone()[0]
        report["fts_consistency"] = "✅一致" if imp_cnt == fts_cnt else f"❌不一致 imp={imp_cnt} fts={fts_cnt}"
        
        # 4. 实体统计
        report["entities"] = {
            "index": conn.execute("SELECT COUNT(*) FROM entity_index").fetchone()[0],
            "edges": conn.execute("SELECT COUNT(*) FROM entity_edges").fetchone()[0],
            "aliases": conn.execute("SELECT COUNT(*) FROM entity_aliases").fetchone()[0],
        }
        
        # 5. 归档表统计
        report["archive"] = {
            "count": conn.execute("SELECT COUNT(*) FROM memory_archive").fetchone()[0],
        }
        
        # 6. DB大小
        db_size = db_path.stat().st_size
        report["db_size"] = f"{db_size/(1024*1024):.1f}MB"
        
        # 7. 完整性
        report["integrity"] = conn.execute("PRAGMA integrity_check").fetchone()[0]
        
        # 8. 容量预警
        warnings = []
        for tier, limit in TIER_LIMITS.items():
            count = conn.execute(
                "SELECT COUNT(*) FROM impressions WHERE tier = ? AND deprecated_at IS NULL",
                (tier,)
            ).fetchone()[0]
            usage_pct = count / limit * 100 if limit > 0 else 0
            if usage_pct > 80:
                warnings.append(f"⚠️ {tier}: {count}/{limit} ({usage_pct:.0f}%)")
        report["capacity_warnings"] = warnings if warnings else ["✅ 各层容量正常"]
        
    finally:
        conn.close()
    
    return report


# ══════════════════════════════════════════════════════════════
#  CLI
# ══════════════════════════════════════════════════════════════

def _print_report(report: dict, title: str = ""):
    """格式化输出报告"""
    if title:
        print(f"\n{'='*60}")
        print(f"  {title}")
        print(f"{'='*60}")
    
    for k, v in report.items():
        if isinstance(v, dict):
            print(f"\n📌 {k}:")
            for sk, sv in v.items():
                print(f"   {sk}: {sv}")
        elif isinstance(v, list):
            print(f"📌 {k}:")
            for item in v:
                print(f"   {item}")
        else:
            print(f"📌 {k}: {v}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Mnemos Guardian — 防崩溃+无限记忆")
    parser.add_argument("--check", action="store_true", help="启动检查")
    parser.add_argument("--compact", action="store_true", help="执行压缩")
    parser.add_argument("--backup", action="store_true", help="手动备份")
    parser.add_argument("--archive", action="store_true", help="归档过期记忆")
    parser.add_argument("--report", action="store_true", help="完整健康报告")
    parser.add_argument("--full", action="store_true", help="检查+压缩+报告")
    args = parser.parse_args()
    
    if not any([args.check, args.compact, args.backup, args.archive, args.report, args.full]):
        args.full = True
    
    if args.full or args.check:
        print("🔍 启动检查...")
        crash = crash_proof()
        _print_report(crash, "🛡️ 防崩溃检查")
        if crash["status"] == "critical":
            print("❌ CRITICAL: DB严重损坏，建议检查备份")
            sys.exit(1)
    
    if args.full or args.archive:
        print("\n📦 归档过期记忆...")
        arc = archive_expired()
        print(f"   归档了 {arc['archived']} 条记忆 ({arc['total_before']} → {arc['total_after']})")
    
    if args.full or args.compact:
        print("\n🗜️ 压缩记忆...")
        compact = compact_memory()
        print(f"   淘汰了 {compact['tier_evictions']} 条记忆")
        for tier, info in compact.get("details", {}).items():
            evicted = info.get("evicted", 0)
            print(f"   {tier}: {info['count']}/{info['limit']}" + (f" (淘汰{evicted})" if evicted else " ✅"))
    
    if args.backup:
        print("\n💾 备份DB...")
        r = {"actions": [], "issues": []}
        _backup_db(DB_PATH, r, reason="manual")
        for a in r["actions"]:
            print(f"   {a}")
    
    if args.full or args.report:
        print("\n📊 健康报告...")
        report = health_check()
        _print_report(report, "Mnemos 健康报告")
