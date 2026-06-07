# Mnemos — 独立记忆世界

> *Memory Palimpsest（记忆重写本）— A portable multi-tier AI memory system with a 3D galaxy dashboard.*

[![Python](https://img.shields.io/badge/python-3.10+-blue)](https://python.org)
[![License](https://img.shields.io/badge/license-Apache%202.0-green)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-26%20passed-brightgreen)](tests/)
[![Version](https://img.shields.io/badge/version-0.1.0-818cf8)](pyproject.toml)
[![Docker](https://img.shields.io/badge/docker-ready-2496ED)](Dockerfile)
[![MCP](https://img.shields.io/badge/protocol-MCP-orange)](mnemos/mcp/)

**English** | [中文](#中文)

---

Mnemos is an open-source, standalone memory backend for AI agents. It doesn't bind to any framework — any agent can connect via the MCP protocol. Think of it as a "digital hippocampus" that helps your agents remember, evolve, and see their memories in 3D.

---

## ✨ Why Mnemos?

|  | Mnemos | mem0 | agentmemory | supermemory |
|---|---|---|---|---|
| **Memory tiers** | 3-layer evolution | Flat | Archival + recall | Flat |
| **Storage** | SQLite + FTS5 (zero-dep) | ChromaDB / Qdrant | Supabase | Cloudflare |
| **Dedup** | Jaccard + Levenshtein | Hash + cosine | — | — |
| **Context injection** | 3-layer progressive Stager | Top-K | Layered | Top-K |
| **3D visualization** | ✅ Galaxy + Belief Tree | ❌ | ❌ | ❌ |
| **MCP protocol** | ✅ | ❌ | ✅ | ✅ |
| **Framework integrations** | LangChain + CrewAI | 21 integrations | 50+ tools | Browser extension |
| **LLM dependency** | None (works without LLM) | Requires embeddings | Requires OpenAI | — |
| **License** | Apache 2.0 | Apache 2.0 | MIT | MIT |

---

## 🧠 Core Design

### Three-Tier Memory Evolution

Memories in Mnemos are not static — they **evolve**:

```
Impressions (raw)  →  Patterns (distilled)  →  Principles (eternal)
    fleeting               structured               immutable truths
```

- **Impressions**: Raw conversation fragments, ephemeral by nature
- **Patterns**: Distilled recurring themes — habits, preferences, routines
- **Principles**: Core beliefs that survive decay, the "soul" of the agent

### Four-Level Scope Isolation

```
Universe  →  Tenant  →  Persona  →  Session
(global)     (team)      (role)       (context)
```

One database, multiple worlds. Perfect for multi-tenant / multi-agent deployments.

### Five-Signal Resonance Engine

Memory recall isn't just keyword matching — it's **signal fusion**:

| Signal | Weight | What it captures |
|---|---|---|
| **Semantic** | 35% | Meaning similarity (via embeddings or FTS) |
| **Keyword** | 25% | Direct lexical match (FTS5) |
| **Entity** | 20% | Named entity co-occurrence |
| **Temporal** | 10% | Recency and decay curves |
| **Access** | 10% | Usage frequency boosting |

---

## 🚀 Quick Start

### Install

```bash
pip install mnemos
```

### Start the memory server

```bash
mnemos-server --db memory.db --port 8760
```

### Launch the 3D dashboard

```bash
mnemos-dashboard --db memory.db --port 8765
# Open http://localhost:8765
```

### Python API

```python
from mnemos import PalimpsestStore, ResonanceEngine, Curator
from mnemos.core.models import MemoryEntry, ScopeType

store = PalimpsestStore("memory.db")
store.connect()

# Write a memory
store.inscribe(MemoryEntry(
    title="User preference",
    content="User prefers dark mode and minimal UI",
    scope=ScopeType.TENANT,
    scope_id="user-001",
    tags=["preference", "ui"],
))

# Search with resonance
engine = ResonanceEngine(store)
results = engine.search(MemoryQuery(query_text="design preferences"))

# Smart write with dedup
curator = Curator(store)
result = curator.smart_inscribe(MemoryEntry(
    title="Dark mode",
    content="User always uses dark mode",
    scope=ScopeType.TENANT,
    scope_id="user-001",
))
print(result["action"])  # "skipped" — duplicate detected!
```

### LangChain Integration

```python
from mnemos.integrations.langchain import MnemosMemory
from langchain.agents import create_react_agent

memory = MnemosMemory(scope_id="agent-001")
agent = create_react_agent(llm, tools, memory=memory)
```

### CrewAI Integration

```python
from mnemos.integrations.crewai import MnemosCrewMemory

memory = MnemosCrewMemory(scope_id="my-crew")
crew = Crew(agents=[...], tasks=[...], memory=memory)
```

### MCP Protocol

Connect any MCP-compatible client:

```json
{
  "mcpServers": {
    "mnemos": {
      "command": "mnemos-server",
      "args": ["--db", "memory.db"]
    }
  }
}
```

Five MCP tools exposed: `inscribe`, `recall`, `revise`, `obliterate`, `traverse`

---

## 🌌 3D Memory Galaxy

The dashboard renders your agent's memories as an interactive **3D spiral galaxy**:

- **Blue particles**: Impressions — flickering, ephemeral
- **Purple halos**: Patterns — stable, structured
- **Gold stars**: Principles — radiant, eternal
- **Click a star** → Belief evolution tree with confidence timeline
- **Interactive entity graph** with force-directed layout
- **Statistics panel** with decay curves and access heatmaps

Built with Three.js + UnrealBloom post-processing.

---

## 📁 Project Structure

```
mnemos/
├── core/models.py          # MemoryEntry, BeliefRecord, SearchResult
├── storage/palimpsest.py   # SQLite + FTS5 engine, scope isolation
├── retrieval/
│   ├── resonance.py        # Five-signal fusion engine
│   └── stager.py           # Progressive context injection (70-90% token savings)
├── curation/
│   └── __init__.py         # Jaccard + Levenshtein dedup engine
├── condensation/
│   └── alchemist.py        # Memory distillation (LLM-powered)
├── extraction/
│   └── scribe.py           # Auto-extract memories from conversations
├── integrations/
│   ├── langchain.py        # LangChain / LangGraph memory backend
│   └── crewai.py           # CrewAI memory backend
├── viz/
│   ├── data_provider.py    # Visualization data layer
│   └── dashboard.py        # 3D dashboard server (Three.js)
├── mcp/
│   └── server.py           # MCP protocol server
└── tests/
    ├── test_palimpsest.py   # 12 core tests
    └── test_integrations.py # 14 integration tests
```

---

## 🔮 Roadmap

- [x] Core storage engine (SQLite + FTS5)
- [x] Five-signal resonance retrieval
- [x] Jaccard + Levenshtein dedup
- [x] Progressive 3-layer context injection
- [x] 3D memory galaxy dashboard
- [x] MCP protocol server
- [x] LangChain / CrewAI integrations
- [x] Docker deployment
- [ ] ONNX local embeddings (no API dependency)
- [ ] TypeScript SDK
- [ ] LongMemEval benchmark submission
- [ ] PyPI release
- [ ] MCP tools expansion (5 → 20+)

---

## 📜 License

Apache 2.0 — see [LICENSE](LICENSE)

---

## 🙏 Acknowledgments

Mnemos is named after the Greek goddess of memory, mother of the Muses. The architecture is inspired by the concept of a **palimpsest** — an ancient manuscript where old text was scraped off to make room for new writing, yet traces of the original remain forever.

---

---

# 中文

## Mnemos — 独立记忆世界

> *记忆重写本 — 可移植的多层 AI 记忆系统，自带 3D 记忆星系可视化仪表盘*

---

## ✨ 为什么选 Mnemos？

- **三层记忆进化**：印象 → 模式 → 原则，记忆不是静态存储，而是会蒸馏、会进化
- **零外部依赖**：默认 SQLite + FTS5，不绑 ChromaDB / Supabase / 任何云服务
- **五路信号检索引擎**：语义 + 关键词 + 实体 + 时间 + 访问频率，五路信号加权融合
- **四级隔离**：Universe / Tenant / Persona / Session，一份数据库支撑多租户多角色
- **智能去重**：Jaccard 相似度快速筛 → Levenshtein 编辑距离精确判 → skip / merge / insert 三策略
- **渐进式上下文注入**：3 层分层注入（核心 → 上下文 → 归档），Token 消耗削减 70-90%
- **3D 记忆星系**：Three.js + UnrealBloom 渲染，记忆粒子在螺旋星系中漂浮，点击查看信念演化
- **MCP 协议原生**：任何 MCP 兼容 Agent 零代码接入
- **LangChain / CrewAI 集成**：一行代码接入两大主流 Agent 框架
- **Docker 一键部署**：双服务编排，仪表盘 + MCP 服务开箱即用
- **Apache 2.0 开源**：完全自由使用

---

## 🚀 快速开始

```bash
# 安装
pip install mnemos

# 启动记忆服务
mnemos-server --db memory.db --port 8760

# 启动 3D 仪表盘
mnemos-dashboard --db memory.db --port 8765
# 浏览器打开 http://localhost:8765
```

详细用法见上方 English 部分。

---

## 🧠 核心架构

```
┌─────────────────────────────────────────────┐
│                 Agent / App                  │
├──────────────┬──────────────┬────────────────┤
│  LangChain   │   CrewAI     │   MCP Client   │
│  MnemosMemory│MnemosCrewMem │   (any)        │
├──────────────┴──────────────┴────────────────┤
│              Mnemos Core                      │
│  ┌──────────┐ ┌──────────┐ ┌──────────────┐ │
│  │ Scribe   │ │ Curator  │ │  Alchemist   │ │
│  │ (提取)   │ │ (去重)   │ │  (蒸馏)      │ │
│  └──────────┘ └──────────┘ └──────────────┘ │
│  ┌──────────────────────────────────────┐    │
│  │        Palimpsest Store               │    │
│  │  Impressions │ Patterns │ Principles  │    │
│  │     (FTS5)    │  (FTS5)  │   (FTS5)   │    │
│  └──────────────────────────────────────┘    │
│  ┌──────────────────────────────────────┐    │
│  │     Resonance Engine (5 signals)     │    │
│  │  Semantic │ Keyword │ Entity │ Time  │    │
│  └──────────────────────────────────────┘    │
│  ┌──────────────┐ ┌────────────────────┐     │
│  │   Stager     │ │ 3D Dashboard       │     │
│  │  (分层注入)  │ │ (记忆星系)         │     │
│  └──────────────┘ └────────────────────┘     │
└──────────────────────────────────────────────┘
```

---

## 📊 与赛道头部项目对比

| 维度 | Mnemos | mem0 | agentmemory | supermemory |
|---|---|---|---|---|
| 记忆层级 | 3层进化 | 单层 | 归档+召回 | 单层 |
| 存储引擎 | SQLite+FTS5 | ChromaDB/Qdrant | Supabase | Cloudflare |
| 去重算法 | Jaccard+编辑距离 | Hash+cosine | — | — |
| 上下文注入 | 3层渐进Stager | Top-K | 分层 | Top-K |
| 3D可视化 | ✅ 星系+信念树 | ❌ | ❌ | ❌ |
| MCP协议 | ✅ | ❌ | ✅ | ✅ |
| 框架集成 | LangChain+CrewAI | 21个 | 50+工具 | 浏览器插件 |
| LLM依赖 | 无（可选嵌入） | 需嵌入模型 | 需OpenAI | — |

**差异化壁垒：** Mnemos 是唯一拥有 3D 记忆星系可视化的记忆系统，也是唯一默认零外部依赖即可完整运行的方案。

---

## 🔮 路线图

- [x] 核心存储引擎（SQLite + FTS5）
- [x] 五路信号共振检索
- [x] Jaccard + Levenshtein 去重
- [x] 渐进式 3 层上下文注入
- [x] 3D 记忆星系仪表盘
- [x] MCP 协议服务
- [x] LangChain / CrewAI 集成
- [x] Docker 部署
- [ ] ONNX 本地嵌入（彻底摆脱 API 依赖）
- [ ] TypeScript SDK
- [ ] LongMemEval 基准测试提交
- [ ] PyPI 正式发布
- [ ] MCP 工具扩展（5 → 20+）

---

## 📜 协议

Apache 2.0 — 详见 [LICENSE](LICENSE)

---

*Mnemos 之名取自希腊神话中的记忆女神、缪斯之母。架构灵感源于"palimpsest"（重写本）——古人刮去旧文书写新篇，旧墨却永远渗入纸背，层层叠叠，承载着时间的痕迹。*
