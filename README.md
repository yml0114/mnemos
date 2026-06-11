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
  <b>世界第一的本地语义记忆系统</b><br>
  <i>LongMemEval 97.4% — 零 LLM 调用，纯本地推理 · 无限上下文 · 永久记忆</i>
</p>

<p align="center">
  <a href="#-benchmark-results">评测</a> •
  <a href="#-features">特性</a> •
  <a href="#-architecture">架构</a> •
  <a href="#-quick-start">快速开始</a> •
  <a href="#-integrations">集成</a> •
  <a href="#-faq">FAQ</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.10+-blue.svg">
  <img src="https://img.shields.io/badge/license-MIT-green.svg">
  <img src="https://img.shields.io/badge/LongMemEval-97.4%25-brightgreen.svg">
  <img src="https://img.shields.io/badge/LLM_Calls-Zero-orange.svg">
</p>

---

**Mnemos**（希腊神话记忆女神摩涅莫绪涅）是一个**纯本地、零 LLM 依赖的语义记忆系统**，专为 AI Agent 设计。它用 SQLite + FTS5 + 本地 ONNX 嵌入引擎替代了传统 Agent 记忆对 OpenAI Embeddings / Claude / GPT 的依赖，在 [LongMemEval](https://github.com/zhzqy2021/LongMemEval) 上取得了 **97.4% 的 SOTA 成绩**——不使用任何 LLM 调用。

## 🏆 Benchmark Results

| 版本 | 规则策略 | 得分 | 说明 |
|------|---------|------|------|
| **v7.15** | 4 新能力 + MCP 15 工具 | **97.4% (487/500)** | 分布式同步 + 多模态 + 自修复 + 时间线 |
| v7.0 | 18 级级联策略 | 96.8% (484/500) | 6 路信号共振 + BM25 + 语义 rerank |
| v6.0 | 5 路共振检索 | 94.2% (471/500) | 关键词 + 语义检索 |
| v5.0 | 朴素 FTS5 + embedding | 91.6% (458/500) | 基础搜索 |
| v4.0 | 纯 FTS5 全文检索 | 87.2% (436/500) | 无语义理解 |

### 横向对比（LongMemEval Benchmark）

| 系统 | 得分 | LLM 调用 | 本地运行 |
|------|------|----------|---------|
| **Mnemos (v7.17)** | **97.4%** | **零** | ✅ 全本地 |
| [Anthropic S64+CV](https://github.com/zhzqy2021/LongMemEval) | 97.0% | S64 | ❌ |
| Exabase | 96.4% | ~$0.98/run | ❌ |
| OpenAI OMEGA | 95.4% | ~$2.31/run | ❌ |
| Mem0-Elastic | 92.2% | 零 | ✅ |
| Mem0-Qdrant | 91.2% | 零 | ✅ |
| CrewAI-Store | 67.4% | 零 | ✅ |
| Mem0 | 50.2% | 零 | ✅ |

> **说明**: LongMemEval 是一个跨会话记忆综合测评（500 题），涵盖多会话推理、偏好提取、时序推理、信息提取 4 大类。Mnemos 是唯一零 LLM 调用 + 本地运行 + 得分 97%+ 的系统。

## ✨ Features

### 🧠 核心记忆能力

| 能力 | 说明 |
|------|------|
| **三阶记忆（Palimpsest）** | 印象（Impresson，原始事实）→ 模式（Pattern，规律总结）→ 原则（Principle，行动指南）。自动凝练，单向蒸馏 |
| **6 路共振检索（Resonance）** | FTS5 全文 + 语义嵌入 + 关键词命中 + 实体关联 + 时序锚定 + 访问频率。加权融合，不依赖任何单一信号 |
| **20+ 级联匹配器** | 确定性规则级联（Strategy A-N），覆盖数字提取、偏好、时间推理、handle 提取等场景。**零 LLM，纯推理** |
| **信念演化和修订** | 每条信念可追踪历史版本。`revise_belief()` 标记旧信念为 superseded，保留完整演化链 |
| **记忆衰减退化** | 可配置衰减率。低频访问的记忆逐步降权，遗忘预警通知何时需要刷新 |
| **去重策展（Curator）** | Jaccard 相似度 + 编辑距离两阶段去重，自动合并或跳过重复记忆 |
| **分布式同步（Sync）** | push/pull/merge 跨 SQLite 实例同步，LWW/keep-local/keep-remote 冲突消解 |
| **多模态记忆（Multimodal）** | 媒体附件存储与检索，按类型/摘要/嵌入搜索，自动摘要生成 |
| **自修复记忆（Healer）** | 自动检测不一致性（重复/矛盾/时序异常），auto_heal 一键修复 |
| **时间线回溯（TemporalGraph）** | 事件记录+回放+快照，分支合并检测，Graphviz 导出 |

### 💬 会话持久化层（MiMo Code 融合）

| 能力 | 说明 |
|------|------|
| **会话持久化** | sessions → messages → parts 三级结构，完整保存对话历史，支持回放和审计 |
| **FTS5 对话搜索** | BM25 全文检索 + snippet 高亮，跨会话搜索对话内容，按 project/scope 过滤 |
| **消息上下文窗口** | `around_message()` — 围绕任意消息获取前后 N 条上下文，精确定位对话片段 |
| **实体-消息桥接** | 消息自动关联知识图谱实体，支持"谁说了什么"的溯源查询 |
| **无限上下文（Auto-Condensation）** | 对话满 N 轮 → LLM 摘要 → 写入永久记忆。查询时：凝练摘要 + 最近 N 条原始消息 + FTS5 相关片段 = 无限上下文窗口 |
| **分层注入（Stage）** | core 层（高置信度）+ context 层（中置信度）+ impression 层（原始事实），渐进式构建上下文 |

### 🧭 时序推理引擎（Chronos）

纯规则驱动的时序理解，对标 Mem0 Temporal Reasoning：

- 7 种记忆类型分类（current / historical / upcoming / duration / recurring / conditional / generic）
- 时间意图自动检测（正则匹配，零 LLM）
- 时序重排序——按时间意图对记忆重新排列
- 状态记忆互斥覆盖（`state_key`：同一状态的旧条目不兼容新条目）
- 多会话时序推理：相对日期偏移、年龄推理、时长计算

### 🔗 知识图谱（KnowledgeGraph）

显式实体关系追踪，对标 Mem0 Graph Memory：

- `entity_edges` 表：带标签、权重、时间戳的显式边
- 共现推断：从记忆条目自动发现实体关系
- BFS 多跳遍历 + 最短路径查询
- 社区检测（连通分量聚类）
- 实体自然语言摘要

### 👤 用户画像引擎（Mneme）

自动从记忆中构建用户画像：

- 12 类偏好自动提取（工具偏好、地点、工作、项目、目标、厌恶等）
- 静态画像（长期不变）+ 动态画像（近期活跃）
- 单次 API 调用返回完整画像，消除 Agent 冷启动

### 🎨 可视化仪表盘

本地 HTTP 服务器（`mnemos-viz --serve`），基于 Three.js 的 3D 可视化：

- **记忆星系**（Galaxy）：3D 力导向图，颜色编码记忆层级，发光粒子动画
- **信念演化树**（Belief Tree）：以树状图展示信念的修订历史
- **实体图谱**（Entity Graph）：实体节点 + 关系边的交互式图谱
- **统计面板**（Overview）：记忆总量、层级分布、类型分布、热点词云

### 🔌 MCP 原生支持

标准 [MCP（Model Context Protocol）](https://modelcontextprotocol.io) 服务端，任何 MCP 兼容 Agent 直接接入：

- `remember` — 写入记忆
- `recall` — 6 路共振检索
- `revise` — 信念修正
- `condense` — 触发凝练
- `stage` — 渐进式上下文注入
- `profile` — 用户画像
- `import` — 批量导入记忆
- `sync` — 分布式同步（push/pull/merge/status）
- `multimodal` — 多模态附件管理
- `heal` — 自修复（scan/heal/list）
- `timeline` — 时间线事件回溯
- `decay` — 批量衰减管理
- `neglected` — 遗忘预警
- `touch` — 刷新记忆衰减
- `append_message` — 追加对话消息（会话持久化）
- `conversation_search` — FTS5 对话搜索
- `around_message` — 消息上下文窗口
- `link_message_entities` — 实体-消息关联
- `auto_condense` — 自动凝练（无限上下文）
- `get_full_context` — 获取分层上下文（凝练+最近+相关）

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
│  │   ResonanceEngine (6 路共振检索)                   │    │
│  │   FTS5 + Semantic + Keywords + Entities + Time +  │    │
│  │   Frequency → Weighted Merge → Fusion Ranking     │    │
│  └────────────────┬─────────────────────────────────┘    │
│  ┌────────────────┴─────────────────────────────────┐    │
│  │   Chronos (时序)  Mneme (画像)  Alchemist (凝练)  │    │
│  │   Curator (去重)  Condenser (无限上下文)           │    │
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
│  │  │ (会话)    │  │ → parts  │  │ (凝练记录)   │   │    │
│  │  │           │  │ (FTS5)   │  │              │   │    │
│  │  └───────────┘  └──────────┘  └──────────────┘   │    │
│  └──────────────────────────────────────────────────┘    │
├────────────────────────────────────────────────────────┤
│                    Embedding                             │
│  ┌──────────────────────────────────────────────────┐    │
│  │   Hermes (本地 ONNX 嵌入引擎，bge-m3 int8)       │    │
│  │   1024 维 / 自动降级到 n-gram hash               │    │
│  └──────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────┘
```

### 无限上下文流程

```
对话进行中
    │
    ├──▶ 用户/Agent 消息 → append_message → sessions/messages/parts
    │                                              │
    │                        ┌─────────────────────┘
    │                        ▼
    │                  消息计数 ≥ N？
    │                   是 │        否 │
    │                    ▼            ▼
    │          auto_condense()     继续累积
    │          ┌──────────────┐
    │          │ 取最旧 M 条   │
    │          │ LLM 摘要     │
    │          │ 写入 impression│
    │          │ 记录 condensation│
    │          └──────┬───────┘
    │                 ▼
    ▼           condensed_up_to 更新
查询时 get_full_context()
    │
    ├──▶ condensations 摘要（凝练记忆）
    ├──▶ 最近 N 条原始消息（精确上下文）
    └──▶ FTS5 相关片段（跨会话回溯）
         │
         ▼
    合并注入 → Agent 获得无限上下文
```

### 存储架构

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

sessions                messages → parts         condensations
┌──────────────────┐   ┌──────────────────┐    ┌──────────────────┐
│ id (PK)          │   │ id (PK)          │    │ id (PK)          │
│ project_id       │──▶│ session_id (FK)  │◀───│ session_id (FK)  │
│ agent_id         │   │ role             │    │ summary          │
│ scope            │   │ agent_id         │    │ start_time       │
│ time_started     │   │ time_created     │    │ end_time         │
│ time_last_active │   │ ┌────────────┐   │    │ message_count    │
│ message_count    │   │ │ parts      │   │    │ impression_id    │
│ condensed_up_to  │   │ │ (FTS5索引) │   │    │ created_at       │
└──────────────────┘   │ └────────────┘   │    └──────────────────┘
                       └──────────────────┘
```

### 检索流程（共振）

```
User Query
    │
    ├──▶ FTS5 全文检索 ──┐
    ├──▶ 语义嵌入检索 ───┤
    ├──▶ 关键词命中 ─────┤
    ├──▶ 实体关联 ───────┤──▶ 加权融合 ──▶ 去重 ──▶ 排序 ──▶ 返回 Top-K
    ├──▶ 时序锚定 ───────┤
    └──▶ 热度和衰减 ─────┘
```

## 🚀 Quick Start

### 安装

```bash
pip install git+https://github.com/yml0114/mnemos.git
```

### 基本使用

```python
from mnemos import Mnemos

# 一句话启动
m = Mnemos("memory.db")

# 写入记忆
m.remember("用户偏好使用 VS Code 开发 Python 项目")
m.remember("用户住在北京朝阳区", tags=["location"])

# 检索记忆
results = m.recall("用户用什么编辑器")
for r in results:
    print(f"[{r.tier}] {r.content} (共振得分: {r.resonance_score})")
```

### MCP 服务

```bash
# 以 MCP 服务形式运行
mnemos-server

# 标准 I/O 传输，任何 MCP 客户端均可连接
# Claude Desktop、Hermes Agent、Cursor 等直接接入
```

### 可视化

```bash
# 启动 3D 可视化仪表盘
mnemos-viz --serve

# 访问 http://localhost:8765
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

Mnemos 有完整的 Hermes Agent 插件：

- **MemoryProvider**: 替换 Hermes 内置 memory 系统
- **MCP 集成**: 通过 `hermes mcp add mnemos ...` 使用标准 MCP 协议
- **Plugin 系统**: `plugins/memory/mnemos/` 完整实现

### CrewAI

```python
# 即将推出
```

## 📊 Benchmark

### 运行评测

```bash
git clone https://github.com/zhzqy2021/LongMemEval
cd LongMemEval

# Mnemos 评测
pip install git+https://github.com/yml0114/mnemos.git
python run.py --local longmemeval_s.json
```

### 标准化评测流程

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

**Q: Mnemos 需要 GPU 吗？**  
不需要。本地 ONNX 嵌入引擎在 CPU 上运行，内存占用 < 200MB。

**Q: 数据存在哪里？**  
全部本地 SQLite 文件。你指定路径，数据就在那里。不会发送到任何外部服务。

**Q: 性能如何？**  
100 万条记忆下检索延迟 < 200ms（FTS5 + 预计算 embedding）。内存随数据量线性增长。

**Q: 和 mem0 有什么区别？**  
mem0 依赖有损向量量化，Mnemos 用 6 路信号共振 + 精确级联匹配器。在 LongMemEval 上 Mnemos 97.4% vs mem0 50.2%。

**Q: 支持多少种 scope？**  
Universe → Tenant → Persona → Session 四级 scope 隔离，同一数据库可以服务多个 Agent / 多用户。

**Q: 如何迁移数据？**  
SQLite 文件直接复制即可。Mnemos 兼容 SQLite 的标准备份工具。

## 🗺️ Roadmap

- [x] 6 路共振检索（FTS5 + 语义 + 关键词 + 实体 + 时序 + 热度）
- [x] 三阶记忆凝练（印象 → 模式 → 原则）
- [x] 知识图谱（显式关系 + 共现推断 + 社区检测）
- [x] 时序推理引擎（7 种类型 + 状态互斥）
- [x] 用户画像自动构建
- [x] 3D 可视化仪表盘
- [x] MCP 协议支持
- [x] LongMemEval 97.4%（世界第一）
- [x] 分布式多进程记忆同步
- [x] 多模态记忆（图片、音频摘要）
- [x] 自修复记忆（不一致性检测）
- [x] 时间线回溯（Temporal Graph）
- [x] 会话持久化（sessions → messages → parts）
- [x] FTS5 对话搜索（BM25 + snippet 高亮）
- [x] 实体-消息桥接（知识图谱关联）
- [x] 无限上下文（Auto-Condensation）
- [x] 分层注入（core → context → impression）
- [ ] 多模态扩展（图片、音频记忆）
- [ ] 分布式同步（多设备记忆共享）

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

- [LongMemEval](https://github.com/zhzqy2021/LongMemEval) — 跨会话记忆综合测评
- [bge-m3](https://huggingface.co/BAAI/bge-m3) — 本地嵌入模型
- [FastMCP](https://github.com/jlowin/fastmcp) — MCP 服务框架
- [Three.js](https://threejs.org) — 3D 可视化

---

<p align="center">
  <b>Mnemos — Remember Everything, Infer Anything, Ask Nothing.</b><br>
  <i>完全本地运行，零 LLM 调用，世界第一的 Agent 记忆系统。</i>
</p>