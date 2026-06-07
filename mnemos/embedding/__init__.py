"""
本地语义嵌入引擎 — Hermes

零外部 API 依赖的向量嵌入方案：
- ONNX Runtime 运行本地模型
- 默认使用 BGE-small-en-v1.5（384维，24MB）
- 自动降级：ONNX → 随机投影哈希 → 纯 FTS5
- 保持 Mnemos 的"零配置启动"原则

设计哲学：
  嵌入是可选的增强层，不是核心依赖。
  没有 ONNX 时照样能跑，有了它检索更聪明。
"""

from __future__ import annotations

import hashlib
import struct
from pathlib import Path
from typing import Any

import numpy as np


# ── 默认配置 ──────────────────────────────────────────────

DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"
EMBEDDING_DIM = 384
CACHE_DIR = Path.home() / ".cache" / "mnemos" / "embeddings"


class Hermes:
    """
    语义嵌入引擎。自动尝试 ONNX，失败降级为 hash。

    使用示例:
        hermes = Hermes()
        vec = hermes.embed("用户喜欢黑暗模式")
        score = hermes.cosine_similarity(vec1, vec2)
    """

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        dim: int = EMBEDDING_DIM,
        cache_dir: Path | str | None = None,
    ):
        self.model_name = model_name
        self.dim = dim
        self.cache_dir = Path(cache_dir) if cache_dir else CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self._session = None
        self._tokenizer = None
        self._ready = False

        self._try_init_onnx()

    def _try_init_onnx(self) -> None:
        """尝试加载 ONNX 模型，失败则静默降级"""
        try:
            import onnxruntime as ort
            from transformers import AutoTokenizer

            model_path = self.cache_dir / "model.onnx"

            if not model_path.exists():
                self._download_model(model_path)

            self._session = ort.InferenceSession(
                str(model_path),
                providers=["CPUExecutionProvider"],
            )
            self._tokenizer = AutoTokenizer.from_pretrained(
                str(self.cache_dir / "tokenizer"),
                local_files_only=True,
            )
            self._ready = True
        except Exception:
            # 静默降级：hash embedding
            self._ready = False

    def _download_model(self, model_path: Path) -> None:
        """从 HuggingFace 下载模型并导出为 ONNX"""
        try:
            from optimum.onnxruntime import ORTModelForFeatureExtraction
            from transformers import AutoTokenizer

            model = ORTModelForFeatureExtraction.from_pretrained(
                self.model_name, export=True
            )
            model.save_pretrained(str(self.cache_dir))

            tokenizer = AutoTokenizer.from_pretrained(self.model_name)
            tokenizer.save_pretrained(str(self.cache_dir / "tokenizer"))
        except Exception:
            raise RuntimeError(
                "无法下载嵌入模型。请手动运行:\n"
                "  pip install optimum[onnxruntime] transformers\n"
                "  python -c \"from optimum.onnxruntime import ORTModelForFeatureExtraction; "
                f"ORTModelForFeatureExtraction.from_pretrained('{self.model_name}', export=True)"
                f".save_pretrained('{self.cache_dir}')\""
            )

    @property
    def ready(self) -> bool:
        """是否加载了真实嵌入模型"""
        return self._ready

    def embed(self, text: str | list[str]) -> np.ndarray:
        """
        将文本转换为嵌入向量。

        返回 shape: (dim,) 或 (n, dim)
        """
        if self._ready and self._session is not None and self._tokenizer is not None:
            return self._embed_onnx(text)
        return self._embed_hash(text)

    def _embed_onnx(self, text: str | list[str]) -> np.ndarray:
        """ONNX 推理"""
        texts = [text] if isinstance(text, str) else text

        inputs = self._tokenizer(
            texts,
            padding=True,
            truncation=True,
            max_length=512,
            return_tensors="np",
        )

        outputs = self._session.run(
            None,
            {
                "input_ids": inputs["input_ids"],
                "attention_mask": inputs["attention_mask"],
            },
        )

        # 平均池化
        embeddings = outputs[0]
        mask = inputs["attention_mask"]
        mask_expanded = np.expand_dims(mask, -1).astype(np.float32)
        embeddings = (embeddings * mask_expanded).sum(axis=1) / mask_expanded.sum(axis=1)

        # L2 归一化
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms = np.maximum(norms, 1e-12)
        embeddings = embeddings / norms

        if isinstance(text, str):
            return embeddings[0]
        return embeddings

    def _embed_hash(self, text: str | list[str]) -> np.ndarray:
        """
        降级方案：确定性哈希投影。

        虽然不是真正的语义嵌入，但比随机好：
        - 相同文本 → 相同向量（可用于精确去重）
        - 近似文本 → 近似向量（n-gram 特征）
        - 零依赖，永远可用
        """
        texts = [text] if isinstance(text, str) else text
        vectors = np.zeros((len(texts), self.dim), dtype=np.float32)

        for i, t in enumerate(texts):
            # n-gram 特征（1-4 gram）
            grams = set()
            t_lower = t.lower()
            for n in range(1, 5):
                for j in range(len(t_lower) - n + 1):
                    grams.add(t_lower[j:j + n])

            # 每个 gram 哈希到多个维度
            for g in grams:
                h = hashlib.md5(g.encode()).digest()
                for k in range(4):
                    dim_idx = struct.unpack("I", h[k * 4:(k + 1) * 4])[0] % self.dim
                    sign = 1.0 if (h[k] & 0x80) else -1.0
                    vectors[i, dim_idx] += sign

            # 按词数归一化
            norm = np.linalg.norm(vectors[i])
            if norm > 1e-12:
                vectors[i] /= norm

        if isinstance(text, str):
            return vectors[0]
        return vectors

    def cosine_similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        """余弦相似度"""
        return float(np.dot(a, b))

    def batch_similarity(
        self, query: np.ndarray, candidates: np.ndarray
    ) -> np.ndarray:
        """查询向量 vs 候选矩阵的批量相似度"""
        return np.dot(candidates, query)  # (n, dim) @ (dim,) → (n,)


# ── 单例 ──────────────────────────────────────────────────

_hermes: Hermes | None = None


def get_hermes() -> Hermes:
    global _hermes
    if _hermes is None:
        _hermes = Hermes()
    return _hermes
