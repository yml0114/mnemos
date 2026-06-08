"""
嵌入向量缓存层 — EmbeddingCache

职责:
  - 桥接 PalimpsestStore (SQLite 持久化) 与 Hermes (嵌入计算)
  - get_or_compute(): 优先从 DB 加载已缓存的嵌入，只对缺失条目计算新向量
  - model_hash(): 检测模型变更，模型切换时自动使全部缓存失效
  - invalidate(): 条目删除/修改时清除对应缓存
"""

from __future__ import annotations

import hashlib
import logging
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from mnemos.embedding import Hermes
    from mnemos.storage.palimpsest import PalimpsestStore

log = logging.getLogger(__name__)


class EmbeddingCache:
    """
    嵌入向量的持久化缓存。

    用法:
        cache = EmbeddingCache(store, hermes)
        vectors = cache.get_or_compute(entries)
    """

    def __init__(self, store: PalimpsestStore, hermes: Hermes) -> None:
        self._store = store
        self._hermes = hermes
        self._model_hash: str | None = None

    # ── 公共接口 ─────────────────────────────────────────

    def model_hash(self) -> str:
        """
        返回当前嵌入模型的配置哈希。
        用于检测模型切换（如 ONNX → hash fallback，或模型版本变更）。
        """
        key = f"{self._hermes.model_name}|{self._hermes.dim}|{self._hermes.ready}"
        h = hashlib.sha256(key.encode()).hexdigest()[:16]
        self._model_hash = h
        return h

    def get_or_compute(self, entries: list) -> dict[str, np.ndarray]:
        """
        批量获取嵌入向量。

        流程:
          1. 从 DB 加载已缓存的嵌入
          2. 识别缺失的条目（新增 / 模型变更后需要重算）
          3. 批量计算缺失条目的嵌入
          4. 将新计算的嵌入写入 DB
          5. 返回完整的 {entry_id: vector} 映射
        """
        if not entries:
            return {}

        entry_ids = [
            e.entry_id if hasattr(e, "entry_id") else str(id(e))
            for e in entries
        ]
        current_hash = self.model_hash()

        # Step 1: 从 DB 加载
        cached = self._store.load_embeddings_batch(entry_ids)

        # Step 2: 识别缺失
        missing_entries = []
        missing_ids = []
        for entry, eid in zip(entries, entry_ids):
            if eid not in cached:
                missing_entries.append(entry)
                missing_ids.append(eid)

        # 模型哈希不匹配时，所有缓存都需要重算
        if cached and self._model_hash_changed(current_hash):
            log.info(
                "模型配置变更，清除 %d 条旧缓存并重新计算", len(cached)
            )
            self._store.delete_embeddings_batch(list(cached.keys()))
            missing_entries = list(entries)
            missing_ids = list(entry_ids)
            cached.clear()

        # Step 3: 批量计算缺失的嵌入
        if missing_entries:
            contents = [
                e.content for e in missing_entries
                if hasattr(e, "content")
            ]
            if contents:
                log.info(
                    "计算 %d 条缺失嵌入 (模型=%s)",
                    len(contents), self._hermes.model_name,
                )
                vectors = self._hermes.embed(contents)
                if len(vectors.shape) == 1:
                    vectors = vectors[np.newaxis, :]

                # Step 4: 逐条写入 DB
                for i, eid in enumerate(missing_ids):
                    if i < len(contents):
                        vec = vectors[i]
                        self._store.save_embedding(
                            eid, self._hermes.model_name, vec
                        )
                        cached[eid] = vec

        # 更新模型哈希
        self._model_hash = current_hash

        return cached

    def invalidate(self, entry_id: str) -> None:
        """使单条嵌入缓存失效"""
        self._store.delete_embedding(entry_id)

    def invalidate_batch(self, entry_ids: list[str]) -> None:
        """批量使嵌入缓存失效"""
        self._store.delete_embeddings_batch(entry_ids)

    def preload(self) -> dict[str, np.ndarray]:
        """
        预加载所有已缓存的嵌入（用于启动时快速恢复）。
        返回 {entry_id: vector}。
        """
        rows = self._store.db.execute(
            "SELECT entry_id, vector, dim FROM embeddings"
        ).fetchall()
        result = {}
        for row in rows:
            result[row["entry_id"]] = self._store._deserialize_vector(
                row["vector"], row["dim"]
            )
        log.info("预加载 %d 条嵌入向量", len(result))
        return result

    # ── 内部方法 ─────────────────────────────────────────

    def _model_hash_changed(self, current_hash: str) -> bool:
        """检查模型哈希是否发生变化"""
        if self._model_hash is None:
            return False  # 首次调用，不做清除
        return self._model_hash != current_hash
