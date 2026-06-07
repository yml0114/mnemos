"""
Palimpsest 存储引擎测试
"""

import pytest
from datetime import datetime, timezone

from mnemos.core.models import (
    MemoryEntry, MemoryTier, ScopeType, EntityRef, BeliefRecord,
    ConfidenceLevel, TemporalAnchor, MemoryQuery,
)
from mnemos.storage.palimpsest import PalimpsestStore
from mnemos.retrieval.resonance import ResonanceEngine


@pytest.fixture
def store():
    s = PalimpsestStore(":memory:")
    s.connect()
    yield s
    s.close()


def test_inscribe_and_recall_impression(store):
    """测试印象写入与召回"""
    entry = MemoryEntry(
        title="小米股价大涨",
        content="2026年6月7日，小米集团股价上涨5.2%，收于32.8港元",
        tier=MemoryTier.IMPRESSION,
        scope=ScopeType.TENANT,
        scope_id="user_001",
        tags=["小米", "股价", "港股"],
        entities=[
            EntityRef(label="小米集团", entity_type="organization"),
            EntityRef(label="港股", entity_type="concept"),
        ],
    )
    eid = store.inscribe(entry)
    assert eid == entry.entry_id

    # 按 ID 召回
    recalled = store.by_id(eid)
    assert recalled is not None
    assert recalled.title == "小米股价大涨"
    assert "32.8港元" in recalled.content
    assert recalled.tier == MemoryTier.IMPRESSION

    # 按范围召回
    scoped = store.by_scope(ScopeType.TENANT, "user_001")
    assert len(scoped) >= 1
    assert any(e.entry_id == eid for e in scoped)


def test_inscribe_pattern_and_principle(store):
    """测试模式和原则写入"""
    # Pattern
    pattern = MemoryEntry(
        title="小米股价规律",
        content="小米股价在财报发布前一周通常有5-10%的上涨",
        tier=MemoryTier.PATTERN,
        scope=ScopeType.TENANT,
        scope_id="user_001",
        entities=[EntityRef(label="小米集团", entity_type="organization")],
        beliefs=[
            BeliefRecord(
                content="小米股价财报前上涨是规律",
                confidence=ConfidenceLevel.CONFIRMED,
            )
        ],
    )
    pid = store.inscribe(pattern)
    assert pid

    # Principle
    principle = MemoryEntry(
        title="财报前布局原则",
        content="在财报发布前一周买入小米正股，财报发布当日卖出",
        tier=MemoryTier.PRINCIPLE,
        scope=ScopeType.UNIVERSE,
        scope_id="",
        entities=[EntityRef(label="小米集团", entity_type="organization")],
        beliefs=[
            BeliefRecord(
                content="财报前买入、发布日卖出是有效策略",
                confidence=ConfidenceLevel.BEDROCK,
            )
        ],
    )
    prid = store.inscribe(principle)
    assert prid

    # 统计
    stats = store.count()
    assert stats["impressions"] == 0
    assert stats["patterns"] == 1
    assert stats["principles"] == 1


def test_fulltext_search(store):
    """测试全文搜索"""
    entries = [
        ("小米股价大涨", "小米集团股价上涨5.2%"),
        ("腾讯财报发布", "腾讯控股发布2026Q1财报，营收增长12%"),
        ("小米汽车交付", "小米SU7本月交付突破2万辆"),
    ]
    for title, content in entries:
        store.inscribe(MemoryEntry(
            title=title, content=content,
            tier=MemoryTier.IMPRESSION,
            scope=ScopeType.TENANT, scope_id="user_001",
        ))

    # 搜索"小米"
    results = store.fts("小米")
    assert len(results) >= 2  # 小米股价 + 小米汽车

    # 搜索"财报"
    results = store.fts("财报")
    assert len(results) >= 1
    assert any("腾讯" in r.content for r in results)


def test_entity_search(store):
    """测试实体检索"""
    for i in range(3):
        store.inscribe(MemoryEntry(
            title=f"小米事件{i}",
            content=f"小米第{i}次事件记录",
            tier=MemoryTier.IMPRESSION,
            scope=ScopeType.TENANT, scope_id="user_001",
            entities=[EntityRef(label="小米集团", entity_type="organization")],
        ))

    results = store.by_entity("小米")
    assert len(results) == 3


