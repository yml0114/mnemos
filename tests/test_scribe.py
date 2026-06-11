"""Tests for mnemos.extraction.scribe module."""

import pytest
from mnemos.extraction.scribe import ScribeExtractor, _rule_based_extract


class TestScribeExtractor:
    """Tests for ScribeExtractor."""

    @pytest.mark.asyncio
    async def test_extract_empty_text(self):
        """空文本应返回空结果"""
        extractor = ScribeExtractor()
        result = await extractor.extract("")
        assert len(result.impressions) == 0
        assert len(result.entities_extracted) == 0

    @pytest.mark.asyncio
    async def test_extract_whitespace_only(self):
        """纯空白文本应返回空结果"""
        extractor = ScribeExtractor()
        result = await extractor.extract("   \n\t  ")
        assert len(result.impressions) == 0

    @pytest.mark.asyncio
    async def test_extract_with_custom_fn(self):
        """使用自定义提取函数"""
        def mock_extract(text):
            return {
                "entities": [{"label": "小米", "entity_type": "organization", "description": "科技公司"}],
                "impressions": [{"title": "小米股价", "content": "小米今天股价涨了5%", "beliefs": [], "time_hint": "今天"}],
                "summary": "小米股价上涨"
            }
        
        extractor = ScribeExtractor(extract_fn=mock_extract)
        result = await extractor.extract("小米今天股价涨了5%")
        
        assert len(result.impressions) == 1
        assert result.impressions[0].title == "小米股价"
        assert len(result.entities_extracted) == 1
        assert result.entities_extracted[0].label == "小米"

    @pytest.mark.asyncio
    async def test_extract_no_llm_fallback(self):
        """无 LLM 时应退化为规则提取"""
        extractor = ScribeExtractor()  # 无 llm_client, 无 extract_fn
        result = await extractor.extract("我觉得这个项目很有前景")
        
        # 应该有印象
        assert len(result.impressions) >= 1

    @pytest.mark.asyncio
    async def test_extract_with_beliefs(self):
        """提取包含信念的记忆"""
        def mock_extract(text):
            return {
                "entities": [],
                "impressions": [{
                    "title": "测试",
                    "content": text,
                    "beliefs": [{"content": "这个方案可行", "confidence": "confirmed"}],
                    "time_hint": None
                }],
                "summary": "测试"
            }
        
        extractor = ScribeExtractor(extract_fn=mock_extract)
        result = await extractor.extract("我确定这个方案可行")
        
        assert len(result.impressions[0].beliefs) == 1
        assert result.impressions[0].beliefs[0].content == "这个方案可行"


class TestRuleBasedExtract:
    """Tests for _rule_based_extract function."""

    def test_basic_extraction(self):
        """基本规则提取"""
        result = _rule_based_extract("今天的会议讨论了项目进度")
        assert "entities" in result
        assert "impressions" in result
        assert "summary" in result

    def test_belief_detection_confirmed(self):
        """检测 confirmed 级别信念"""
        result = _rule_based_extract("我确定这个方案是正确的")
        beliefs = result["impressions"][0]["beliefs"]
        confirmed = [b for b in beliefs if b["confidence"] == "confirmed"]
        assert len(confirmed) >= 1

    def test_belief_detection_tentative(self):
        """检测 tentative 级别信念"""
        result = _rule_based_extract("我觉得这个方向是对的")
        beliefs = result["impressions"][0]["beliefs"]
        tentative = [b for b in beliefs if b["confidence"] == "tentative"]
        assert len(tentative) >= 1

    def test_belief_detection_speculative(self):
        """检测 speculative 级别信念"""
        result = _rule_based_extract("可能这个方案需要调整")
        beliefs = result["impressions"][0]["beliefs"]
        speculative = [b for b in beliefs if b["confidence"] == "speculative"]
        assert len(speculative) >= 1

    def test_entity_extraction(self):
        """提取实体"""
        result = _rule_based_extract("我们使用了Python框架开发这个项目")
        entities = result["entities"]
        # 可能提取到 "Python" 或 "开发这个项目"
        assert isinstance(entities, list)
