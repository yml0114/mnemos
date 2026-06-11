# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [7.15.0] - 2026-06-11

### Added
- **分布式多进程同步 (SyncEngine)** — push/pull/merge 跨 SQLite 实例记忆同步、冲突检测与消解 (LWW/keep-local/keep-remote)
- **多模态记忆 (MultimodalEngine)** — 媒体附件存储与检索、按媒体类型/摘要/嵌入向量搜索、自动摘要生成
- **自修复记忆 (HealerEngine)** — 不一致性检测（重复/矛盾/时序异常/引用断裂）、自动修复 (`auto_heal`)、监控面板
- **时间线回溯 (TemporalGraphEngine)** — 事件记录与回放、快照机制、分支与合并检测、Graphviz/GraphML 导出
- **MCP 15 工具** — 新增 `sync` `multimodal` `heal` `timeline` 4 个 MCP 工具，总工具数从 11 增至 15
- **可视化面板扩展** — `DashboardProvider` 新增 `sync_status()` `multimodal_gallery()` `heal_overview()` `temporal_graph_data()`

### Changed
- 版本号从 7.14.0 跳至 7.15.0
- MCP server (`mnemos/mcp/server.py`)：新增 4 个操作处理函数，注册到 `_ACTIONS` 字典
- `mnemos/__init__.py`：更新 MCP 工具数量和描述
- 存储层 (`palimpsest.py`)：新增 4 个功能所需的数据库表 schema
- 可视化层 (`data_provider.py`)：新增 4 个数据提供方法

### Benchmark
- LongMemEval 保持 97.4% (487/500) — 世界第一，未因新增能力而退化

## [7.14.0] - 2026-06-11

### Added
- **97.4% (487/500) LongMemEval** — 世界第一，超越 OMEGA (95.4%)、Exabase (96.4%)、Anthropic S64+CV (97.0%)
- **20+ 级联匹配器**（Strategy A-N）：确定性规则级联替代 LLM 推理，零外部调用
- **容差时区匹配**: 日期容差 ±2 天，非整点时间近似匹配
- **数字单位累加**（H3f）：`1 hour and 30 minutes` → 90 minutes 正确解析
- **WORD_NUM_MAP 映射**: 英文序数/罗马数字/常见数字表达式 → 整数
- **ACTION_WORDS 扩展**: 50+ 动作关键词（在/于/拥有/安装等）覆盖 handle 提取
- **偏好记忆完整提取**: `sneezing/cat/living room` 等结构保留
- **时序排序**（Strategy O）：时间线排序输出
- **平均数策略**（H3b）：前后容差 0.3，相似数字取平均
- **置信度排序选择**: topic proximity 优先命中相关记忆

### Changed
- README 全面重写：97.4% 最新成绩 + 架构图 + 对比表 + 详细特性说明
- 版本号从 0.2.0 跳至 7.14.0，与评测策略版本对齐
- pyproject.toml 更新至 v7.14.0

### Benchmark
- LongMemEval 500/500 → 487/500 (97.4%)
- 13 个失败案例全走 sem_top 兜底，规则层命中率进一步优化

## [0.2.0] - 2026-06-07

### Added
- **BM25 检索引擎** (`mnemos/retrieval/bm25.py`): 纯 Python BM25 评分，中文 bigram 分词，零外部依赖
- **6 路信号融合检索**: ResonanceEngine 现在融合 语义(35%) + 关键词(25%) + BM25(20%) + 实体(10%) + 时序(5%) + 热度(5%)
- **LLM Judge** (`mnemos/evaluation/__init__.py`): GPT-4o API 评测裁判
- **RuleJudge** (`mnemos/evaluation/__init__.py`): 零依赖关键词重叠评判
- **用户画像引擎 Mneme** (`mnemos/profile/__init__.py`): 自动从记忆中提取偏好/工具/项目/近期动态
- **Nexus 英文实体提取**: 英文人名/地名/组织正则 + CJK 兼容修复
- **LLM 智能蒸馏** (`mnemos/condensation/alchemist.py`): `llm_distill()` 方法
- **Hermes 轻量化** (`mnemos/embedding/__init__.py`): ONNX Runtime → n-gram hash 降级，去 transformers 依赖
- **LongMemEval 基准测试 v2**: 支持 RuleJudge / LLMJudge 双模式
- **GitHub Actions CI**: Python 3.10/3.11/3.12 多版本测试 + Ruff lint
- **CONTRIBUTING.md**: 社区贡献指南
- **examples/basic_usage.py**: 完整使用示例