def test_time_range_search(store):
    """测试时间范围检索"""
    from datetime import timedelta

    now = datetime.now(timezone.utc)

    # 写入不同时间的记忆
    old = MemoryEntry(
        title="旧事件", content="三天前的事",
        tier=MemoryTier.IMPRESSION,
        scope=ScopeType.TENANT, scope_id="user_001",
        created_at=now - timedelta(days=3),
        last_accessed_at=now - timedelta(days=3),
    )
    new = MemoryEntry(
        title="新事件", content="刚才发生的事",
        tier=MemoryTier.IMPRESSION,
        scope=ScopeType.TENANT, scope_id="user_001",
        created_at=now,
        last_accessed_at=now,
    )
    store.inscribe(old)
    store.inscribe(new)

    # 搜索最近1天
    recent = store.by_time(after=now - timedelta(days=1))
    assert len(recent) >= 1
    assert any("刚才" in r.content for r in recent)


def test_entity_graph(store):
    """测试实体共现图谱"""
    store.inscribe(MemoryEntry(
        title="小米和雷军",
        content="雷军在小米发布会上宣布新战略",
        tier=MemoryTier.IMPRESSION,
        scope=ScopeType.TENANT, scope_id="user_001",
        entities=[
            EntityRef(label="小米集团", entity_type="organization"),
            EntityRef(label="雷军", entity_type="person"),
        ],
    ))
    store.inscribe(MemoryEntry(
        title="雷军访谈",
        content="雷军接受央视访谈谈小米汽车",
        tier=MemoryTier.IMPRESSION,
        scope=ScopeType.TENANT, scope_id="user_001",
        entities=[
            EntityRef(label="雷军", entity_type="person"),
            EntityRef(label="小米汽车", entity_type="product"),
        ],
    ))

    graph = store.entity_graph("雷军")
    assert "center" in graph
    assert graph["center"] == "雷军"
    assert len(graph["edges"]) >= 1
    # 雷军应该和小米集团、小米汽车都有共现
    labels = {e["source"] for e in graph["edges"]} | {e["target"] for e in graph["edges"]}
    assert "小米集团" in labels or "小米汽车" in labels


def test_belief_revision(store):
    """测试信念修正"""
    entry = MemoryEntry(
        title="小米股价预测",
        content="小米股价预测分析",
        tier=MemoryTier.IMPRESSION,
        scope=ScopeType.TENANT, scope_id="user_001",
        beliefs=[
            BeliefRecord(
                content="小米股价年底能到40港元",
                confidence=ConfidenceLevel.TENTATIVE,
            )
        ],
    )
    eid = store.inscribe(entry)

    # 召回并修正
    recalled = store.by_id(eid)
    old_belief = recalled.beliefs[0]
    recalled.revise_belief(
        old_belief_id=old_belief.belief_id,
        new_content="小米股价年底可能到35港元（修正）",
        source="新财报数据",
    )

    # 更新存储
    import json
    store.revise(eid, MemoryTier.IMPRESSION, {
        "beliefs_json": json.dumps(
            [b.model_dump() for b in recalled.beliefs],
            ensure_ascii=False,
            default=str,
        ),
    })

    # 验证
    updated = store.by_id(eid)
    current = updated.current_beliefs()
    assert len(current) == 1
    assert "35港元" in current[0].content

    # 旧信念应被标记为被取代
    superseded = [b for b in updated.beliefs if b.superseded_by is not None]
    assert len(superseded) == 1


def test_decay(store):
    """测试记忆衰减"""
    from datetime import timedelta

    now = datetime.now(timezone.utc)

    # 写入一条"旧"记忆（很久未访问）
    stale = MemoryEntry(
        title="过期事件", content="很久以前的事",
        tier=MemoryTier.IMPRESSION,
        scope=ScopeType.TENANT, scope_id="user_001",
        decay_factor=0.02,
        created_at=now - timedelta(days=30),
        last_accessed_at=now - timedelta(days=30),
    )
    store.inscribe(stale)

    # 衰减
    count = store.decay_stale(rate=0.02)
    assert count >= 0

    # 衰减后应变小
    recalled = store.by_id(stale.entry_id)
    assert recalled.decay_factor <= 0.01


