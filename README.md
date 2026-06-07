# Mnemos — 独立记忆世界

> *Memory Palimpsest — A portable multi-tier AI memory system with FTS5-first cascading retrieval, temporal reasoning, belief revision, and a 3D galaxy dashboard.*

[![CI](https://github.com/yml0114/mnemos/actions/workflows/ci.yml/badge.svg)](https://github.com/yml0114/mnemos/actions)
[![Python](https://img.shields.io/badge/python-3.9+-blue)](https://python.org)
[![License](https://img.shields.io/badge/license-Apache%202.0-green)](LICENSE)
[![LongMemEval](https://img.shields.io/badge/LongMemEval-94.8%25-gold)](benchmarks/longmemeval/)
[![Zero LLM](https://img.shields.io/badge/LLM-Zero-brightgreen)](mnemos/)
[![MCP](https://img.shields.io/badge/protocol-MCP-orange)](mnemos/mcp/)

**English** | [中文](#中文)

---

Mnemos is an open-source, standalone memory backend for AI agents. It doesn't bind to any framework — any agent can connect via the MCP protocol. Think of it as a **digital hippocampus** with temporal reasoning and belief evolution.

---

## 🏆 LongMemEval Benchmark

**94.8% on LongMemEval full 6-category evaluation (ICLR 2025)** — closing in on OMEGA (95.4%) with **zero LLM dependency**.

| Category | Mnemos | OMEGA | Mastra | Hindsight |
|---|---|---|---|---|
| **Knowledge Updates** | **100%** | 96% | 96.2% | — |
| **Multi-Session Reasoning** | 88.7% | 83% | 87.2% | — |
| **Information Extraction (Assistant)** | **98.2%** | — | — | — |
| **Preference Memory** | 93.3% | 100% | 100% | — |
| **Information Extraction (User)** | **97.1%** | — | 93.7% | — |
| **Temporal Reasoning** | **95.5%** | 94% | 95.5% | — |
| **Overall** | **94.8%** | 95.4% | 94.87% | 91.4% |

> Evaluated on LongMemEval-S (500 questions, 6 categories). Mnemos is the only zero-LLM system approaching OMEGA's score — and still improving.

**Why Mnemos wins:**
- 🚫 **Zero LLM** — no GPT, no Gemini, no API calls, $0 cost
- ⚡ **2.5 q/s** — comparable to LLM-based systems but with zero API cost
- 🧱 **Pure SQLite** — no ChromaDB, no Qdrant, no Redis, no cloud
- 🎯 **FTS5-first cascading** — exact match → partial → semantic, only calling embeddings as last resort
- 🧠 **Smart extractors** — topic-aware money aggregation, temporal math, implicit preference inference

### FTS5-First + Lazy Semantic Architecture

Mnemos uses a **cascading strategy pipeline** that tries the cheapest method first and only escalates when needed:

```
Strategy A: Direct FTS5 match (zero compute)     → 47% of questions solved
Strategy B: Partial / substring match              → 16% solved
Strategy C: Regex pattern extraction               → 9% solved
Strategy D: Brute-force all entries                → 7% solved
Strategy E: Semantic rerank (bge-m3 int8)          → 6% solved  ← lazy, only when A-D fail
Strategy F: All-entries direct scan                → 5% solved
Strategy G: Numerical search + aggregation          → 3% solved
Strategy H: Implicit preference + content overlap   → 4% solved
Strategy K: Abstention detection (not enough info)  → 3% solved
```

This means **94% of questions are answered without any embedding computation**, making Mnemos both fast and cheap.

### Reproduce

```bash
git clone https://github.com/yml0114/mnemos.git && cd mnemos
pip install -e ".[embedding]"
PYTHONPATH=. python3 benchmarks/longmemeval/run.py --local benchmarks/longmemeval/longmemeval_s.json
# Expected: 94.8%+ accuracy on 500 questions
```

---

## ✨ Why Mnemos?

|  | Mnemos | OMEGA | Mastra | Mem0 | Hindsight |
|---|---|---|---|---|---|
| **LongMemEval** | **94.8%** | 95.4% | 94.87% | ~85% | 91.4% |
| **LLM dependency** | **None** | GPT-4.1 | GPT-5-mini | Gemini Pro | Gemini Pro |
| **Cost per query** | **$0** | ~$0.003 | ~$0.002 | ~$0.005 | ~$0.005 |
| **Speed** | **2.5 q/s** | ~2 q/s | ~2 q/s | ~1 q/s | ~1 q/s |
| **Memory tiers** | 3-layer evolution | Flat | Flat | Flat | Multi-strategy |
| **Storage** | SQLite + FTS5 (zero-dep) | SQLite | SQLite | ChromaDB/Qdrant | Proprietary |
| **Retrieval** | FTS5-first cascade | Semantic | Observation | 3-signal | Multi-strategy |
| **Temporal reasoning** | ✅ Chronos | ✅ | ✅ | ✅ (2026-05) | ❌ |
| **Entity linking** | ✅ CN + EN | ✅ | ✅ | ✅ | ✅ |
| **Belief revision** | ✅ 4-level confidence | ❌ | ❌ | ❌ | ❌ |
| **3D visualization** | ✅ Galaxy + Belief Tree | ❌ | ❌ | ❌ | ❌ |
| **MCP protocol** | ✅ | ❌ | ❌ | ❌ | ❌ |
| **License** | Apache 2.0 | MIT | OSS | Apache 2.0 | Proprietary |
| **Funding** | $0 | $0 | $13M | $10M+ | $0 |

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

### Atomic Fact Architecture (v0.3.0)

Each memory is decomposed into **atomic facts** — one fact per entry:

```
"我喜欢红色和火锅" →  "小明0喜欢红色" (preference, state_key=小明0_color)
                      "小明0喜欢火锅" (preference, state_key=小明0_food)
```

Benefits:
- **Exact match**: person + answer keyword → instant retrieval, zero noise
- **Scope isolation**: each fact tagged with user_id + entity, no cross-contamination
- **Pronoun resolution**: "我" → "小明0", "你" → resolved to entity name
- **State tracking**: same state_key → old fact auto-deactivated

### Chronos Temporal Reasoning

Unlike simple recency sorting, Chronos understands **temporal intent**:

- **State queries**: "What is X?" → returns the *current* value (state_key deactivation)
- **Historical queries**: "What was X?" → returns the *past* value
- **Upcoming queries**: "What will happen?" → returns future plans
- **Change detection**: "Did X change?" → returns transition timeline

### Belief Revision System

Every memory carries **belief records** with 4-level confidence:

```
Speculative → Tentative → Confirmed → Bedrock
   (10%)        (30%)       (50%)      (70%)
```

### Hermes Embedding Engine

Zero-API local embeddings with graceful degradation:

```
bge-m3 ONNX int8 (1024-dim, 558MB) → n-gram hash projection (384-dim, instant)
     ↑ best accuracy, multilingual        ↑ always works, no deps
```

### Nexus Entity Linking

Bilingual entity extraction — Chinese + English:

- 🇨🇳 Chinese: Surname-based name extraction, place suffixes, org patterns
- 🇺🇸 English: Capitalized name patterns, org suffixes (Inc/LLC/Ltd...), place suffixes

---

## 🚀 Quick Start

### Install

```bash
pip install mnemos            # Core (no heavy deps)
pip install mnemos[embedding] # With local embeddings
pip install mnemos[judge]     # With LLM Judge
pip install mnemos[all]       # Everything
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

### MCP Protocol

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
│   └── stager.py               # Progressive context injection
├── curation/__init__.py        # Jaccard + Levenshtein dedup
├── condensation/alchemist.py   # Rule + LLM memory distillation
├── extraction/scribe.py        # Auto-extract memories from conversations
├── evaluation/__init__.py      # LLMJudge + RuleJudge (zero-dep)
├── profile/__init__.py         # Mneme auto user profiling
├── embedding/__init__.py       # Hermes: bge-m3 ONNX → hash fallback
├── temporal/
│   ├── __init__.py             # Chronos temporal reasoning engine
│   └── nexus.py                # Nexus bilingual entity linking
├── integrations/
│   ├── langchain.py            # LangChain memory backend
│   └── crewai.py               # CrewAI memory backend
├── viz/
│   ├── data_provider.py        # Visualization data layer
│   └── dashboard.py            # 3D dashboard server (Three.js)
├── mcp/server.py               # MCP protocol server (6 tools)
└── benchmarks/longmemeval/
    └── run.py                  # LongMemEval benchmark runner
```

---

## 🔮 Roadmap

- [x] Core storage engine (SQLite + FTS5)
- [x] Six-signal resonance retrieval (+BM25)
- [x] Jaccard + Levenshtein dedup
- [x] Progressive 3-layer context injection
- [x] Chronos temporal reasoning
- [x] Nexus bilingual entity linking (CN + EN)
- [x] Hermes local embedding (bge-m3 ONNX → hash fallback)
- [x] LLM Judge + Rule Judge for benchmarking
- [x] Mneme auto user profiling
- [x] LLM-powered distillation (Alchemist)
- [x] 3D memory galaxy dashboard
- [x] MCP protocol server
- [x] LangChain / CrewAI integrations
- [x] **LongMemEval 94.8% — full 6-category, zero LLM, closing in on OMEGA**
- [ ] LongMemEval 96%+ (surpass OMEGA)
- [ ] LongMemEval leaderboard submission
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

> *记忆重写本 — 可移植的多层 AI 记忆系统，FTS5优先级联检索 + 时序推理 + 信念修正 + 3D星系可视化*

---

## 🏆 LongMemEval 基准测试

**LongMemEval (ICLR 2025) 94.8% 准确率** — 零 LLM 逼近 OMEGA (95.4%)。

| 类别 | Mnemos | OMEGA | Mastra | Hindsight |
|---|---|---|---|---|
| **知识更新** | **100%** | 96% | 96.2% | — |
| **多会话推理** | 88.7% | 83% | 87.2% | — |
| **信息提取-助手** | **98.2%** | — | — | — |
| **偏好记忆** | 93.3% | 100% | 100% | — |
| **信息提取-用户** | **97.1%** | — | 93.7% | — |
| **时序推理** | **95.5%** | 94% | 95.5% | — |
| **总分** | **94.8%** | 95.4% | 94.87% | 91.4% |

> 基于 LongMemEval-S (500题, 6类) 评测。Mnemos 是唯一零 LLM 接近 OMEGA 的系统，且仍在快速迭代。

**Mnemos 为什么赢：**
- 🚫 **零 LLM** — 不花一分钱，不需要任何 API Key
- ⚡ **2.5 q/s** — 与 LLM 系统相当，但零 API 成本
- 🧱 **纯 SQLite** — 不需要 ChromaDB、Qdrant、Redis
- 🎯 **FTS5优先级联** — 精确匹配 → 部分 → 语义，嵌入只在最后兜底
- 🧠 **智能提取器** — 话题感知金额聚合、时序计算、隐含偏好推理

### 复现

```bash
git clone https://github.com/yml0114/mnemos.git && cd mnemos
pip install -e ".[embedding]"
PYTHONPATH=. python3 benchmarks/longmemeval/run.py --local benchmarks/longmemeval/longmemeval_s.json
# 预期: 94.8%+ 准确率 (500题)
```

---

## ✨ 为什么选 Mnemos？

| 维度 | Mnemos | OMEGA | Mastra | Mem0 | Hindsight |
|---|---|---|---|---|---|
| **LongMemEval** | **94.8%** | 95.4% | 94.87% | ~85% | 91.4% |
| **LLM 依赖** | **无** | GPT-4.1 | GPT-5-mini | Gemini Pro | Gemini Pro |
| **单次成本** | **$0** | ~$0.003 | ~$0.002 | ~$0.005 | ~$0.005 |
| **速度** | **2.5 q/s** | ~2 q/s | ~2 q/s | ~1 q/s | ~1 q/s |
| **记忆层级** | 3层进化 | 单层 | 单层 | 单层 | 多策略 |
| **存储** | SQLite（零依赖） | SQLite | SQLite | ChromaDB | 闭源 |
| **检索策略** | FTS5级联 | 语义 | 观察 | 3路信号 | 多策略 |
| **时序推理** | ✅ Chronos | ✅ | ✅ | ✅ | ❌ |
| **信念修正** | ✅ 4级置信度 | ❌ | ❌ | ❌ | ❌ |
| **3D可视化** | ✅ 星系+信念树 | ❌ | ❌ | ❌ | ❌ |
| **MCP协议** | ✅ | ❌ | ❌ | ❌ | ❌ |
| **资金** | $0 | $0 | $13M | $10M+ | $0 |

---

## 🚀 快速开始

```bash
pip install mnemos            # 核心安装
pip install mnemos[embedding] # 含本地嵌入
pip install mnemos[all]       # 全量安装
```

---

## 🔮 路线图

- [x] 核心存储引擎（SQLite + FTS5）
- [x] 6路信号共振检索（+BM25）
- [x] Chronos 时序推理 + Nexus 实体链接
- [x] Hermes 本地嵌入（bge-m3 ONNX）
- [x] 3D 记忆星系仪表盘 + MCP 协议
- [x] **LongMemEval 94.8% — 全6类评测，零LLM，逼近OMEGA**
- [ ] LongMemEval 96%+（超越 OMEGA）
- [ ] LongMemEval 排行榜提交
- [ ] TypeScript SDK + PyPI 发布
- [ ] MCP 工具扩展（6→20+）
- [ ] 多模态记忆（图片、音频）

---

## 📜 协议

Apache 2.0 — 详见 [LICENSE](LICENSE)

---

*Mnemos 之名取自希腊神话中的记忆女神、缪斯之母。架构灵感源于"palimpsest"（重写本）——古人刮去旧文书写新篇，旧墨却永远渗入纸背，层层叠叠，承载着时间的痕迹。*
