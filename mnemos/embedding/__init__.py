"""
本地语义嵌入引擎 — Hermes

零外部 API 依赖的向量嵌入方案：
- ONNX Runtime 运行本地模型（384维，~24MB）
- 自动降级：ONNX → n-gram 哈希投影
- 轻量加载：huggingface_hub + tokenizers，不依赖 transformers/optimum
"""

from __future__ import annotations

import hashlib
import os
import struct
from pathlib import Path

import numpy as np

DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIM = 384
CACHE_DIR = Path.home() / ".cache" / "mnemos" / "embeddings"


class Hermes:
    """语义嵌入引擎。自动尝试 ONNX，失败降级为 hash。"""

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
        # 本地无模型文件且禁止下载 → 直接跳过，不卡网络
        onnx_path = self.cache_dir / "model.onnx"
        if not onnx_path.exists() and os.environ.get("MNEMOS_NO_DOWNLOAD", ""):
            self._ready = False
            return
        try:
            import onnxruntime as ort
            model_path = self._ensure_model()
            if not model_path:
                return
            self._session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
            self._tokenizer = self._load_tokenizer()
            self._ready = True
        except Exception:
            self._ready = False

    def _ensure_model(self) -> Path | None:
        onnx_path = self.cache_dir / "model.onnx"
        if onnx_path.exists():
            return onnx_path
        # 如果环境变量禁用下载或无网络，直接跳过
        if os.environ.get("MNEMOS_NO_DOWNLOAD"):
            return None
        try:
            import httpx
            resp = httpx.head("https://huggingface.co", timeout=3.0)
            if resp.status_code != 200:
                return None
        except Exception:
            return None
        try:
            from huggingface_hub import hf_hub_download
            import shutil
            downloaded = hf_hub_download(
                repo_id=self.model_name, filename="onnx/model.onnx",
                cache_dir=str(self.cache_dir / "hf_cache"),
            )
            shutil.copy(downloaded, onnx_path)
            return onnx_path
        except Exception:
            return None

    def _load_tokenizer(self):
        tokenizer_path = self.cache_dir / "tokenizer.json"
        if not tokenizer_path.exists():
            if os.environ.get("MNEMOS_NO_DOWNLOAD"):
                return None
            try:
                import httpx
                resp = httpx.head("https://huggingface.co", timeout=3.0)
                if resp.status_code != 200:
                    return None
            except Exception:
                return None
            try:
                from huggingface_hub import hf_hub_download
                import shutil
                downloaded = hf_hub_download(
                    repo_id=self.model_name, filename="tokenizer.json",
                    cache_dir=str(self.cache_dir / "hf_cache"),
                )
                shutil.copy(downloaded, tokenizer_path)
            except Exception:
                return None
        try:
            from tokenizers import Tokenizer
            return Tokenizer.from_file(str(tokenizer_path))
        except Exception:
            return None

    @property
    def ready(self) -> bool:
        return self._ready

    def embed(self, text: str | list[str]) -> np.ndarray:
        if self._ready and self._session is not None:
            return self._embed_onnx(text)
        return self._embed_hash(text)

    def _embed_onnx(self, text: str | list[str]) -> np.ndarray:
        texts = [text] if isinstance(text, str) else text
        if self._tokenizer is not None:
            encodings = self._tokenizer.encode_batch(texts)
            max_len = min(max(len(e.ids) for e in encodings), 256)
            input_ids = np.zeros((len(texts), max_len), dtype=np.int64)
            attention_mask = np.zeros((len(texts), max_len), dtype=np.int64)
            for i, enc in enumerate(encodings):
                n = min(len(enc.ids), max_len)
                input_ids[i, :n] = enc.ids[:n]
                attention_mask[i, :n] = 1
        else:
            input_ids, attention_mask = self._simple_encode(texts)

        outputs = self._session.run(None, {"input_ids": input_ids, "attention_mask": attention_mask})
        embeddings = outputs[0]
        if len(embeddings.shape) == 2:
            embeddings = embeddings[np.newaxis, :, :]
        mask = attention_mask[:, :, np.newaxis].astype(np.float32)
        embeddings = (embeddings * mask).sum(axis=1) / np.maximum(mask.sum(axis=1), 1e-12)
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        embeddings = embeddings / np.maximum(norms, 1e-12)
        return embeddings[0] if isinstance(text, str) else embeddings

    def _simple_encode(self, texts: list[str]) -> tuple[np.ndarray, np.ndarray]:
        max_len = min(max(len(t) for t in texts), 128)
        input_ids = np.zeros((len(texts), max_len), dtype=np.int64)
        attention_mask = np.zeros((len(texts), max_len), dtype=np.int64)
        for i, t in enumerate(texts):
            for j, ch in enumerate(t[:max_len]):
                input_ids[i, j] = ord(ch) % 30000 + 1
                attention_mask[i, j] = 1
        return input_ids, attention_mask

    def _embed_hash(self, text: str | list[str]) -> np.ndarray:
        texts = [text] if isinstance(text, str) else text
        vectors = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, t in enumerate(texts):
            grams = set()
            t_lower = t.lower()
            for n in range(1, 5):
                for j in range(len(t_lower) - n + 1):
                    grams.add(t_lower[j:j + n])
            for g in grams:
                h = hashlib.md5(g.encode()).digest()
                for k in range(4):
                    dim_idx = struct.unpack("I", h[k * 4:(k + 1) * 4])[0] % self.dim
                    sign = 1.0 if (h[k] & 0x80) else -1.0
                    vectors[i, dim_idx] += sign
            norm = np.linalg.norm(vectors[i])
            if norm > 1e-12:
                vectors[i] /= norm
        return vectors[0] if isinstance(text, str) else vectors

    def cosine_similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        return float(np.dot(a, b))

    def batch_similarity(self, query: np.ndarray, candidates: np.ndarray) -> np.ndarray:
        return np.dot(candidates, query)


_hermes: Hermes | None = None


def get_hermes() -> Hermes:
    global _hermes
    if _hermes is None:
        _hermes = Hermes()
    return _hermes
