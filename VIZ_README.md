# 🔮 Mnemos 记忆图谱 — ECharts 可视化

交互式记忆图谱，基于 ECharts 力导向布局，暗色主题 + 发光节点 + 社区聚类。

## 截图

![图谱](https://img.shields.io/badge/ECharts-5.5-blueviolet) ![Python-3.9+-green](https://img.shields.io/badge/Python-3.9+-yellow)

## 功能

| 功能 | 说明 |
|------|------|
| 🔮 力导向图 | ECharts graph layout，社区聚类 + 实体关系 + 记忆节点 |
| 🌈 颜色编码 | 印象/上下文/核心/信念 四色分层，实体按类型着色 |
| ✨ 发光效果 | shadowBlur 渲染发光节点，选中高亮相邻 |
| 🏘️ 社区展开 | 点击展开/收起社区成员，双击切换 |
| 📊 统计面板 | 健康度、实体分布、衰减分布、标签云、PageRank Top10 |
| 📅 时间线 | Canvas 绘制记忆创建时间轴 |
| 🔍 搜索 | Ctrl+K 模糊搜索记忆/实体 |
| ⌨️ 快捷键 | 1-4 按分层筛选，T 时间线，S 统计，F 适应视图 |

## 用法

```bash
# 直接运行（需要 ~/.hermes/mnemos.db）
python3 mnemos_viz.py                    # 生成并打开浏览器
python3 mnemos_viz.py --no-open          # 仅生成 HTML
python3 mnemos_viz.py --serve            # 启动 HTTP 服务器 (端口 9730)
python3 mnemos_viz.py --verbose          # 详细输出
python3 mnemos_viz.py --output /tmp/vis.html  # 自定义输出路径
```

## 架构

```
mnemos_viz.py (独立脚本，无外部依赖)
  ├── load()          — 读取 SQLite (impressions, entity_index, entity_edges)
  ├── build()         — 构建节点+边（社区节点、实体节点、记忆节点）
  ├── compute_*       — PageRank + Label Propagation 社区检测（纯 Python）
  ├── gen_html()      — 生成 ECharts HTML（内联 CSS + JS）
  └── main()          — CLI 入口 + 可选 HTTP 服务器
```

## 依赖

- Python 3.9+（标准库即可，无第三方依赖）
- `~/.hermes/mnemos.db` — Mnemos 记忆数据库
- 浏览器访问生成的 `memory_viz.html`（ECharts 通过 CDN 加载）

## 与 Hermes 集成

此工具通过 Hermes WebUI 的 `/memory-viz` 路由提供服务：
- 路由: `hermes-webui/api/routes.py` → `memory_viz` endpoint
- API: `/api/mnemos/viz-data` → 返回 JSON 数据
- 静态: `~/.hermes/memory_viz.html` → 图谱页面
