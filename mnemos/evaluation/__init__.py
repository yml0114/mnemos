"""
LLM Judge — 答案评判模块

用于 LongMemEval 等基准测试的自动评分。
支持多种 LLM 后端（OpenAI / 兼容 API），判断系统答案与标准答案的一致性。
"""

from __future__ import annotations

import json
import os
import re
from typing import Any


JUDGE_SYSTEM = """You are an impartial answer judge for a memory benchmark.
Your task: compare the system's answer to the ground truth answer and score it.

Scoring rules:
- Score 1.0: The system answer is semantically equivalent to the ground truth.
  Minor wording differences (e.g., "lives in Shanghai" vs "resides in Shanghai") are fine.
- Score 0.5: The system answer is partially correct but missing key details or includes extra incorrect info.
- Score 0.0: The system answer is wrong, irrelevant, or says "I don't know".

Return ONLY a JSON object:
{"score": <float 0-1>, "explanation": "<one sentence why>"}"""

JUDGE_PROMPT = """Question: {question}
Ground Truth: {ground_truth}
System Answer: {system_answer}

Score:"""


class LLMJudge:
    """使用 LLM 评判答案正确性。"""

    def __init__(self, api_key: str = "", model: str = "gpt-4o", base_url: str = ""):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.model = model
        self.base_url = base_url

    def evaluate(self, prediction: str, reference: str, question: str = "") -> float:
        """统一评估接口。返回 0.0-1.0 分数。"""
        result = self.judge(question=question, ground_truth=reference, system_answer=prediction)
        return result["score"]

    def judge(self, question: str, ground_truth: str, system_answer: str) -> dict[str, Any]:
        """评判单条答案。返回 {"score": float, "explanation": str}"""
        prompt = JUDGE_PROMPT.format(
            question=question,
            ground_truth=ground_truth,
            system_answer=system_answer,
        )
        try:
            response = self._call_llm(JUDGE_SYSTEM, prompt)
            return self._parse_response(response)
        except Exception as e:
            return {"score": 0.0, "explanation": f"Judge error: {e}"}

    def judge_batch(
        self, items: list[dict[str, str]]
    ) -> list[dict[str, Any]]:
        """批量评判。items: [{"question": ..., "ground_truth": ..., "system_answer": ...}]"""
        return [self.judge(**item) for item in items]

    def _call_llm(self, system: str, prompt: str) -> str:
        import httpx

        url = f"{self.base_url}/chat/completions" if self.base_url else "https://api.openai.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.0,
            "max_tokens": 200,
        }
        resp = httpx.post(url, headers=headers, json=body, timeout=30)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    def _parse_response(self, text: str) -> dict[str, Any]:
        # 尝试直接解析 JSON
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        # 尝试提取 JSON 块
        m = re.search(r'\{[^{}]*"score"[^{}]*\}', text)
        if m:
            try:
                return json.loads(m.group())
            except json.JSONDecodeError:
                pass
        return {"score": 0.0, "explanation": f"Unparseable: {text[:100]}"}


class RuleJudge:
    """规则评判器（无 LLM 依赖）。用于快速验证和 CI 环境。"""

    def evaluate(self, prediction: str, reference: str, question: str = "") -> float:
        """统一评估接口。返回 0.0-1.0 分数。"""
        result = self.judge(question=question, ground_truth=reference, system_answer=prediction)
        return result["score"]

    def judge(self, question: str, ground_truth: str, system_answer: str) -> dict[str, Any]:
        """基于关键词重叠的简单评判"""
        if not system_answer or system_answer.strip() in ("", "I don't know", "不知道"):
            return {"score": 0.0, "explanation": "Empty or 'don't know' answer"}

        gt_words = set(self._tokenize(ground_truth))
        sa_words = set(self._tokenize(system_answer))

        if not gt_words:
            return {"score": 0.0, "explanation": "Empty ground truth"}

        overlap = gt_words & sa_words
        precision = len(overlap) / len(sa_words) if sa_words else 0
        recall = len(overlap) / len(gt_words)

        # F1-like score
        if precision + recall > 0:
            score = 2 * precision * recall / (precision + recall)
        else:
            score = 0.0

        return {
            "score": round(min(score, 1.0), 2),
            "explanation": f"Keyword overlap: precision={precision:.2f}, recall={recall:.2f}",
        }

    def _tokenize(self, text: str) -> list[str]:
        """改进的分词：中文 bigram/trigram + 英文词，提升中文匹配率"""
        tokens = []
        # English words
        for m in re.finditer(r'[a-zA-Z]+', text.lower()):
            tokens.append(m.group())
        # Chinese unigrams
        cn_chars = re.findall(r'[\u4e00-\u9fff]', text)
        tokens.extend(cn_chars)
        # Chinese bigrams
        for i in range(len(cn_chars) - 1):
            tokens.append(cn_chars[i] + cn_chars[i + 1])
        # Chinese trigrams for better precision
        for i in range(len(cn_chars) - 2):
            tokens.append(cn_chars[i] + cn_chars[i + 1] + cn_chars[i + 2])
        return tokens
