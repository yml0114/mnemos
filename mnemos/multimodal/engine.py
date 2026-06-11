"""
多模态记忆引擎 — MultimodalEngine

为记忆系统提供媒体附件（图片、音频、视频、文件、链接）的存储、
检索和向量嵌入管理能力。

设计哲学:
  媒体是记忆的感官延伸——文字记录事件，媒体记录事件的感官细节。
  每个媒体附件关联一条记忆（memory_id），附带类型、摘要和元数据。
  向量嵌入用于跨模态语义检索（以图搜图、以文搜图）。

底层存储:
  PalimpsestStore 的 media_attachments + media_embeddings 表
"""

from __future__ import annotations

import json
import mimetypes
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from pydantic import BaseModel, Field

from mnemos.storage.palimpsest import PalimpsestStore


# ── 数据模型 ─────────────────────────────────────────────


class MediaType(str):
    """媒体类型枚举（匹配 media_attachments 表 CHECK 约束）"""

    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    FILE = "file"
    LINK = "link"

    _valid = {IMAGE, AUDIO, VIDEO, FILE, LINK}

    def __new__(cls, value: str) -> str:
        if value not in cls._valid:
            raise ValueError(f"Invalid MediaType: {value!r}; choose from {cls._valid}")
        return str.__new__(cls, value)


class MediaAttachment(BaseModel):
    """单个媒体附件的数据模型"""

    media_id: str
    memory_id: str
    media_type: str = ""         # image / audio / video / file / link
    mime_type: str = ""
    filename: str = ""
    storage_uri: str = ""        # 本地路径或远程 URL
    byte_size: int = 0
    summary: str = ""            # 摘要文本（存于 metadata，引擎层读写）
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = ""


# ── 辅助 ─────────────────────────────────────────────────


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _guess_mime(path_or_url: str) -> str:
    """从文件路径或 URL 推断 MIME 类型"""
    mime, _ = mimetypes.guess_type(path_or_url)
    return mime or ""


def _filename_from(path_or_url: str) -> str:
    """从路径或 URL 提取文件名"""
    return Path(path_or_url).name


# ── 引擎 ─────────────────────────────────────────────────


