# Mnemos 使用示例

## 基础：存储与检索记忆

```python
from mnemos.storage import PalimpsestStore

store = PalimpsestStore("memory.db")

# 存储记忆
mem_id = store.add(
    content="用户偏好深色主题，不喜欢蓝色",
    tier="impression",
    tags=["preference", "ui"],
    state_key="theme_preference",
)

# 检索记忆
results = store.search("用户喜欢什么主题？", limit=5)
for r in results:
    print(f"[{r.tier}] {r.content} (score={r.score:.2f})")
```

## 六路信号融合检索

```python
from mnemos.storage import PalimpsestStore
from mnemos.retrieval import ResonanceEngine

store = PalimpsestStore("memory.db")
engine = ResonanceEngine(store)

# 自动融合：语义 + 关键词 + BM25 + 实体 + 时序 + 热度
results = engine.recall("上次讨论的技术方案", top_k=10)
for r in results:
    print(f"  {r.content} | signals={r.signal_breakdown}")
```

## 时序推理（Chronos）

```python
from mnemos.storage import PalimpsestStore
from mnemos.temporal import Chronos

store = PalimpsestStore("memory.db")
chronos = Chronos(store)

# 状态查询：当前值
result = chronos.query("用户的居住城市", mode="state")

# 变化查询：是否发生过改变
result = chronos.query("项目状态", mode="change")

# 历史查询：过去是什么
result = chronos.query("团队规模", mode="historical")
```

## 用户画像（Mneme）

```python
from mnemos.storage import PalimpsestStore
from mnemos.profile import Mneme

store = PalimpsestStore("memory.db")
mneme = Mneme(store)

# 自动从记忆中提取用户画像
profile = mneme.build()
print(f"偏好: {profile.preferences}")
print(f"常用工具: {profile.tools}")
print(f"参与项目: {profile.projects}")
print(f"近期动态: {profile.recent_activities}")
```

## 评测裁判（LLM Judge + Rule Judge）

```python
from mnemos.evaluation import LLMJudge, RuleJudge

# 零依赖关键词评判
judge = RuleJudge()
score = judge.evaluate(
    prediction="用户喜欢深色主题",
    reference="用户偏好暗色模式",
)
print(f"RuleJudge score: {score:.2f}")

# LLM 评判（需要 OpenAI API Key）
import os
os.environ["OPENAI_API_KEY"] = "sk-..."
judge = LLMJudge(model="gpt-4o")
score = judge.evaluate(
    prediction="用户喜欢深色主题",
    reference="用户偏好暗色模式",
)
print(f"LLMJudge score: {score:.2f}")
```

## Hermes 语义嵌入

```python
from mnemos.embedding import Hermes

# 自动检测：有 ONNX 模型用真实向量，没有则 hash 降级
hermes = Hermes()

# 获取 384 维向量
vec = hermes.embed("这段文本的语义向量")
print(f"维度: {len(vec)}, 模式: {'ONNX' if hermes.ready else 'Hash'}")
```

## MCP 协议服务

```bash
# 启动 MCP 服务
MNEMOS_DB_PATH=./memory.db mnemos-server

# 6 个工具可用：
# - mnemos_add       添加记忆
# - mnemos_search    检索记忆
# - mnemos_recall    六路融合召回
# - mnemos_profile   用户画像
# - mnemos_forget    遗忘记忆
# - mnemos_believe   更新信念
```

## 3D 可视化仪表盘

```bash
# 启动可视化
mnemos-dashboard --db memory.db --port 8765

# 浏览器打开 http://localhost:8765
# 3D 星系布局 + 信念演化树 + 时序热力图
```

## LangChain / CrewAI 集成

```python
# LangChain
from mnemos.integrations import MnemosLangChainMemory
from langchain_openai import ChatOpenAI

llm = ChatOpenAI()
memory = MnemosLangChainMemory(db_path="memory.db")

# CrewAI
from mnemos.integrations import MnemosCrewAIMemory
from crewai import Agent

agent = Agent(
    role="Researcher",
    goal="Research AI memory systems",
    memory=MnemosCrewAIMemory(db_path="memory.db"),
)
```
