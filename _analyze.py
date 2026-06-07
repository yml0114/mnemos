import json

with open('/Users/liangliang/workspace/mnemos/results/20260607_203141/results.jsonl') as f:
    results = [json.loads(l) for l in f]

cats = {}
for r in results:
    c = r['category']
    if c not in cats:
        cats[c] = {'total':0, 'correct':0, 'wrong':[]}
    cats[c]['total'] += 1
    if r['correct']:
        cats[c]['correct'] += 1
    else:
        cats[c]['wrong'].append(r)

for c, d in cats.items():
    pct = d['correct']/d['total']*100 if d['total'] else 0
    print(f'{c}: {d["correct"]}/{d["total"]} = {pct:.0f}%')
    for w in d['wrong']:
        print(f'  ❌ Q: {w["question"]} | 期望: {w["expected"]} | top: {w["top_result"][:80]}')
