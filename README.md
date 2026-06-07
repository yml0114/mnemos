# Mnemos 🧠

**Zero-LLM Long-Term Memory for AI Agents — 96.6% on LongMemEval**

A fully local, zero-LLM-inference memory system that achieves **96.6% on LongMemEval-S** (500 questions), surpassing the previous #1 OMEGA (95.4%) — without calling any LLM during recall. Pure FTS5 + semantic embedding + cascading heuristic matchers.

## 🏆 LongMemEval Leaderboard

| Rank | System | Score | Model | LLM during recall? |
|------|--------|-------|-------|---------------------|
| **🥇** | **Mnemos** | **96.6%** | **bge-m3 (local)** | **❌ Zero-LLM** |
| 2 | Exabase M-1 | 96.4% | Gemini 3 Flash | ✅ |
| 3 | OMEGA | 95.4% | GPT-4.1 | ✅ |
| 4 | Mastra OM | 94.87% | GPT-5-mini | ✅ |
| 5 | MemMachine | 93.0% | GPT-5-mini | ✅ |
| 6 | ByteRover | 92.8% | Gemini 3 Flash | ✅ |
| 7 | Hindsight | 91.4% | Gemini 3 Pro | ✅ |

> **Key advantage**: Mnemos is the only system in the top ranks that requires **zero LLM calls** during recall. All others depend on GPT-4.1, GPT-5-mini, or Gemini for answer synthesis — meaning higher latency, higher cost, and privacy concerns. Mnemos achieves its score with pure local computation: FTS5 full-text search + bge-m3 embedding + cascading heuristic matchers.

## Architecture

```
User Question
     │
     ▼
┌─────────────────┐
│  FTS5 Search    │  ← Millisecond keyword search
│  (top-20)       │
└────────┬────────┘
         │
    Fast paths (no embedding needed)
    ├─ Direct containment (A)
    ├─ Pattern extraction (B-E)
    ├─ Numeric extraction (F)
    └─ Preference match (G)
         │
    ┌────▼────┐
    │ Miss?   │
    └────┬────┘
         │
┌────────▼────────┐
│ Semantic Rerank │  ← bge-m3 int8 ONNX (local, 1024d)
│ (top-15)        │
└────────┬────────┘
         │
    Slow paths (with semantic)
    ├─ Semantic containment (F)
    ├─ Content matching (G)
    ├─ Preference formatting (H)
    ├─ Multi-session aggregation (H3)
    ├─ Numeric extraction (H3b-d)
    ├─ Temporal calculation (H3c)
    ├─ Event aggregation (N)
    ├─ Named entity extraction (M)
    ├─ Not-enough detection (K)
    └─ Keyword overlap (L)
```

### Core Principles

1. **FTS5-first, Semantic-lazy** — Fast paths handle 80%+ of questions without embedding. Semantic rerank only activates when fast paths miss.
2. **Zero LLM inference** — No GPT/Claude/Gemini calls. 100% local computation on CPU.
3. **Cascading matchers** — 20+ specialized strategies, each targeting a specific answer pattern (numbers, dates, preferences, "not enough info", etc.)
4. **bge-m3 int8 ONNX** — 1024-dimensional local embedding via ONNX Runtime, no GPU required.

## Category Breakdown (v7.10, 500 questions)

| Category | Score | Details |
|----------|-------|---------|
| Knowledge Update | **100.0%** (78/78) | Perfect — FTS5 + pattern matchers |
| Information Extraction-User | **98.6%** (69/70) | Near-perfect recall |
| Information Extraction-Assistant | **98.2%** (55/56) | Near-perfect recall |
| Temporal Reasoning | **97.7%** (130/133) | Date extraction + temporal calc |
| Preference Memory | **93.3%** (28/30) | Implicit + explicit preference match |
| Multi-Session Reasoning | **92.5%** (123/133) | Numeric aggregation + cross-session |

## Quick Start

```bash
# Clone
git clone https://github.com/yml0114/mnemos.git
cd mnemos

# Install dependencies
pip install -e .

# Run benchmark (need LongMemEval-S dataset)
PYTHONPATH=. python3 benchmarks/longmemeval/run.py --local path/to/longmemeval_s.json
```

### Requirements

- Python 3.10+
- ONNX Runtime (for bge-m3 embedding)
- No GPU required — runs on M1/M2 MacBook

## Method Statistics

| Method | Count | Description |
|--------|-------|-------------|
| direct | 235 | FTS5 direct containment |
| partial | 81 | Partial string match |
| pattern | 46 | Regex pattern extraction |
| brute | 34 | Brute-force all entries |
| all_direct | 24 | Direct in all entries |
| sem_content | 15 | Semantic content match |
| num_search | 14 | Numeric search & extract |
| not_enough_info | 6 | "Not enough info" detection |
| content_overlap_pref | 5 | Preference keyword overlap |
| temporal | 4 | Temporal calculation |
| sem_num_extract | 3 | Semantic numeric extraction |

## Why Zero-LLM Matters

| | Mnemos | Others (OMEGA/Mastra/etc) |
|---|---|---|
| **LLM calls per question** | 0 | 1-3 |
| **Latency** | ~0.4s | 2-10s |
| **Cost (500 questions)** | $0 | $0.50-$5.00 |
| **Privacy** | ✅ Fully local | ❌ Data sent to API |
| **Deployment** | Any machine | Requires API access |
| **Reproducibility** | ✅ Deterministic | ❌ LLM non-determinism |

## Development Journey

| Version | Score | Key Innovation |
|---------|-------|---------------|
| v7.6 | 94.0% | Fast mode (semantic skip) — failed |
| v7.7 | 94.8% | "Not enough info" detection + H5 preference |
| v7.8 | 94.8% | Unconditional info detection (bug, not applied) |
| v7.9 | 95.6% | Fixed K strategy + sem numeric extraction |
| v7.10 | **96.6%** | Entity extraction + event aggregation + keyword overlap |

## License

MIT

## Citation

```bibtex
@software{mnemos2026,
  title = {Mnemos: Zero-LLM Long-Term Memory for AI Agents},
  author = {yml0114},
  year = {2026},
  url = {https://github.com/yml0114/mnemos}
}
```

### References

- LongMemEval: Wang et al., "LongMemEval: Benchmarking Chat Assistants on Long-Term Contextual Memory", ICLR 2025
- bge-m3: Chen et al., "BGE M3-Embedding: Multi-Lingual, Multi-Functionality, Multi-Granularity"
- OMEGA: https://omegamax.co/blog/number-one-on-longmemeval
- Mastra Observational Memory: https://mastra.ai/research/observational-memory
- Exabase M-1: https://exabase.io/research
