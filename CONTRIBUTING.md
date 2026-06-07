# 贡献指南

感谢你对 Mnemos 的关注！我们欢迎所有形式的贡献。

## 快速开始

```bash
# 克隆仓库
git clone https://github.com/yml0114/mnemos.git
cd mnemos

# 安装开发依赖
pip install -e ".[dev,all]"

# 运行测试
pytest -v
```

## 如何贡献

### 报告 Bug

1. 在 [Issues](https://github.com/yml0114/mnemos/issues) 中搜索是否已有相同问题
2. 没有的话，新建 Issue，包含：
   - 复现步骤
   - 期望行为 vs 实际行为
   - Python 版本和操作系统
   - 相关日志

### 提交代码

1. Fork 仓库
2. 创建功能分支：`git checkout -b feat/your-feature`
3. 编写代码 + 测试
4. 确保所有测试通过：`pytest -v`
5. 提交：`git commit -m "feat: 简短描述"`
6. 推送：`git push origin feat/your-feature`
7. 创建 Pull Request

### 代码规范

- **风格**：遵循 PEP 8，行宽 120
- **类型**：关键公共 API 添加类型注解
- **文档**：公共函数必须有 docstring
- **测试**：新功能必须附带测试
- **依赖**：核心模块零外部依赖（仅 pydantic + httpx + numpy + mcp）

### Commit 规范

| 前缀 | 用途 |
|-------|------|
| `feat:` | 新功能 |
| `fix:` | Bug 修复 |
| `docs:` | 文档更新 |
| `test:` | 测试相关 |
| `refactor:` | 重构 |
| `perf:` | 性能优化 |
| `chore:` | 杂项 |

## 架构概览

```
mnemos/
├── core/          数据模型（MemoryType, TemporalQueryMode）
├── storage/       存储引擎（PalimpsestStore: SQLite + FTS5）
├── retrieval/     检索引擎（ResonanceEngine: 6路融合 + BM25）
├── temporal/      时序推理（Chronos + Nexus 实体链接）
├── embedding/     语义嵌入（Hermes: ONNX → hash 降级）
├── evaluation/    评测裁判（LLMJudge + RuleJudge）
├── profile/       用户画像（Mneme）
├── condensation/  记忆蒸馏（Alchemist + LLM 智能蒸馏）
├── extraction/    记忆提取（Scribe）
├── curation/      去重合并（Curator）
├── integrations/  框架集成（LangChain, CrewAI）
├── mcp/           MCP 协议服务
└── viz/           3D 可视化仪表盘
```

## 核心原则

1. **零外部依赖部署**：核心功能不依赖 ChromaDB/Qdrant/Redis，SQLite + FTS5 即可运行
2. **渐进增强**：有 ONNX 模型用语义向量，没有则 hash 降级，始终可用
3. **可移植**：数据库就是文件，拷贝即迁移
4. **中英双语**：实体提取、分词、评测均支持中英文

## 有问题？

- 在 [Discussions](https://github.com/yml0114/mnemos/discussions) 提问
- 在 [Issues](https://github.com/yml0114/mnemos/issues) 报告 Bug

---

感谢你的贡献！ 🙏
