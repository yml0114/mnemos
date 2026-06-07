# Mnemos — 独立记忆世界

> *Memory Palimpsest — A portable multi-tier AI memory system with 6-signal fusion retrieval, temporal reasoning, belief revision, and a 3D galaxy dashboard.*

[![Python](https://img.shields.io/badge/python-3.10+-blue)](https://python.org)
[![License](https://img.shields.io/badge/license-Apache%202.0-green)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-48%20passed-brightgreen)](tests/)
[![Version](https://img.shields.io/badge/version-0.2.0-818cf8)](pyproject.toml)
[![MCP](https://img.shields.io/badge/protocol-MCP-orange)](mnemos/mcp/)

**English** | [中文](#中文)

---

Mnemos is an open-source, standalone memory backend for AI agents. It doesn't bind to any framework — any agent can connect via the MCP protocol. Think of it as a **digital hippocampus** with temporal reasoning and belief evolution.

---

## ✨ Why Mnemos?

|  | Mnemos | mem0 | supermemory | Hindsight |
|---|---|---|---|---|
| **Memory tiers** | 3-layer evolution | Flat | Flat | Multi-strategy |
| **Storage** | SQLite + FTS5 (zero-dep) | ChromaDB / Qdrant | Cloudflare | Proprietary |
| **Retrieval** | 6-signal fusion | 3-signal | Knowledge graph | Multi-strategy |
| **Temporal reasoning** | ✅ Chronos | ✅ (2026-05) | ❌ | ❌ |
| **Entity linking** | ✅ CN + EN | ✅ | ✅ | ✅ |
| **Belief revision** | ✅ 4-level confidence | ❌ | ❌ | ❌ |
| **User profiling** | ✅ Mneme | ❌ | ✅ | ❌ |
| **LLM Judge** | ✅ + Rule fallback | ✅ | ✅ | ✅ |
| **3D visualization** | ✅ Galaxy + Belief Tree | ❌ | ❌ | ❌ |
| **MCP protocol** | ✅ | ❌ | ✅ | ❌ |
| **LLM dependency** | None (works offline) | Requires embeddings | — | Requires Gemini |
| **License** | Apache 2.0 | Apache 2.0 | MIT | Proprietary |

---

## 🧠 Core Design

### Three-Tier Memory Evolution

Memories in Mnemos are not static — they **evolve**:

```
Impressions (raw)  →  Patterns (distilled)  →  Principles (eternal)
    fleeting               structured               immutable truths
```

### Six-Signal Resonance Engine

Memory recall is **signal fusion** — not just keyword matching:

| Signal | Weight | What it captures |
|---|---|---|
| **Semantic** | 35% | Meaning similarity (Hermes ONNX or hash fallback) |
| **Keyword** | 25% | Direct lexical match (FTS5) |
| **BM25** | 20% | Probabilistic keyword scoring (no ES needed) |
| **Entity** | 10% | Named entity co-occurrence (CN + EN) |
| **Temporal** | 5% | Recency, decay curves, state_key resolution |
| **Access** | 5% | Usage frequency boosting |

### Chronos Temporal Reasoning

Unlike simple recency sorting, Chronos understands **temporal intent**:

- **State queries**: "What is X?" → returns the *current* value (state_key deactivation)
- **Historical queries**: "What was X?" → returns the *past* value
- **Upcoming queries**: "What will happen?" → returns future plans
- **Change detection**: "Did X change?" → returns transition timeline
- **Duration queries**: "How long has X been?" → returns time span
- **Frequency queries**: "How often does X?" → returns occurrence patterns

### Belief Revision System

Every memory carries **belief records** with 4-level confidence:

```
Speculative → Tentative → Confirmed → Bedrock
   (10%)        (30%)       (50%)      (70%)
```

Beliefs can be **revised** — new evidence upgrades or downgrades confidence. Old beliefs are never deleted, creating an audit trail.

### Hermes Embedding Engine

Zero-API local embeddings with graceful degradation:

```
ONNX Runtime (384-dim, 24MB) → n-gram hash projection (384-dim, instant)
     ↑ needs model download          ↑ always works, no deps
```

### Nexus Entity Linking

Bilingual entity extraction — Chinese + English:

- 🇨🇳 Chinese: Surname-based name extraction, place suffixes, org patterns
- 🇺🇸 English: Capitalized name patterns, org suffixes (Inc/LLC/Ltd...), place suffixes

---

## 🚀 Quick Start

### Install

```bash
# Core (no heavy deps)
pip install mnemos

# With local embeddings
pip install mnemos[embedding]

# With LLM Judge
pip install mnemos[judge]

# Everything
pip install mnemos[all]
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
from mnemos.core.models import MemoryEntry, MemoryQuery, ScopeType

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

# Search with 6-signal resonance
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

### User Profiling

```python
from mnemos.profile import Mneme

mneme = Mneme(store)
profile = mneme.build("user-001")
print(profile.preferences)  # ["喜欢黑暗模式", "偏好极简UI"]
print(profile.projects)     # ["AI平行世界", "不尬翻译APP"]
print(mneme.summary(profile))  # Suitable for system prompt injection
```

### LLM Judge for Benchmarking

```python
from mnemos.evaluation import LLMJudge, RuleJudge

# With OpenAI API
judge = LLMJudge(api_key="sk-...", model="gpt-4o")
result = judge.judge(
    question="Where does the user live?",
    ground_truth="Shanghai",
    system_answer="Resides in Shanghai",
)
print(result["score"])  # 1.0

# Rule-based fallback (no API needed)
rule_judge = RuleJudge()
result = rule_judge.judge(
    question="Where does the user live?",
    ground_truth="Shanghai",
    system_answer="Lives in Beijing",
)
print(result["score"])  # 0.0
```

### Framework Integrations

```python
# LangChain
from mnemos.integrations.langchain import MnemosMemory
memory = MnemosMemory(scope_id="agent-001")

# CrewAI
from mnemos.integrations.crewai import MnemosCrewMemory
memory = MnemosCrewMemory(scope_id="my-crew")
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

Six MCP tools: `inscribe`, `recall`, `revise`, `obliterate`, `traverse`, `profile`

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
├── core/models.py              # MemoryEntry, BeliefRecord, SearchResult
├── storage/palimpsest.py       # SQLite + FTS5 engine, scope isolation
├── retrieval/
│   ├── resonance.py            # Six-signal fusion engine
│   ├── bm25.py                 # BM25 probabilistic keyword scoring
│   └── stager.py               # Progressive context injection (70-90% token savings)
├── curation/
│   └── __init__.py             # Jaccard + Levenshtein dedup engine
├── condensation/
│   └── alchemist.py            # Rule + LLM memory distillation
├── extraction/
│   └── scribe.py               # Auto-extract memories from conversations
├── evaluation/
│   └── __init__.py             # LLMJudge (GPT-4o) + RuleJudge (zero-dep)
├── profile/
│   └── __init__.py             # Mneme auto user profiling
├── embedding/
│   └── __init__.py             # Hermes: ONNX → hash graceful degradation
├── temporal/
│   ├── __init__.py             # Chronos temporal reasoning engine
│   └── nexus.py                # Nexus bilingual entity linking
├── integrations/
│   ├── langchain.py            # LangChain memory backend
│   └── crewai.py               # CrewAI memory backend
├── viz/
│   ├── data_provider.py        # Visualization data layer
│   └── dashboard.py            # 3D dashboard server (Three.js)
└── mcp/
    └── server.py               # MCP protocol server (6 tools)
```

---

## 🔮 Roadmap

- [x] Core storage engine (SQLite + FTS5)
- [x] Five → Six-signal resonance retrieval (+BM25)
- [x] Jaccard + Levenshtein dedup
- [x] Progressive 3-layer context injection
- [x] Chronos temporal reasoning
- [x] Nexus bilingual entity linking (CN + EN)
- [x] Hermes local embedding (ONNX → hash fallback)
- [x] LLM Judge + Rule Judge for benchmarking
- [x] Mneme auto user profiling
- [x] LLM-powered distillation (Alchemist)
- [x] 3D memory galaxy dashboard
- [x] MCP protocol server
- [x] LangChain / CrewAI integrations
- [ ] LongMemEval benchmark submission
- [ ] TypeScript SDK
- [ ] PyPI release
- [ ] MCP tools expansion (6 → 20+)
- [ ] Multi-modal memory (images, audio)

---

## 📜 License

Apache 2.0 — see [LICENSE](LICENSE)

---

*Mnemos is named after the Greek goddess of memory, mother of the Muses. The architecture is inspired by the concept of a **palimpsest** — an ancient manuscript where old text was scraped off to make room for new writing, yet traces of the original remain forever.*

---

# 中文

## Mnemos — 独立记忆世界

> *记忆重写本 — 可移植的多层 AI 记忆系统，6路信号融合检索 + 时序推理 + 信念修正 + 3D星系可视化*

---

## ✨ 为什么选 Mnemos？

| 维度 | Mnemos | mem0 | supermemory | Hindsight |
|---|---|---|---|---|
| **记忆层级** | 3层进化 | 单层 | 单层 | 多策略 |
| **检索引擎** | 6路信号融合 | 3路 | 知识图谱 | 多策略 |
| **时序推理** | ✅ Chronos | ✅ (2026-05) | ❌ | ❌ |
| **实体链接** | ✅ 中英文 | ✅ | ✅ | ✅ |
| **信念修正** | ✅ 4级置信度 | ❌ | ❌ | ❌ |
| **用户画像** | ✅ Mneme | ❌ | ✅ | ❌ |
| **LLM裁判** | ✅ + 规则降级 | ✅ | ✅ | ✅ |
| **3D可视化** | ✅ 星系+信念树 | ❌ | ❌ | ❌ |
| **LLM依赖** | 无（可离线运行） | 需嵌入模型 | — | 需Gemini |
| **协议** | Apache 2.0 | Apache 2.0 | MIT | 闭源 |

**差异化壁垒**：
1. 唯一拥有 **3D 记忆星系可视化** 的记忆系统
2. 唯一默认 **零外部依赖即可完整运行** 的方案
3. **信念修正系统** — 其他项目均无
4. **Chronos 时序推理** — 与 mem0 2026-05 版本同构，但零 LLM 依赖

---

## 🧠 核心架构

```
┌─────────────────────────────────────────────────┐
│                   Agent / App                    │
├──────────────┬──────────────┬────────────────────┤
│  LangChain   │   CrewAI     │   MCP Client        │
├──────────────┴──────────────┴────────────────────┤
│                  Mnemos Core                      │
│  ┌──────────┐ ┌──────────┐ ┌──────────────────┐  │
│  │ Scribe   │ │ Curator  │ │  Alchemist       │  │
│  │ (提取)   │ │ (去重)   │ │  (规则+LLM蒸馏)  │  │
│  └──────────┘ └──────────┘ └──────────────────┘  │
│  ┌────────────────────────────────────────────┐   │
│  │           Palimpsest Store                  │   │
│  │  Impressions │ Patterns │ Principles        │   │
│  └────────────────────────────────────────────┘   │
│  ┌────────────────────────────────────────────┐   │
│  │     Resonance Engine (6 signals)           │   │
│  │  Semantic │ Keyword │ BM25 │ Entity │ Time │   │
│  └────────────────────────────────────────────┘   │
│  ┌──────────────┐ ┌──────────┐ ┌──────────────┐  │
│  │   Chronos    │ │  Nexus   │ │   Hermes     │  │
│  │  (时序推理)  │ │(实体链接)│ │  (本地嵌入)  │  │
│  └──────────────┘ └──────────┘ └──────────────┘  │
│  ┌──────────────┐ ┌──────────┐ ┌──────────────┐  │
│  │   Mneme      │ │  Judge   │ │  3D Galaxy   │  │
│  │  (用户画像)  │ │(评测裁判)│ │  (可视化)    │  │
│  └──────────────┘ └──────────┘ └──────────────┘  │
└──────────────────────────────────────────────────┘
```

---

## 🚀 快速开始

```bash
# 核心安装（无重依赖）
pip install mnemos

# 含本地嵌入
pip install mnemos[embedding]

# 含 LLM Judge
pip install mnemos[judge]

# 全量安装
pip install mnemos[all]
```

---

## 🔮 路线图

- [x] 核心存储引擎（SQLite + FTS5）
- [x] 5→6路信号共振检索（+BM25）
- [x] Chronos 时序推理
- [x] Nexus 中英文实体链接
- [x] Hermes 本地嵌入（ONNX→hash降级）
- [x] LLM Judge + Rule Judge 评测裁判
- [x] Mneme 用户画像
- [x] Alchemist LLM 智能蒸馏
- [x] 3D 记忆星系仪表盘
- [x] MCP 协议服务
- [x] LangChain / CrewAI 集成
- [ ] LongMemEval 基准提交
- [ ] TypeScript SDK
- [ ] PyPI 发布
- [ ] MCP 工具扩展（6→20+）
- [ ] 多模态记忆（图片、音频）

---

## 📜 协议

Apache 2.0 — 详见 [LICENSE](LICENSE)

---

*Mnemos 之名取自希腊神话中的记忆女神、缪斯之母。架构灵感源于"palimpsest"（重写本）——古人刮去旧文书写新篇，旧墨却永远渗入纸背，层层叠叠，承载着时间的痕迹。*
