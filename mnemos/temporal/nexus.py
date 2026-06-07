"""
实体链接引擎 — Nexus

对标 Mem0 Entity Linking (2026-04):
- 从记忆中提取实体并建立跨记忆关联
- 检索时按实体匹配加权
- 纯规则实现，不依赖 NER 模型（保持零外部依赖）
"""

from __future__ import annotations

import re
from collections import defaultdict

from mnemos.core.models import EntityRef, MemoryEntry


# 中文人名: 姓 + 1-2字名。名字字排除常见虚词/连词/标点/数字
_CN_SURNAME = '[刘张李王陈杨赵黄周吴徐孙马胡朱郭何罗高林郑梁谢唐许冯宋韩邓彭曹曾田萧潘袁蔡蒋余于杜叶程魏苏吕丁任卢姚沈钟姜崔谭陆汪范金石廖贾夏韦付方白邹孟熊秦邱江尹薛闫段雷侯龙史陶黎贺顾郝毛龚邵万钱严覃武戴莫孔向汤温康施文牛樊葛邢安齐易乔伍庞]'
# 合法的名字用字：非标点/非数字/非英文/非常见虚词
_NAME_CHAR = r'[^\s\d，。！？、；：""''（）【】《》\u0021-\u002f\u003a-\u0040\u005b-\u0060\u007b-\u007fa-zA-Z和与的去了吗呢吧啊在从到给为被把让对就跟也会能可以这那什么怎么但而虽因所以及或]'
_CN_NAME = re.compile(_CN_SURNAME + _NAME_CHAR + '{1,2}')

# 英文人名: 首字母大写的连续词（常见模式）
_EN_NAME = re.compile(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?\b')

# 地名: 中文地名 + 地理后缀（非贪婪，限制前文长度避免跨句匹配）
_CN_PLACE = re.compile(r'[\u4e00-\u9fff]{2,8}?(?:省|市|区|县|镇|村|路|街|广场|大厦|中心)')

# 组织/公司: 中文名称 + 组织后缀
_CN_ORG = re.compile(r'[\u4e00-\u9fff]{2,10}?(?:公司|集团|大学|学院|医院|银行|研究所|实验室|平台)')

# 技术/工具: 常见专有名词
_TECH_TERMS = re.compile(
    r'\b(?:Python|Java|Go|Rust|React|Vue|Angular|Docker|Kubernetes|K8s|'
    r'SQLite|PostgreSQL|MySQL|MongoDB|Redis|Kafka|'
    r'PyTorch|TensorFlow|MLX|Ollama|LangChain|CrewAI|'
    r'FastAPI|Flask|Django|Node\.js|TypeScript|JavaScript|'
    r'MacOS|Linux|Windows|iOS|Android|'
    r'GitHub|GitLab|AWS|GCP|Azure)\b'
)


class Nexus:
    """
    实体链接引擎。

    使用示例:
        nexus = Nexus()
        entities = nexus.extract(entry)
        linked = nexus.link(entities, all_entries)
    """

    def extract(self, entry: MemoryEntry) -> list[EntityRef]:
        """从一条记忆中提取实体"""
        content = entry.content
        found = []

        # 中文人名
        for m in _CN_NAME.finditer(content):
            found.append(EntityRef(label=m.group(), entity_type="person"))

        # 地名
        for m in _CN_PLACE.finditer(content):
            found.append(EntityRef(label=m.group(), entity_type="location"))

        # 组织
        for m in _CN_ORG.finditer(content):
            found.append(EntityRef(label=m.group(), entity_type="organization"))

        # 技术术语
        for m in _TECH_TERMS.finditer(content):
            found.append(EntityRef(label=m.group(), entity_type="artifact"))

        # 英文人名
        for m in _EN_NAME.finditer(content):
            label = m.group()
            # 过滤明显的非人名词
            if label not in {"The", "This", "That", "These", "Those", "What",
                             "When", "Where", "Which", "There", "Their", "They",
                             "With", "From", "About", "After", "Before", "Would",
                             "Could", "Should", "Have", "Has", "Been", "Were",
                             "More", "Some", "Other", "First", "Second", "Last",
                             "Next", "Only", "Also", "Just", "Like", "Make",
                             "Made", "Take", "Give", "Find", "Found", "Need",
                             "Want", "Know", "Think", "Tell", "Said", "Look",
                             "Come", "Went", "Done", "Good", "Great", "Right",
                             "Wrong", "Same", "Much", "Many", "Most", "Very"}:
                found.append(EntityRef(label=label, entity_type="person"))

        # 去重
        seen = set()
        unique = []
        for e in found:
            if e.label not in seen:
                seen.add(e.label)
                unique.append(e)
                if len(unique) >= 10:  # 每条记忆最多 10 个实体
                    break

        return unique

    def link(
        self, entities: list[EntityRef], all_entries: list[MemoryEntry]
    ) -> dict[str, list[str]]:
        """
        建立实体到记忆的链接映射。

        返回: {entity_label: [entry_id, ...]}
        """
        index = defaultdict(list)

        for entry in all_entries:
            entry_entities = entry.entities or self.extract(entry)
            for e in entry_entities:
                index[e.label].append(entry.entry_id)

        return dict(index)

    def boost_by_entity(
        self,
        results: list[tuple[MemoryEntry, float]],
        query_entities: list[str],
        entity_index: dict[str, list[str]],
    ) -> list[tuple[MemoryEntry, float]]:
        """
        实体命中加权：查询涉及的实体如果在记忆中也有出现，提升得分。
        """
        for i, (entry, score) in enumerate(results):
            bonus = 0.0
            for qe in query_entities:
                if qe in entity_index and entry.entry_id in entity_index[qe]:
                    bonus += 0.08  # 每个匹配实体加 8%
            if bonus > 0:
                results[i] = (entry, min(1.0, score + bonus))

        return sorted(results, key=lambda x: x[1], reverse=True)

    def extract_query_entities(self, query: str) -> list[str]:
        """从查询文本中提取实体（用于实体命中加权）"""
        entities = []
        for pattern in [_CN_NAME, _CN_PLACE, _CN_ORG, _TECH_TERMS, _EN_NAME]:
            for m in pattern.finditer(query):
                entities.append(m.group())
        return list(set(entities))[:5]  # 最多 5 个查询实体
