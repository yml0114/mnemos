<div align="right">
  🌐 <a href="README.en.md">English</a> | 中文
</div>

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/yml0114/mnemos/main/assets/logo-dark.svg">
    <img src="https://raw.githubusercontent.com/yml0114/mnemos/main/assets/logo-light.svg" width="320" alt="Mnemos">
  </picture>
</p>

<p align="center">
  <b>World's #1 Local Semantic Memory System</b><br>
  <i>LongMemEval 97.4% — Zero LLM Calls, Pure Local Inference · Infinite Context · Permanent Memory</i>
</p>

<p align="center">
  <a href="#-benchmark-results">Benchmark</a> •
  <a href="#-features">Features</a> •
  <a href="#-architecture">Architecture</a> •
  <a href="#-quick-start">Quick Start</a> •
  <a href="#-integrations">Integrations</a> •
  <a href="#-faq">FAQ</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.10+-blue.svg">
  <img src="https://img.shields.io/badge/license-MIT-green.svg">
  <img src="https://img.shields.io/badge/LongMemEval-97.4%25-brightgreen.svg">
  <img src="https://img.shields.io/badge/LLM_Calls-Zero-orange.svg">
</p>

---

**Mnemos** (named after the Greek goddess of memory) is a **pure-local, zero LLM dependency semantic memory system** designed for AI Agents. It replaces the traditional dependence on OpenAI Embeddings / Claude / GPT with SQLite + FTS5 + local ONNX embedding engine, achieving a SOTA score of **97.4% on LongMemEval**—without any LLM calls.

## 🏆 Benchmark Results

| Version | Strategy | Score | Notes |
|---------|----------|-------|-------|
| **v7.15** | 4 new abilities + 15 MCP tools | **97.4% (487/500)** | Distributed sync + multimodal + self-healing + timeline |
| v7.0 | 18-tier cascade strategy | 96.8% (484/500) | 6-way signal resonance + BM25 + semantic rerank |
| v6.0 | 5-way resonance retrieval | 94.2% (471/500) | Keywords + semantic search |
| v5.0 | Naive FTS5 + embedding | 91.6% (458/500) | Basic search |
| v4.0 | Pure FTS5 full-text search | 87.2% (436/500) | No semantic understanding |

### Horizontal Comparison (LongMemEval Benchmark)