def test_resonance_search(store):
    """测试多信号融合检索"""
    # 准备数据
    store.inscribe(MemoryEntry(
        title="小米股价大涨",
        content="2026年6月7日，小米集团股价上涨5.2%，雷军在发布会上宣布新战略",
        tier=MemoryTier.IMPRESSION,
        scope=ScopeType.TENANT, scope_id="user_001",
        tags=["小米", "股价", "港股"],
        entities=[
            EntityRef(label="小米集团", entity_type="organization"),
            EntityRef(label="雷军", entity_type="person"),
        ],
    ))
    store.inscribe(MemoryEntry(
        title="腾讯财报发布",
        content="腾讯控股发布2026Q1财报",
        tier=MemoryTier.IMPRESSION,
        scope=ScopeType.TENANT, scope_id="user_001",
        entities=[EntityRef(label="腾讯控股", entity_type="organization")],
    ))

    engine = ResonanceEngine(store)

    # 语义搜索
    query = MemoryQuery(query_text="小米 雷军")
    results = engine.search(query)
    assert len(results) >= 1
    assert results[0].resonance_score > 0
    assert "小米" in results[0].entry.title or "小米" in results[0].entry.content

    # 实体搜索
    query = MemoryQuery(query_text="", entities=["腾讯控股"])
    results = engine.search(query)
    assert len(results) >= 1
    assert any("腾讯" in r.entry.content for r in results)


def test_memory_traverse(store):
    """测试记忆关联遍历"""
    # 创建关联链: A ← B ← C
    a = MemoryEntry(
        title="事件A", content="原始事件",
        tier=MemoryTier.IMPRESSION,
        scope=ScopeType.TENANT, scope_id="user_001",
    )
    a_id = store.inscribe(a)

    b = MemoryEntry(
        title="事件B", content="关联事件B",
        tier=MemoryTier.IMPRESSION,
        scope=ScopeType.TENANT, scope_id="user_001",
        related_ids=[a_id],
    )
    b_id = store.inscribe(b)

    # 验证 B 存储了关联
    b_recalled = store.by_id(b_id)
    assert a_id in b_recalled.related_ids, f"B should reference A, got {b_recalled.related_ids}"

    # 从 B 遍历，depth=2 表示 B + 1跳邻居
    chain = store.traverse(b_id, depth=2)
    ids = {e.entry_id for e in chain}
    assert b_id in ids
    assert a_id in ids, f"A ({a_id}) should be in chain: {ids}"


def test_store_stats(store):
    """测试统计"""
    for i in range(5):
        store.inscribe(MemoryEntry(
            title=f"测试{i}", content=f"内容{i}",
            tier=MemoryTier.IMPRESSION,
            scope=ScopeType.TENANT, scope_id="user_001",
            entities=[EntityRef(label=f"实体{i}", entity_type="concept")],
        ))

    stats = store.count()
    assert stats["impressions"] == 5
    assert stats["entities"] == 5
    # 如果实体间有共现，cooccur 可能 > 0（这里每个记忆只有一个实体，所以共现为 0）
    assert stats["cooccur_pairs"] == 0


def test_scope_isolation(store):
    """测试范围隔离"""
    # 用户A的记忆
    store.inscribe(MemoryEntry(
        title="用户A的秘密", content="A的隐私",
        tier=MemoryTier.IMPRESSION,
        scope=ScopeType.TENANT, scope_id="user_a",
    ))
    # 用户B的记忆
    store.inscribe(MemoryEntry(
        title="用户B的秘密", content="B的隐私",
        tier=MemoryTier.IMPRESSION,
        scope=ScopeType.TENANT, scope_id="user_b",
    ))

    # 用户A查询不应看到B的记忆
    a_results = store.by_scope(ScopeType.TENANT, "user_a")
    assert all("A" in r.content or r.content == "A的隐私" for r in a_results)
    assert not any("B的隐私" in r.content for r in a_results)

    # 全局原则应所有人可见
    store.inscribe(MemoryEntry(
        title="全局规则", content="所有人可见的规则",
        tier=MemoryTier.PRINCIPLE,
        scope=ScopeType.UNIVERSE, scope_id="",
    ))
    universe = store.by_scope(ScopeType.UNIVERSE, "")
    assert any("所有人可见" in r.content for r in universe)