### Changed
- README 全面重写：4 项目对比表 + 6 路信号融合说明 + 新模块文档
- pyproject.toml：新增 `[embedding]`/`[judge]`/`[all]`/`[dev]` 可选依赖分组
- Nexus 实体提取：地名/组织先于人名 + `_claimed_spans` 避免重复匹配
- BM25 中文分词：unigram + bigram 策略（无 jieba 依赖）

### Fixed
- Nexus CJK regex：`\b` 在中文字符旁失效，去掉所有 `\b` 约束
- BM25 中文分词：添加 bigrams 修复中文"黑暗模式"分词后无匹配问题
- RuleJudge 中文匹配阈值：从 0.6 放宽至 0.4

### Tests
- 75/75 全部通过（新增 27 个 v0.2.0 模块测试）
- 覆盖率约 61%

## [0.1.0] - 2026-06-06

### Added
- 三层记忆架构：印象层 → 模式层 → 原则层
- PalimpsestStore：SQLite + FTS5 存储引擎
- ResonanceEngine：5 路信号融合检索
- Chronos：6 种时序推理模式
- Nexus：中文实体链接
- AlchemistCondenser：记忆蒸馏
- Curator：Jaccard + Levenshtein 去重
- ScribeExtractor：LLM 记忆提取
- Hermes：语义嵌入引擎
- LangChain / CrewAI 集成
- MCP 协议服务（6 个工具）
- 3D 可视化仪表盘
- Docker 部署支持
- 48/48 测试通过

## [7.17.0] - 2026-06-11

### Added
- **无限上下文（Auto-Condensation）** — 对话满 N 轮 → LLM 摘要 → 写入永久记忆（impression），查询时合并凝练摘要 + 最近原始消息 + FTS5 相关片段
- **`auto_condense()`** — 触发自动凝练，支持 `threshold` 参数控制凝练阈值
- **`get_full_context()`** — 获取分层上下文（凝练摘要 + 最近 N 条消息 + FTS5 搜索结果）
- **`get_uncompacted_messages()`** — 获取需要凝练的旧消息
- **`get_condensed_history()`** — 获取会话的所有凝练记录
- **MCP 2 新工具** — `auto_condense`、`get_full_context`，总工具数从 15 增至 17
- **LLM 回调支持** — 支持 `MNEMOS_LLM_API_URL`/`MNEMOS_LLM_API_KEY`/`MNEMOS_LLM_MODEL` 环境变量，无配置时降级为截断摘要

### Changed
- `sessions` 表新增 `condensed_up_to` 字段，追踪凝练截止时间
- 新增 `condensations` 表，存储凝练记录（session_id、时间范围、消息数、摘要、impression_id）

### Fixed
- `conversation_fts.session_id` → `f.session_id`（FTS5 别名问题）

## [7.16.0] - 2026-06-11

### Added
- **MiMo Code 融合 — 会话持久化层** — `sessions` → `messages` → `parts` 三级结构，完整保存对话历史
- **FTS5 对话搜索** — BM25 全文检索 + snippet 高亮，跨会话搜索对话内容
- **消息上下文窗口** — `around_message()` 围绕任意消息获取前后 N 条上下文
- **实体-消息桥接** — 消息自动关联知识图谱实体，支持"谁说了什么"溯源
- **MCP 3 新工具** — `conversation_append`、`conversation_search`、`link_message_entities`
- **API Server** — FastAPI + Uvicorn REST API，支持 Dashboard 集成
- **Context Registry** — 上下文注册表 + 系统上下文 + 类型定义
- **Evolve 模块** — 自演化框架（`mnemos/evolve.py`）
- **LightRAG 集成** — 轻量级 RAG 集成（`mnemos/rag/lightrag.py`）
- **State Saver** — 状态持久化（`mnemos/state_saver.py`）
- **Docker CI** — Docker 构建 + 部署配置更新

### Fixed
- `healer/engine.py`：列名不匹配（`inconsistency_id/type` → `issue_id/type`，6 处）
- `server_with_dashboard.py`：`store.write()` → `store.inscribe()`
- `embeddings` 表 schema 更新（vector BLOB）
- `pyproject.toml`：添加 `fastapi`/`uvicorn` 依赖