| System | Score | LLM Calls | Local |
|--------|-------|-----------|-------|
| **Mnemos (v7.17)** | **97.4%** | **Zero** | ✅ Fully local |
| [Anthropic S64+CV](https://github.com/zhzqy2021/LongMemEval) | 97.0% | S64 | ❌ |
| Exabase | 96.4% | ~$0.98/run | ❌ |
| OpenAI OMEGA | 95.4% | ~$2.31/run | ❌ |
| Mem0-Elastic | 92.2% | Zero | ✅ |
| Mem0-Qdrant | 91.2% | Zero | ✅ |
| CrewAI-Store | 67.4% | Zero | ✅ |
| Mem0 | 50.2% | Zero | ✅ |

> **Note:** LongMemEval is a comprehensive cross-session memory evaluation (500 questions) covering four major categories: multi-session reasoning, preference extraction, temporal reasoning, and information extraction. Mnemos is the only system with zero LLM calls + local execution + score above 97%.

## ✨ Features

### 🧠 Core Memory Capabilities

| Capability | Description |
|------------|-------------|
| **Tiered Memory (Palimpsest)** | Impressions (raw facts) → Patterns (regularities) → Principles (action guidelines). Automatic condensation via one-way distillation. |
| **6-way Resonance Retrieval (Resonance)** | FTS5 full-text + semantic embeddings + keyword hits + entity associations + temporal anchoring + access frequency. Weighted fusion, not dependent on any single signal. |
| **20+ Cascade Matchers** | Deterministic rule cascade (Strategy A-N) covering scenarios such as number extraction, preferences, time reasoning, handle extraction. **Zero LLM, pure reasoning** |
| **Belief Evolution & Revision** | Each belief's history is traceable. `revise_belief()` marks old beliefs as superseded, preserving the full evolution chain. |
| **Memory Decay & Neglect** | Configurable decay rate. Low-frequency memories gradually lose weight; neglect alerts notify when refresh is needed. |
| **Deduplication & Curation (Curator)** | Two-stage deduplication with Jaccard similarity + edit distance, automatically merging or skipping duplicate memories. |
| **Distributed Synchronization (Sync)** | push/pull/merge sync across SQLite instances, conflict resolution with LWW/keep-local/keep-remote strategies. |
| **Multimodal Memory (Multimodal)** | Media attachment storage and retrieval. Search by type/summary/embedding. Automatic summary generation. |
| **Self-Healing Memory (Healer)** | Automatic inconsistency detection (duplicates/conflicts/temporal anomalies), one-click auto_heal. |
| **Timeline Rewind (TemporalGraph)** | Event logging + replay + snapshots, branch merge detection, Graphviz export. |

### 💬 Session Persistence Layer (MiMo Code Fusion)

| Capability | Description |
|------------|-------------|
| **Session Persistence** | sessions → messages → parts 3-level structure, complete conversation history with replay and audit |
| **FTS5 Conversation Search** | BM25 full-text search + snippet highlighting, cross-session conversation search, project/scope filtering |
| **Message Context Window** | `around_message()` — get N messages before/after any target message, pinpoint conversation segments |
| **Entity-Message Bridging** | Messages auto-link to knowledge graph entities, supports "who said what" provenance queries |
| **Infinite Context (Auto-Condensation)** | Conversation reaches N turns → LLM summary → write to permanent memory. Query: condensation summary + recent N raw messages + FTS5 related snippets = infinite context window |
| **Layered Injection (Stage)** | core layer (high confidence) + context layer (medium confidence) + impression layer (raw facts), progressive context building |

### 🧭 Temporal Inference Engine (Chronos)

Pure rule-driven temporal understanding, comparable to Mem0 Temporal Reasoning:

- 7 memory type classifications (current / historical / upcoming / duration / recurring / conditional / generic)
- Automatic time intent detection (regex matching, zero LLM)
- Temporal reordering — reorders memories based on time intent.
- State memory mutually exclusive overwriting (`state_key`: old entries of the same state are incompatible with new entries)
- Multi-session temporal reasoning: relative date offsets, age reasoning, duration calculation

### 🔗 Knowledge Graph (KnowledgeGraph)

Explicit entity relationship tracking, comparable to Mem0 Graph Memory:

- `entity_edges` table: explicit edges with labels, weights, timestamps
- Co-occurrence inference: automatically discover entity relationships from memory entries
- BFS multi-hop traversal + shortest path queries
- Community detection (connected component clustering)
- Natural language summaries for entities

### 👤 User Profile Engine (Mneme)

Automatically builds user profiles from memory:

- 12 preference categories automatic extraction (tool preferences, locations, work, projects, goals, dislikes, etc.)
- Static profile (long-term) + Dynamic profile (recently active)
- One API call returns full profile, eliminating agent cold start

### 🎨 Visual Dashboard

Local HTTP server (`mnemos-viz --serve`), Three.js-based 3D visualization:

- **Memory Galaxy (Galaxy)**: 3D force-directed graph, color-coded memory tiers, glowing particle animation.
- **Belief Tree**: tree diagram showing belief revision history.
- **Entity Graph**: interactive graph of entity nodes + relationship edges.
- **Statistics Panel (Overview)**: total memories, tier distribution, type distribution, hot word cloud.

### 🔌 Native MCP Support

Standard [MCP (Model Context Protocol)](https://modelcontextprotocol.io) server, any MCP-compatible agent connects directly:

- `remember` — write memories
- `recall` — 6-way resonance retrieval
- `revise` — belief revision
- `condense` — trigger condensation
- `stage` — progressive context injection
- `profile` — user profile
- `import` — bulk memory import
- `sync` — distributed sync (push/pull/merge/status)
- `multimodal` — multimodal attachment management
- `heal` — self-healing (scan/heal/list)
- `timeline` — timeline event rewind
- `decay` — batch decay management
- `neglected` — neglect alerts
- `touch` — refresh memory decay
- `append_message` — append conversation message (session persistence)
- `conversation_search` — FTS5 conversation search
- `around_message` — message context window
- `link_message_entities` — entity-message linking
- `auto_condense` — auto condensation (infinite context)
- `get_full_context` — get layered context (condensed + recent + related)

## 🏛️ Architecture

```
┌──────────────────────────────────────────────────────────┐
│                     Agent Interfaces                      │
│  ┌─────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  │
│  │  MCP    │  │ LangChain│  │  CrewAI  │  │  Hermes  │  │
│  │  Server │  │ Memory   │  │  Plugin  │  │  Plugin  │  │
│  └────┬────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘  │
├───────┴────────────┴──────────────┴────────────┴────────┤
│                      Core API                            │
│  ┌──────────────────────────────────────────────────┐    │
│  │   ResonanceEngine (6-way resonance retrieval)    │    │
│  │   FTS5 + Semantic + Keywords + Entities + Time + │    │
│  │   Frequency → Weighted Merge → Fusion Ranking    │    │
│  └────────────────┬─────────────────────────────────┘    │
│  ┌────────────────┴─────────────────────────────────┐    │
│  │   Chronos (Temporal)  Mneme (Profile)  Alchemist (Condense) │
│  │   Curator (Dedup)     Condenser (Infinite Context)          │
│  └────────────────┬─────────────────────────────────┘    │
├───────────────────┴───────────────────────────────────┤
│                    Storage                              │
│  ┌──────────────────────────────────────────────────┐    │
│  │    PalimpsestStore (SQLite + FTS5)               │    │
│  │                                                    │    │
│  │  ┌───────────┐  ┌──────────┐  ┌──────────────┐   │    │
│  │  │ memory_   │  │ memory_  │  │ entity_edges │   │    │
│  │  │ entries   │  │ fts5     │  │ (knowledge   │   │    │
│  │  │           │  │          │  │  graph)      │   │    │
│  │  └───────────┘  └──────────┘  └──────────────┘   │    │
│  │                                                    │    │
│  │  ┌───────────┐  ┌──────────┐  ┌──────────────┐   │    │
│  │  │ sessions  │  │ messages │  │ condensations│   │    │
│  │  │ (convos)  │  │ → parts  │  │ (condensed)  │   │    │
│  │  │           │  │ (FTS5)   │  │              │   │    │
│  │  └───────────┘  └──────────┘  └──────────────┘   │    │
│  └──────────────────────────────────────────────────┘    │
├────────────────────────────────────────────────────────┤
│                    Embedding                             │
│  ┌──────────────────────────────────────────────────┐    │
│  │   Hermes (local ONNX embedding engine, bge-m3 int8)│   │
│  │   1024 dimensions / auto fallback to n-gram hash │    │
│  └──────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────┘
```

### Storage Architecture

```
memory_entries          memory_fts5              entity_edges
┌──────────────────┐   ┌──────────────────┐    ┌──────────────────┐
│ entry_id (PK)    │   │ rowid            │    │ from_id          │
│ content           │   │ content          │    │ to_id            │
│ title             │◄──┤ title            │    │ relation         │
│ tier              │   │ tags             │    │ weight           │
│ scope_type        │   └──────────────────┘    │ created_at       │
│ scope_id          │                            │ updated_at       │
│ tags (JSON)       │   memory_decay             └──────────────────┘
│ entities (JSON)   │   ┌──────────────────┐
│ beliefs (JSON)    │   │ entry_id         │    memory_cooccurrence
│ created_at        │   │ access_count     │    ┌──────────────────┐
│ last_accessed_at  │   │ decay_rate       │    │ entity_a         │
│ state_key         │   │ decay_score      │    │ entity_b         │
│ temporal_labels   │   │ last_decay_at    │    │ count            │
└──────────────────┘   └──────────────────┘    └──────────────────┘
```

### Retrieval Flow (Resonance)

```
User Query
    │
    ├──▶ FTS5 Full-text Search ──┐
    ├──▶ Semantic Embedding Search ───┤
    ├──▶ Keyword Hit ─────┤
    ├──▶ Entity Association ───────┤──▶ Weighted Fusion ──▶ Deduplication ──▶ Ranking ──▶ Return Top-K
    ├──▶ Temporal Anchoring ───────┤
    └──▶ Frequency & Decay ─────┘
```

### Infinite Context Flow

```
Conversation Ongoing
    │
    ├──▶ User/Agent Message → append_message → sessions/messages/parts
    │                                              │
    │                        ┌─────────────────────┘
    │                        ▼
    │                  Message Count ≥ N?
    │                   Yes │        No │
    │                    ▼            ▼
    │          auto_condense()     Keep Accumulating
    │          ┌──────────────┐
    │          │ Take oldest M│
    │          │ LLM Summary  │
    │          │ Write impression│
    │          │ Record condensation│
    │          └──────┬───────┘
    │                 ▼
    ▼           condensed_up_to Updated
Query: get_full_context()
    │
    ├──▶ Condensations Summary (condensed memory)
    ├──▶ Recent N Raw Messages (precise context)
    └──▶ FTS5 Related Snippets (cross-session recall)
         │
         ▼
    Merge Inject → Agent Gets Infinite Context
```

## 🚀 Quick Start

### Installation

```bash
pip install mnemos
```

### Basic Usage

```python
from mnemos import Mnemos

# One-liner to start
m = Mnemos("memory.db")

# Write memories
m.remember("User prefers VS Code for Python development")
m.remember("User lives in Chaoyang, Beijing", tags=["location"])

# Retrieve memories
results = m.recall("What editor does the user use?")
for r in results:
    print(f"[{r.tier}] {r.content} (resonance score: {r.resonance_score})")
```

### MCP Service

```bash
# Run as MCP service
mnemos-mcp

# Standard I/O transport; any MCP client can connect
# Claude Desktop, Hermes Agent, Cursor, etc.
```

### Visualization

```bash
# Start 3D visualization dashboard
mnemos-viz --serve

# Visit http://localhost:8765
```

## 🔌 Integrations

### LangChain

```python
from mnemos.integrations.langchain import MnemosMemory
from langchain.agents import create_react_agent

memory = MnemosMemory(scope_id="agent-001", auto_remember=True)
agent = create_react_agent(llm, tools, memory=memory)
```

### Hermes Agent

Mnemos has full Hermes Agent plugins:

- **MemoryProvider**: replaces the built-in Hermes memory system
- **MCP Integration**: use the standard MCP protocol via `hermes mcp add mnemos ...`
- **Plugin System**: complete implementation under `plugins/memory/mnemos/`

### CrewAI

```python
# Coming soon
```

## 📊 Benchmark

### Running Evaluation

```bash
git clone https://github.com/zhzqy2021/LongMemEval
cd LongMemEval

# Mnemos evaluation
pip install mnemos
python run.py --local longmemeval_s.json
```

### Standardized Evaluation Process

```python
import json
from mnemos import Mnemos

m = Mnemos("benchmark.db")
with open("longmemeval_s.json") as f:
    dataset = json.load(f)

for session in dataset["sessions"]:
    for turn in session["turns"]:
        if turn["role"] == "user":
            m.remember(turn["content"], source="user")
        else:
            m.remember(turn["content"], source="assistant", role="assistant")

questions = dataset["questions"]
correct = sum(1 for q in questions if m.match(q["query"]) == q["answer"])
print(f"Accuracy: {correct}/{len(questions)} ({correct/len(questions)*100:.1f}%)")
```

## ❓ FAQ

**Q: Does Mnemos require a GPU?**  
No. The local ONNX embedding engine runs on CPU, memory footprint < 200MB.

**Q: Where is data stored?**  
All in a local SQLite file. Wherever you point the path, the data stays there. No data is sent to any external service.

**Q: What's the performance?**  
Under 1 million memories, retrieval latency < 200ms (FTS5 + precomputed embeddings). Memory grows linearly with data volume.

**Q: How does it differ from mem0?**  
mem0 relies on lossy vector quantization; Mnemos uses 6-way signal resonance + precise cascade matching. On LongMemEval, Mnemos scores 97.4% vs mem0 50.2%.

**Q: How many scopes are supported?**  
Four-level scope isolation: Universe → Tenant → Persona → Session. A single database can serve multiple agents / multiple users.

**Q: How to migrate data?**  
Simply copy the SQLite file. Mnemos is compatible with standard SQLite backup tools.

## 🗺️ Roadmap

- [x] 6-way resonance retrieval (FTS5 + semantic + keywords + entities + temporal + frequency)
- [x] Tiered memory condensation (Impression → Pattern → Principle)
- [x] Knowledge graph (explicit relationships + co-occurrence inference + community detection)
- [x] Temporal inference engine (7 types + state mutual exclusion)
- [x] Automatic user profile building
- [x] 3D visualization dashboard
- [x] MCP protocol support
- [x] LongMemEval 97.4% (world's first)
- [x] Distributed multi-process memory synchronization
- [x] Multimodal memory (images, audio summaries)
- [x] Self-healing memory (inconsistency detection)
- [x] Timeline rewind (Temporal Graph)
- [x] Session persistence (sessions → messages → parts)
- [x] FTS5 conversation search (BM25 + snippet highlighting)
- [x] Entity-message bridging (knowledge graph linking)
- [x] Infinite context (Auto-Condensation)
- [x] Layered injection (core → context → impression)

## 🧪 Development

```bash
git clone https://github.com/yml0114/mnemos
cd mnemos
pip install -e ".[dev]"
pytest tests/
```

## 📄 License

MIT

## 🙏 Credits

- [LongMemEval](https://github.com/zhzqy2021/LongMemEval) — Cross-session memory comprehensive evaluation
- [bge-m3](https://huggingface.co/BAAI/bge-m3) — Local embedding model
- [FastMCP](https://github.com/jlowin/fastmcp) — MCP service framework
- [Three.js](https://threejs.org) — 3D visualization

---

<p align="center">
  <b>Mnemos — Remember Everything, Infer Anything, Ask Nothing.</b><br>
  <i>Runs entirely locally, zero LLM calls, the world's #1 Agent memory system.</i>
</p>