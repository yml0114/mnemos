"""
BM25 关键词检索引擎

轻量实现，对标 Mem0 的 BM25 通道。不依赖 elasticsearch 等外部服务，
纯 Python + numpy，与 FTS5 并行运行提供更精准的关键词匹配。
"""

from __future__ import annotations

import re
from collections import Counter
from math import log

import numpy as np


class BM25Scorer:
    """
    轻量 BM25 实现。

    对标 Mem0 多信号检索中的 BM25 关键词通道。
    FTS5 做快速召回，BM25 做精确评分。

    使用示例:
        scorer = BM25Scorer()
        scorer.index(["记忆1 内容", "记忆2 内容"])
        scores = scorer.score("查询文本")
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self._docs: list[list[str]] = []
        self._doc_ids: list[str] = []
        self._doc_freq: Counter = Counter()  # 词→文档频率
        self._avgdl: float = 0.0
        self._tokenizer = re.compile(r'[\u4e00-\u9fff]+|[a-zA-Z]+')

    def index(self, docs: list[tuple[str, str]]):
        """
        建立索引。

        Args:
            docs: [(entry_id, content), ...]
        """
        self._docs = []
        self._doc_ids = []
        self._doc_freq = Counter()
        total_len = 0

        for doc_id, content in docs:
            tokens = self._tokenize(content)
            self._docs.append(tokens)
            self._doc_ids.append(doc_id)
            total_len += len(tokens)
            for token in set(tokens):
                self._doc_freq[token] += 1

        self._avgdl = total_len / max(len(self._docs), 1)

    def add(self, doc_id: str, content: str):
        """增量添加文档"""
        tokens = self._tokenize(content)
        self._docs.append(tokens)
        self._doc_ids.append(doc_id)
        for token in set(tokens):
            self._doc_freq[token] += 1
        total_len = sum(len(d) for d in self._docs)
        self._avgdl = total_len / max(len(self._docs), 1)

    def remove(self, doc_id: str):
        """移除文档"""
        try:
            idx = self._doc_ids.index(doc_id)
            tokens = self._docs[idx]
            for token in set(tokens):
                self._doc_freq[token] = max(0, self._doc_freq[token] - 1)
            del self._docs[idx]
            del self._doc_ids[idx]
        except ValueError:
            pass

    def score(self, query: str) -> list[tuple[str, float]]:
        """
        对查询评分，返回 [(doc_id, score), ...] 按得分降序。
        """
        query_tokens = self._tokenize(query)
        if not query_tokens or not self._docs:
            return []

        N = len(self._docs)
        scores = np.zeros(N)

        for token in query_tokens:
            df = self._doc_freq.get(token, 0)
            if df == 0:
                continue
            idf = log((N - df + 0.5) / (df + 0.5) + 1.0)

            for i, doc_tokens in enumerate(self._docs):
                tf = doc_tokens.count(token)
                if tf == 0:
                    continue
                doc_len = len(doc_tokens)
                numerator = tf * (self.k1 + 1)
                denominator = tf + self.k1 * (
                    1 - self.b + self.b * doc_len / self._avgdl
                )
                scores[i] += idf * numerator / denominator

        # 归一化到 0-1
        max_score = scores.max()
        if max_score > 0:
            scores /= max_score

        results = [
            (self._doc_ids[i], float(scores[i]))
            for i in np.argsort(scores)[::-1]
            if scores[i] > 0.01
        ]
        return results

    def _tokenize(self, text: str) -> list[str]:
        return [m.group().lower() for m in self._tokenizer.finditer(text)]
