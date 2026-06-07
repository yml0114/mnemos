"""检查代词替换是否生效"""
import sys
sys.path.insert(0, '/Users/liangliang/workspace/mnemos')

from mnemos.storage.palimpsest import PalimpsestStore

store = PalimpsestStore("benchmark.db")
store.connect()

all_mem = store.all(limit=1000)

# 检查小明0的记忆
print("=== 小明0 的所有记忆 ===")
for m in all_mem:
    if "小明0" in m.content or "小明0" in str(m.tags) or m.scope_id == "user_0":
        print(f"  [{m.memory_type}] {m.content[:100]} | tags={m.tags}")

print("\n=== 包含'我喜欢'的记忆（代词未替换的泄漏）===")
count = 0
for m in all_mem:
    if "我喜欢" in m.content:
        print(f"  [{m.memory_type}] {m.content[:80]} | scope_id={m.scope_id}")
        count += 1
        if count > 5:
            break

print("\n=== 包含'红色'的记忆 ===")
count = 0
for m in all_mem:
    if "红色" in m.content:
        print(f"  [{m.memory_type}] {m.content[:80]} | scope_id={m.scope_id}")
        count += 1
        if count > 5:
            break

store.close()
