"""
记忆提取引擎 — Scribe（书吏）

职责:
  从原始对话文本中提取结构化记忆单元。

提取策略:
  1. 实体识别: 从文本中识别人物、概念、产品、事件
  2. 印象提取: 将对话片段转化为离散的印象条目
  3. 信念识别: 识别文本中表达的信念/判断/决策
  4. 时序锚定: 解析相对/绝对时间表达

LLM 依赖:
  提取本身依赖 LLM（通过配置注入），但所有 LLM 调用被封装在
  extractor 函数中，可替换为任意 LLM 后端。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Protocol

from mnemos.core.models import (
    BeliefRecord,
    ConfidenceLevel,
    EntityRef,
    MemoryEntry,
    MemoryExtractionResult,
    MemoryTier,
    ScopeType,
    TemporalAnchor,
)


# ── LLM 接口 ─────────────────────────────────────────────


class LLMClient(Protocol):
    """LLM 客户端协议 — 不绑定任何特定 LLM"""

    async def generate(self, prompt: str, system: str = "") -> str:
        """生成文本"""
        ...


# ── 提取模板 ────────────────────────────────────────────


_EXTRACTION_SYSTEM = """你是一位记忆书记官(Scribe)。你的任务是从对话文本中提取结构化的记忆片段。

## 提取规则
1. **实体**: 识别所有被提及的实体（人、公司、产品、项目、技术、概念），每个实体给一个简短描述
2. **印象**: 将对话分解为独立的事实片段，每条印象一句话，包含 who/what/when
3. **信念**: 识别说话者表达的判断、偏好、决策、假设，标注置信度:
   - speculative: 推测性表述（"可能""也许""我猜"）
   - tentative: 初步判断（"我觉得""倾向于"）
   - confirmed: 明确断言（"确定""是的""就是这样"）
   - bedrock: 不可撼动的事实
4. **时间**: 识别所有时间表达（绝对日期、相对时间、事件引用）

## 输出格式
返回纯 JSON，不要 markdown 包裹:
{
  "entities": [{"label": "名称", "entity_type": "person/organization/concept/event/product", "description": "简述"}],
  "impressions": [{"title": "简短标题", "content": "完整印象内容", "beliefs": [{"content": "信念", "confidence": "speculative/tentative/confirmed/bedrock"}], "time_hint": "时间表达或null"}],
  "summary": "整体摘要一句话"
}"""


_EXTRACTION_PROMPT = """请从以下对话片段中提取记忆:

---
{text}
---

返回 JSON:"""


# ── 提取引擎 ────────────────────────────────────────────


class ScribeExtractor:
    """
    记忆书吏 — 从文本中提取结构化记忆。

    使用示例:
        extractor = ScribeExtractor(llm_client=my_llm)
        result = await extractor.extract("小米今天股价涨了5%")
    """

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        *,
        extract_fn: Callable[[str], dict[str, Any]] | None = None,
    ):
        """
        Args:
            llm_client: LLM 客户端（可选，如果不提供则使用 extract_fn）
            extract_fn: 自定义提取函数（可选，用于绕过 LLM 的测试/简单场景）
        """
        self._llm = llm_client
        self._extract_fn = extract_fn

    async def extract(
        self,
        text: str,
        scope_type: ScopeType = ScopeType.TENANT,
        scope_id: str = "",
        source_ref: str = "",
    ) -> MemoryExtractionResult:
        """从文本中提取记忆"""
        if not text.strip():
            return MemoryExtractionResult()

        # 调用提取（LLM 或自定义函数）
        raw = await self._call_extract(text)

        entities = [
            EntityRef(
                entity_id=uuid.uuid4().hex[:12],
                label=e.get("label", ""),
                entity_type=e.get("entity_type", "concept"),
                description=e.get("description", ""),
            )
            for e in raw.get("entities", [])
        ]

        now = datetime.now(timezone.utc)
        impressions: list[MemoryEntry] = []

        for imp in raw.get("impressions", []):
            time_hint = imp.get("time_hint")
            anchors: list[TemporalAnchor] = []
            if time_hint:
                anchors.append(TemporalAnchor(
                    anchor_id=uuid.uuid4().hex[:8],
                    recorded_at=now,
                    relative_expression=time_hint,
                ))

            beliefs = [
                BeliefRecord(
                    belief_id=uuid.uuid4().hex[:10],
                    content=b.get("content", ""),
                    confidence=ConfidenceLevel(
                        b.get("confidence", "speculative")
                    ),
                    source=source_ref,
                    adopted_at=now,
                )
                for b in imp.get("beliefs", [])
            ]

            entry = MemoryEntry(
                entry_id=uuid.uuid4().hex[:16],
                tier=MemoryTier.IMPRESSION,
                title=imp.get("title", text[:50]),
                content=imp.get("content", text),
                scope=scope_type,
                scope_id=scope_id,
                entities=entities,
                beliefs=beliefs,
                anchors=anchors,
                created_at=now,
                last_accessed_at=now,
            )
            impressions.append(entry)

        return MemoryExtractionResult(
            impressions=impressions,
            entities_extracted=entities,
        )

    async def _call_extract(self, text: str) -> dict[str, Any]:
        """调用 LLM 或自定义函数提取"""
        import json as _json

        if self._extract_fn:
            return self._extract_fn(text)

        if self._llm is None:
            # 无 LLM 时的退化模式：纯规则提取
            return _rule_based_extract(text)

        prompt = _EXTRACTION_PROMPT.format(text=text[:8000])
        raw = await self._llm.generate(
            prompt=prompt, system=_EXTRACTION_SYSTEM
        )

        # 清理 LLM 输出中可能的 markdown 包裹
        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1])

        try:
            return _json.loads(raw)
        except _json.JSONDecodeError:
            # 解析失败时退化为规则提取
            return _rule_based_extract(text)


# ── 规则退化提取 ────────────────────────────────────────


def _rule_based_extract(text: str) -> dict[str, Any]:
    """当 LLM 不可用时的纯规则退化提取"""
    import re

    # 简单实体识别
    entity_matches = re.findall(
        r'(?:公司|产品|项目|框架|工具|语言|协议)[：:]?\s*([^\s，。,\.]{2,30})',
        text,
    )

    # 简单信念识别
    belief_patterns = [
        (r'(?:我确定|肯定|一定是|毫无疑问)([^。！？\n]{5,50})', "confirmed"),
        (r'(?:我觉得|我认为|倾向于|倾向于)([^。！？\n]{5,50})', "tentative"),
        (r'(?:可能|也许|大概|或许|说不定)([^。！？\n]{5,50})', "speculative"),
    ]

    beliefs = []
    for pattern, conf in belief_patterns:
        for m in re.findall(pattern, text):
            beliefs.append({"content": m.strip(), "confidence": conf})

    return {
        "entities": [
            {"label": e, "entity_type": "concept", "description": ""}
            for e in entity_matches[:10]
        ],
        "impressions": [{
            "title": text[:80],
            "content": text,
            "beliefs": beliefs,
            "time_hint": None,
        }],
        "summary": text[:200],
    }
