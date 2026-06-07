"""
Mnemos — 独立记忆世界
=====================

可移植的多层 AI 记忆系统，自带 3D 可视化仪表盘。

核心理念: Memory Palimpsest（记忆重写本）
- 记忆可以被修正（信念更新），旧版本作为"底本"保留
- 三层架构: 印象层(Impressions) → 模式层(Patterns) → 原则层(Principles)
- 五路信号检索: 语义 + 关键词 + 实体图谱 + 时序锚定 + 访问热度
- 3D 记忆星系可视化: Three.js 渲染，螺旋星云布局，信念演化树
- 零外部依赖部署: SQLite + FTS5，MCP 协议接入

快速开始:
    pip install -e .
    mnemos-dashboard --db memory.db --port 8765  # 3D 可视化
    MNEMOS_DB_PATH=./memory.db mnemos-server      # MCP 服务

核心模块:
    mnemos.core          — 数据模型 (MemoryEntry, MemoryTier, BeliefRecord)
    mnemos.storage       — 存储引擎 (PalimpsestStore)
    mnemos.retrieval     — 检索引擎 (ResonanceEngine) + 渐进注入 (Stager)
    mnemos.curation      — 记忆去重 (Curator) + 智能合并
    mnemos.condensation  — 记忆蒸馏 (AlchemistCondenser)
    mnemos.extraction    — 记忆提取 (ScribeExtractor)
    mnemos.integrations  — 框架集成 (LangChain, CrewAI)
    mnemos.temporal      — 时序推理 (Chronos) + 实体链接 (Nexus)
    mnemos.embedding     — 本地语义嵌入 (ONNX, 零外部API)
    mnemos.viz           — 可视化 (DashboardProvider, 3D 仪表盘)
    mnemos.mcp           — MCP 协议服务 (5 个工具)
"""

__version__ = "0.1.0"
