# Mnemos — 独立记忆世界

> **Memory Palimpsest（记忆重写本）** — 可移植的多层 AI 记忆系统

独立记忆世界是一个开源的、独立部署的 AI Agent 记忆后端。不绑定任何框架，任何 Agent 通过 MCP 协议即可接入。

## 核心理念

- **记忆如重写本**：信念可以被修正，旧版本不删除，作为"底本"保留
- **三层架构**：印象 → 模式 → 原则，从原始记忆自动蒸馏为可指导决策的认知
- **多信号共振**：语义 + 关键词 + 实体图谱 + 时序锚定 + 访问热度，五路融合检索
- **零依赖部署**：默认 SQLite + FTS5，无需 Neo4j、pgvector 等外部依赖

## 快速开始

```bash
# 安装
pip install -e .

# 作为 MCP 服务运行
MNEMOS_DB_PATH=./memory.db python -m mnemos.mcp.server

# 或直接在代码中使用
```

```python
from mnemos.storage.palimpsest import PalimpsestStore
from mnemos.retrieval.resonance import ResonanceEngine
from mnemos.core.models import MemoryEntry, MemoryQuery, ScopeType

# 初始化
store = PalimpsestStore("memory.db")
store.connect()

# 写入记忆
entry = MemoryEntry(
    title="小米股价大涨",
    content="2026年6月7日，小米集团股价上涨5.2%",
    scope=ScopeType.TENANT,
    scope_id="user_001",
    tags=["小米", "股价"],
)
store.inscribe(entry)

# 检索记忆
engine = ResonanceEngine(store)
results = engine.search(MemoryQuery(query_text="小米股价"))
for r in results:
    print(f"{r.entry.title} — 共振得分: {r.resonance_score:.2f}")
```

## 架构

```
┌──────────────────────────────────────┐
│           MCP 协议层                  │
│   mnemos_remember / mnemos_recall    │
├──────────────────────────────────────┤
│   Resonance 检索引擎                  │
│   语义 + 关键词 + 实体 + 时序 + 热度  │
├──────────────────────────────────────┤
│   Palimpsest 存储引擎                 │
│   impressions → patterns → principles│
├──────────────────────────────────────┤
│   SQLite + FTS5（零配置）             │
└──────────────────────────────────────┘
```

## 功能

| 功能 | 说明 |
|------|------|
| `mnemos_remember` | 写入记忆 |
| `mnemos_recall` | 多信号检索 |
| `mnemos_revise` | 修正信念（保留历史） |
| `mnemos_condense` | 印象→模式→原则自动蒸馏 |
| `mnemos_stats` | 记忆统计 |
| 范围隔离 | Universe / Tenant / Persona / Session 四级 |
| 实体图谱 | 自动共现矩阵，实体关系可视化 |
| 记忆衰减 | 长期未访问自动衰减，归零后归档 |

## 测试

```bash
python -m pytest tests/ -v
# 12 tests passed
```

## 协议

Apache 2.0 — 开源，可商用，无附加条款。