class MultimodalEngine:
    """
    多模态记忆引擎 — 媒体附件的存取与检索。

    使用示例:
        from mnemos.storage.palimpsest import PalimpsestStore
        from mnemos.multimodal.engine import MultimodalEngine, MediaType

        store = PalimpsestStore("memory.db")
        store.connect()
        engine = MultimodalEngine(store)

        # 附加图片到一条记忆
        aid = engine.attach_media(
            memory_id="abc123",
            media_type=MediaType.IMAGE,
            file_path="/tmp/photo.jpg",
            summary="用户提供的建筑照片",
            metadata={"width": 1920, "height": 1080},
        )

        # 查询该记忆的所有附件
        attachments = engine.get_attachments("abc123")
    """

    # ── 初始化 ──────────────────────────────────────────

    def __init__(self, store: PalimpsestStore) -> None:
        self._store = store
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        """
        确保 media_attachments 表有 summary 列（向后兼容迁移）。
        summary 以独立列存储，支持后续建 FTS 索引。
        """
        conn = self._store.db
        cols = [row[1] for row in conn.execute("PRAGMA table_info(media_attachments)").fetchall()]
        if "summary" not in cols:
            conn.execute(
                "ALTER TABLE media_attachments ADD COLUMN summary TEXT NOT NULL DEFAULT ''"
            )
            conn.commit()

    # ── 写入 ──────────────────────────────────────────

    def attach_media(
        self,
        memory_id: str,
        media_type: str,
        file_path: str | None = None,
        url: str | None = None,
        summary: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """
        为一条记忆附加媒体文件。

        Args:
            memory_id:  关联的记忆 ID
            media_type: 媒体类型 (image / audio / video / file / link)
            file_path:  本地文件路径（与 url 二选一）
            url:        远程 URL（与 file_path 二选一）
            summary:    媒体摘要描述
            metadata:   附加元数据字典

        Returns:
            attachment_id — 新创建的媒体附件 ID

        Raises:
            ValueError: file_path 和 url 同时为 None 或同时提供
        """
        if not file_path and not url:
            raise ValueError("Either file_path or url must be provided")
        if file_path and url:
            raise ValueError("Provide only one of file_path or url, not both")

        # 规范化 MediaType
        mt = MediaType(media_type)

        # 构建 storage_uri（至少一个为 str，见上面 ValueError）
        storage_uri: str = url or file_path  # type: ignore[assignment]
        mime = _guess_mime(storage_uri)
        fname = _filename_from(storage_uri)

        # byte_size：本地文件可读取，URL 为 0
        byte_size = 0
        if file_path:
            p = Path(file_path)
            if p.exists():
                byte_size = p.stat().st_size

        now = _now()
        # 使用时间戳 + hash 生成唯一 ID
        import hashlib
        raw_id = f"{memory_id}:{storage_uri}:{now}"
        media_id = hashlib.sha1(raw_id.encode()).hexdigest()[:16]

        # summary 存储到 metadata 中一份（便于检索），同时写列
        meta = dict(metadata) if metadata else {}
        meta["_summary"] = summary or ""

        self._store.db.execute(
            """INSERT OR REPLACE INTO media_attachments
               (media_id, memory_id, media_type, mime_type, filename,
                storage_uri, byte_size, summary, metadata, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                media_id,
                memory_id,
                mt,
                mime,
                fname,
                storage_uri,
                byte_size,
                summary or "",
                json.dumps(meta, ensure_ascii=False),
                now,
            ),
        )
        self._store.db.commit()
        return media_id

    # ── 查询 ──────────────────────────────────────────

    def get_attachments(self, memory_id: str) -> list[MediaAttachment]:
        """获取某条记忆的所有媒体附件"""
        rows = self._store.db.execute(
            "SELECT * FROM media_attachments WHERE memory_id=? ORDER BY created_at",
            (memory_id,),
        ).fetchall()
        return [self._row_to_attachment(dict(r)) for r in rows]

    def get_attachment(self, attachment_id: str) -> MediaAttachment | None:
        """按 ID 精确获取单个媒体附件"""
        row = self._store.db.execute(
            "SELECT * FROM media_attachments WHERE media_id=?",
            (attachment_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_attachment(dict(row))

    def search_by_type(
        self, media_type: str, limit: int = 20
    ) -> list[MediaAttachment]:
        """按媒体类型搜索所有附件"""
        mt = MediaType(media_type)
        rows = self._store.db.execute(
            "SELECT * FROM media_attachments WHERE media_type=? "
            "ORDER BY created_at DESC LIMIT ?",
            (mt, limit),
        ).fetchall()
        return [self._row_to_attachment(dict(r)) for r in rows]

    def search_by_summary(
        self, query: str, limit: int = 20
    ) -> list[MediaAttachment]:
        """
        全文搜索媒体摘要（LIKE 模式，中英文兼容）。

        先尝试 summary 列 LIKE 搜索；若无结果，回退到 metadata
        JSON 字段内模糊匹配。
        """
        rows = self._store.db.execute(
            "SELECT * FROM media_attachments WHERE summary LIKE ? "
            "ORDER BY created_at DESC LIMIT ?",
            (f"%{query}%", limit),
        ).fetchall()
        if rows:
            return [self._row_to_attachment(dict(r)) for r in rows]

        # 回退：metadata 内模糊匹配（所有 metadata）
        all_rows = self._store.db.execute(
            "SELECT * FROM media_attachments ORDER BY created_at DESC LIMIT 500"
        ).fetchall()
        results: list[MediaAttachment] = []
        for r in all_rows:
            meta_raw = dict(r).get("metadata", "{}")
            try:
                meta = json.loads(meta_raw) if meta_raw else {}
            except (json.JSONDecodeError, TypeError):
                meta = {}
            summary_from_meta = meta.get("_summary", "")
            if query.lower() in summary_from_meta.lower():
                results.append(self._row_to_attachment(dict(r)))
            if len(results) >= limit:
                break
        return results

    # ── 更新 ──────────────────────────────────────────

    def update_summary(self, attachment_id: str, summary: str) -> bool:
        """更新媒体附件的摘要"""
        _now()
        row = self._store.db.execute(
            "SELECT metadata FROM media_attachments WHERE media_id=?",
            (attachment_id,),
        ).fetchone()
        if row is None:
            return False

        # 更新 metadata 中的 _summary
        try:
            meta = json.loads(row["metadata"]) if row["metadata"] else {}
        except (json.JSONDecodeError, TypeError):
            meta = {}
        meta["_summary"] = summary

        self._store.db.execute(
            "UPDATE media_attachments SET summary=?, metadata=? WHERE media_id=?",
            (summary, json.dumps(meta, ensure_ascii=False), attachment_id),
        )
        self._store.db.commit()
        return True

    # ── 删除 ──────────────────────────────────────────

    def delete_attachment(self, attachment_id: str) -> bool:
        """删除一个媒体附件（同时删除关联的向量嵌入）"""
        # 先删向量嵌入（FK CASCADE 会处理，但显式更清晰）
        self._store.db.execute(
            "DELETE FROM media_embeddings WHERE media_id=?",
            (attachment_id,),
        )
        cur = self._store.db.execute(
            "DELETE FROM media_attachments WHERE media_id=?",
            (attachment_id,),
        )
        self._store.db.commit()
        return cur.rowcount > 0

    # ── 向量嵌入 ──────────────────────────────────────

    def store_embedding(
        self,
        attachment_id: str,
        model: str,
        vector: np.ndarray,
        modality: str = "image",
    ) -> None:
        """
        为媒体附件存储向量嵌入（用于跨模态检索）。

        Args:
            attachment_id: 媒体附件 ID
            model:         嵌入模型名称
            vector:        numpy 向量
            modality:      模态标签 (image / audio / text / ...)
        """
        dim = int(vector.size)
        blob = vector.astype(np.float32).tobytes()
        now = _now()
        self._store.db.execute(
            "INSERT OR REPLACE INTO media_embeddings "
            "(media_id, model, vector, dim, dtype, modality, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (attachment_id, model, blob, dim, "float32", modality, now),
        )
        self._store.db.commit()

    def load_embedding(self, attachment_id: str) -> np.ndarray | None:
        """加载媒体附件的向量嵌入"""
        row = self._store.db.execute(
            "SELECT vector, dim FROM media_embeddings WHERE media_id=?",
            (attachment_id,),
        ).fetchone()
        if row is None:
            return None
        return np.frombuffer(row["vector"], dtype=np.float32).reshape(-1)

    def delete_embedding(self, attachment_id: str) -> bool:
        """删除媒体附件的向量嵌入"""
        cur = self._store.db.execute(
            "DELETE FROM media_embeddings WHERE media_id=?",
            (attachment_id,),
        )
        self._store.db.commit()
        return cur.rowcount > 0

    def search_by_embedding(
        self,
        query_vector: np.ndarray,
        model: str | None = None,
        modality: str | None = None,
        top_k: int = 10,
    ) -> list[tuple[MediaAttachment, float]]:
        """
        向量相似度检索：返回最相似的媒体附件列表。

        Args:
            query_vector: 查询向量
            model:        限定嵌入模型（None=所有）
            modality:     限定模态（None=所有）
            top_k:        返回数量

        Returns:
            [(MediaAttachment, similarity_score), ...] 按相似度降序
        """
        conditions: list[str] = []
        params: list[Any] = []
        if model:
            conditions.append("model=?")
            params.append(model)
        if modality:
            conditions.append("modality=?")
            params.append(modality)

        where = " AND ".join(conditions)
        if where:
            where = "WHERE " + where

        rows = self._store.db.execute(
            f"SELECT media_id, vector, dim FROM media_embeddings {where}",
            params,
        ).fetchall()

        scored: list[tuple[MediaAttachment, float]] = []
        q = query_vector.astype(np.float32).flatten()
        q_norm = np.linalg.norm(q)
        if q_norm < 1e-12:
            return []

        for r in rows:
            emb = np.frombuffer(r["vector"], dtype=np.float32).reshape(-1)
            emb_norm = np.linalg.norm(emb)
            if emb_norm < 1e-12:
                continue
            sim = float(np.dot(q, emb) / (q_norm * emb_norm))
            att = self.get_attachment(r["media_id"])
            if att:
                scored.append((att, sim))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    # ── 统计 ──────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        """返回多模态附件统计信息"""
        total = self._store.db.execute(
            "SELECT COUNT(*) FROM media_attachments"
        ).fetchone()[0]
        by_type = self._store.db.execute(
            "SELECT media_type, COUNT(*) as cnt FROM media_attachments "
            "GROUP BY media_type"
        ).fetchall()
        embeddings = self._store.db.execute(
            "SELECT COUNT(*) FROM media_embeddings"
        ).fetchone()[0]
        return {
            "total_attachments": total,
            "by_type": {r["media_type"]: r["cnt"] for r in by_type},
            "total_embeddings": embeddings,
        }

    # ── 内部辅助 ──────────────────────────────────────

    def _row_to_attachment(self, row: dict[str, Any]) -> MediaAttachment:
        """数据库行 → MediaAttachment"""
        meta_raw = row.get("metadata", "{}")
        try:
            meta = json.loads(meta_raw) if meta_raw else {}
        except (json.JSONDecodeError, TypeError):
            meta = {}

        # 优先使用 summary 列值，metadata 中 _summary 作为补充
        summary = row.get("summary", "") or meta.get("_summary", "")

        return MediaAttachment(
            media_id=row["media_id"],
            memory_id=row["memory_id"],
            media_type=row.get("media_type", ""),
            mime_type=row.get("mime_type", ""),
            filename=row.get("filename", ""),
            storage_uri=row.get("storage_uri", ""),
            byte_size=row.get("byte_size", 0),
            summary=summary,
            metadata=meta,
            created_at=row.get("created_at", ""),
        )
