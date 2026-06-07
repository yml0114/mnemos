# Mnemos — 独立记忆世界

> **Memory Palimpsest（记忆重写本）** — 可移植的多层 AI 记忆系统，自带 3D 可视化仪表盘

[![Python](https://img.shields.io/badge/python-3.10+-blue)](https://python.org)
[![License](https://img.shields.io/badge/license-Apache%202.0-green)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-12%20passed-brightgreen)](tests/)
[![Version](https://img.shields.io/badge/version-0.1.0-818cf8)](pyproject.toml)

独立记忆世界是一个开源的、独立部署的 AI Agent 记忆后端。不绑定任何框架，任何 Agent 通过 MCP 协议即可接入。

**核心理念**：记忆不是数据库行，而是可以生长、关联、演化、修正的活体。旧认知不会被删除，作为"底本"保留——你总能追溯"我们曾经相信什么"以及"现在相信什么"。

---

## ✨ 特性

- 🧠 **三层记忆架构**：印象 → 模式 → 原则，自动蒸馏升级
- 🎯 **五路信号共振检索**：语义 + 关键词 + 实体图谱 + 时序锚定 + 访问热度
- 📜 **信念修正链**：信念可被推翻、修正，完整历史可追溯
- 🔒 **四级范围隔离**：Universe / Tenant / Persona / Session
- 🌌 **3D 记忆星系可视化**：Three.js 实时渲染，螺旋星云布局
- 🌳 **信念演化树**：动画展示每条信念的修正历史
- 🕸️ **实体关系图谱**：交互式共现网络探索
- 📡 **MCP 协议**：标准接口，任何 Agent 即插即用
- 🪶 **零外部依赖**：默认 SQLite + FTS5，无需 Neo4j/pgvector

---

## 🚀 快速开始

### 安装

```bash
pip install -e .
```

### 启动 3D 可视化仪表盘

```bash
mnemos-dashboard --db memory.db --port 8765
# 浏览器打开 http://localhost:8765
```

你会看到：
- 🌌 **记忆星系**：每条记忆是一颗发光的星体，印象=蓝粒子、模式=紫光环、原则=金星
- 🌳 **信念演化树**：点击星体查看信念如何被修正
- 🕸️ **实体图谱**：点击实体节点探索关联网络
- 📊 **统计面板**：实时计数 + 时间线

### 启动 MCP 服务

```bash
MNEMOS_DB_PATH=./memory.db python -m mnemos.mcp.server
```

### 代码中使用

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
    content="2026年6月7日，小米集团股价上涨5.2%，市值突破万亿",
    scope=ScopeType.TENANT,
    scope_id="user_001",
    tags=["小米", "股价", "科技股"],
)
store.inscribe(entry)

# 多信号检索
engine = ResonanceEngine(store)
results = engine.search(MemoryQuery(query_text="小米股价"))
for r in results:
    print(f"{r.entry.title} — 共振得分: {r.resonance_score:.2f}")
    print(f"  信号明细: {r.signal_breakdown}")
```

---

## 🏗️ 架构

```
┌──────────────────────────────────────────┐
│         🌌 3D 可视化仪表盘                │
│   记忆星系 · 信念树 · 实体图谱 · 统计     │
├──────────────────────────────────────────┤
│           📡 MCP 协议层                   │
│   remember / recall / revise / condense  │
├──────────────────────────────────────────┤
│         🎯 Resonance 检索引擎             │
│   语义 0.35 + 关键词 0.25 + 实体 0.20   │
│        + 时序 0.10 + 热度 0.10          │
├──────────────────────────────────────────┤
│       📜 Palimpsest 存储引擎              │
│   impressions → patterns → principles   │
├──────────────────────────────────────────┤
│      💾 SQLite + FTS5（零配置）           │
└──────────────────────────────────────────┘
```

---

## 📡 MCP 工具

| 工具 | 说明 |
|------|------|
| `mnemos_remember` | 写入一条记忆（自动归类印象层） |
| `mnemos_recall` | 多信号融合检索 |
| `mnemos_revise` | 修正信念（保留历史） |
| `mnemos_condense` | 触发蒸馏：印象→模式→原则 |
| `mnemos_stats` | 记忆世界统计 |

---

## 🧪 测试

```bash
python -m pytest tests/ -v
# 12 passed ✅
```

---

## 🗺️ 路线图

- [x] 核心存储引擎 (Palimpsest)
- [x] 多信号检索引擎 (Resonance)
- [x] 记忆蒸馏 (Alchemist)
- [x] MCP 协议服务
- [x] 3D 记忆星系可视化
- [x] 信念演化树
- [x] 实体关系图谱
- [ ] 向量检索集成 (sqlite-vec)
- [ ] 记忆提取 LLM 集成
- [ ] PyPI 发布

---

## 📄 协议

Apache 2.0 — 开源，可商用，无附加条款。

---

**Made with 🌌 by [yml0114](https://github.com/yml0114)**
