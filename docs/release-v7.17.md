# mnemos v7.17.0 — 无限上下文

## 核心功能：无限上下文（Auto-Condensation）

对话满 N 轮 → LLM 摘要 → 写入永久记忆（impression），查询时合并凝练摘要 + 最近原始消息 + FTS5 相关片段，实现真正的无限上下文。

### 新增 API
- `auto_condense()` — 触发自动凝练，支持 `threshold` 参数
- `get_full_context()` — 获取分层上下文（凝练摘要 + 最近 N 条消息 + FTS5 搜索结果）
- `get_uncompacted_messages()` — 获取需要凝练的旧消息
- `get_condensed_history()` — 获取会话的所有凝练记录

### MCP 工具
- `auto_condense` — 触发自动凝练
- `get_full_context` — 查询无限上下文

### Schema
- `sessions.condensed_up_to` — 追踪凝练截止时间
- `condensations` 表 — 存储凝练记录

### Bug 修复
- `conversation_fts.session_id` → `f.session_id`（FTS5 别名问题）

---

# mnemos v7.16.0 — MiMo Code 融合

## 核心功能：会话持久化层

`sessions` → `messages` → `parts` 三级结构，完整保存对话历史。

### 新增功能
- **FTS5 对话搜索** — BM25 全文检索 + snippet 高亮
- **消息上下文窗口** — `around_message()` 围绕任意消息获取前后 N 条上下文
- **实体-消息桥接** — 消息自动关联知识图谱实体
- **MCP 3 新工具** — `conversation_append`、`conversation_search`、`link_message_entities`
- **API Server** — FastAPI + Uvicorn REST API
- **Context Registry** — 上下文注册表 + 系统上下文
- **Evolve 模块** — 自演化框架
- **LightRAG 集成** — 轻量级 RAG 集成
- **State Saver** — 状态持久化

### Bug 修复
- `healer/engine.py`：列名不匹配（6 处）
- `embeddings` 表 schema 更新（vector BLOB）
- `pyproject.toml`：添加 `fastapi`/`uvicorn` 依赖

---

## 安装

```bash
pip install git+https://github.com/yml0114/mnemos.git
```

## 文档

- [README](https://github.com/yml0114/mnemos/blob/master/README.md)
- [CHANGELOG](https://github.com/yml0114/mnemos/blob/master/CHANGELOG.md)
