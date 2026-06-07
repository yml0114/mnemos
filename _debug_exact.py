"""快速诊断精确匹配为什么没生效"""
import sys
sys.path.insert(0, '/Users/liangliang/workspace/mnemos')

from mnemos.storage.palimpsest import PalimpsestStore

store = PalimpsestStore("benchmark.db")
store.connect()

# 1. 检查 FTS 能不能搜到
print("=== FTS 搜索 '小明0 红色' ===")
try:
    r = store.fts("小明0 红色", limit=5)
    for m in r:
        print(f"  FTS: {m.content[:80]} | tags={m.tags}")
except Exception as e:
    print(f"  FTS error: {e}")

# 2. 检查 all() 里的记忆内容
print("\n=== all() 前10条 ===")
all_mem = store.all(limit=10)
for m in all_mem:
    print(f"  [{m.memory_type}] {m.content[:80]} | tags={m.tags} | scope_id={m.scope_id}")

# 3. 搜索包含"红色"的记忆
print("\n=== 包含'红色'的记忆 ===")
all_mem = store.all(limit=1000)
for m in all_mem:
    if "红色" in m.content:
        print(f"  {m.content[:80]} | tags={m.tags} | scope_id={m.scope_id}")
        break

# 4. 搜索包含"小明0"的记忆
print("\n=== 包含'小明0'的记忆 ===")
count = 0
for m in all_mem:
    if "小明0" in m.content or "小明0" in str(m.tags):
        print(f"  {m.content[:80]} | tags={m.tags} | scope_id={m.scope_id}")
        count += 1
        if count >= 5:
            break

store.close()
