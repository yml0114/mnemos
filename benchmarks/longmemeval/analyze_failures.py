#!/usr/bin/env python3
"""Analyze LongMemEval failures — print full question, expected answer, top_result, category for each failing result."""

import json
import sys

DATASET = "/Users/liangliang/workspace/mnemos/benchmarks/longmemeval/longmemeval_s.json"
RESULTS = "/Users/liangliang/workspace/mnemos/benchmarks/longmemeval/results/20260608_013643/results.jsonl"

# Load dataset
with open(DATASET, "r", encoding="utf-8") as f:
    questions = json.load(f)

# Load results
results = []
with open(RESULTS, "r", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line:
            results.append(json.loads(line))

print(f"Dataset has {len(questions)} questions")
print(f"Results has {len(results)} results")

# Find failures
failures = []
for i, r in enumerate(results):
    if not r.get("correct", True):
        failures.append((i, r))

print(f"\nTotal failures: {len(failures)}\n")

for idx, (i, r) in enumerate(failures):
    q = questions[i] if i < len(questions) else None
    
    print("=" * 100)
    print(f"FAILURE #{idx + 1}  (result line {i + 1})")
    print(f"Category: {r.get('category', 'N/A')}")
    print(f"Question ID: {q.get('question_id', 'N/A') if q else 'N/A'}")
    print(f"Question type: {q.get('question_type', 'N/A') if q else 'N/A'}")
    print()
    
    print(f"QUESTION TEXT:")
    print(f"{q.get('question', 'N/A') if q else 'N/A'}")
    print()
    
    print(f"EXPECTED ANSWER:")
    print(f"{r['expected']}")
    print()
    
    print(f"PREDICTED (model output):")
    print(f"'{r.get('predicted', 'N/A')}'")
    print()
    
    print(f"MATCH METHOD: {r.get('match_method', 'N/A')}")
    print()
    
    print(f"TOP_RESULT (top retrieved chunk):")
    print(f"{r.get('top_result', 'N/A')}")
    print()
    
    if q and "answer_session_ids" in q:
        print(f"ANSWER SESSION IDS: {q['answer_session_ids']}")
    print()

print("=" * 100)
print("SUMMARY:")
print("=" * 50)
print(f"{'#':>2} {'Category':<28} {'Expected Answer':<60}")
print("-" * 90)
for idx, (i, r) in enumerate(failures):
    exp = r['expected']
    exp_display = (exp[:57] + '...') if len(exp) > 60 else exp
    print(f"{idx+1:>2} {r.get('category','N/A'):<28} {exp_display:<60}")
