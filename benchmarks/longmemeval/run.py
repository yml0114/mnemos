"""
LongMemEval 基准测试框架

运行方式:
    cd benchmarks/longmemeval
    pip install datasets openai
    python run.py --model gpt-4o-mini --subset 50

输出:
    results/{timestamp}/metrics.json  — 聚合指标
    results/{timestamp}/results.jsonl — 逐题结果
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# 确保 mnemos 在 path 中
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from mnemos.core.models import MemoryEntry, MemoryQuery, ScopeType
from mnemos.retrieval.resonance import ResonanceEngine
from mnemos.retrieval.stager import Stager
from mnemos.storage.palimpsest import PalimpsestStore
from mnemos.temporal import Chronos


# ── 评测配置 ──────────────────────────────────────────────

CATEGORIES = {
    "single-session-user": "信息提取-用户",
    "single-session-assistant": "信息提取-助手",
    "single-session-preference": "偏好记忆",
    "multi-session": "多会话推理",
    "temporal-reasoning": "时序推理",
    "knowledge-update": "知识更新",
}


def build_benchmark_memory(store: PalimpsestStore, samples: list[dict]) -> None:
    """用 LongMemEval 样本构建记忆"""
    for sample in samples:
        sessions = sample.get("history", sample.get("sessions", []))
        if isinstance(sessions, dict):
            sessions = list(sessions.values())

        for session in sessions:
            if isinstance(session, dict):
                turns = session.get("turns", session.get("messages", []))
            elif isinstance(session, list):
                turns = session
            else:
                continue

            for turn in turns:
                if isinstance(turn, dict):
                    role = turn.get("role", "user")
                    content = turn.get("content", str(turn))
                else:
                    content = str(turn)
                    role = "user"

                entry = MemoryEntry(
                    content=str(content)[:2000],
                    scope=ScopeType.TENANT,
                    scope_id=sample.get("user_id", "benchmark"),
                )

                store.inscribe(entry)


def answer_question(
    engine: ResonanceEngine,
    chronos: Chronos,
    stager: Stager,
    question: str,
    answer: str,
    category: str,
) -> dict[str, Any]:
    """用 Mnemos 回答一个问题，返回是否正确"""
    query = MemoryQuery(
        query_text=question,
        max_results=20,
    )

    results = engine.search(query)
    results = [r for r in results if isinstance(r, type(results[0]) if results else object)]

    # 时序重排序
    if hasattr(results[0], 'entry'):
        reranked = chronos.rerank(results, question)

    # Stager 分层注入
    plan = stager.plan(results)
    staged = {"core": plan.core, "context": plan.context, "archive": plan.archive}

    # 构建上下文
    context_parts = []
    for sm in staged.get("core", []):
        entry = sm.entry if hasattr(sm, 'entry') else sm
        context_parts.append(entry.content)
    for sm in staged.get("context", [])[:5]:
        entry = sm.entry if hasattr(sm, 'entry') else sm
        context_parts.append(entry.content)

    context = "\n".join(context_parts)

    # 简单判断：正确答案是否在召回上下文中
    correct = _check_answer_in_context(answer, context, category)

    return {
        "question": question,
        "expected": answer,
        "category": category,
        "correct": correct,
        "context_length": len(context),
        "num_core": len(staged.get("core", [])),
        "num_context": len(staged.get("context", [])),
        "top_result": results[0].entry.content[:200] if results else "",
    }


def _check_answer_in_context(answer: str, context: str, category: str) -> bool:
    """检查答案是否在召回上下文中"""
    if not answer or not context:
        return False

    answer_lower = answer.strip().lower()
    context_lower = context.lower()

    # 精确匹配
    if answer_lower in context_lower:
        return True

    # 关键词匹配（答案中每个非停用词都在上下文中）
    stopwords = {"a", "an", "the", "is", "are", "was", "were", "in", "on",
                 "at", "to", "for", "of", "and", "or", "with", "by", "from"}
    answer_words = [w for w in answer_lower.split() if w not in stopwords and len(w) > 1]

    if answer_words:
        matched = sum(1 for w in answer_words if w in context_lower)
        return matched / len(answer_words) > 0.6

    return False


def run_benchmark(
    store: PalimpsestStore,
    samples: list[dict],
    subset: int = 0,
) -> dict[str, Any]:
    """运行完整评测"""
    engine = ResonanceEngine(store)
    chronos = Chronos()
    stager = Stager()

    if subset > 0:
        samples = samples[:subset]

    results = []
    category_scores: dict[str, list[bool]] = {}
    start_time = time.time()

    for i, sample in enumerate(samples):
        questions = sample.get("questions", sample.get("qa_pairs", []))
        if isinstance(questions, dict):
            questions = list(questions.values())

        for q in questions:
            if isinstance(q, dict):
                question = q.get("question", q.get("q", ""))
                answer = q.get("answer", q.get("a", ""))
                category = q.get("category", q.get("type", "unknown"))
            else:
                continue

            result = answer_question(engine, chronos, stager, question, answer, category)
            results.append(result)

            if category not in category_scores:
                category_scores[category] = []
            category_scores[category].append(result["correct"])

        if (i + 1) % 10 == 0:
            elapsed = time.time() - start_time
            correct = sum(r["correct"] for r in results)
            print(f"  [{i+1}/{len(samples)}] {correct}/{len(results)} correct ({elapsed:.0f}s)")

    total = len(results)
    correct = sum(r["correct"] for r in results)
    elapsed = time.time() - start_time

    metrics = {
        "model": "mnemos-v0.2.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_questions": total,
        "correct": correct,
        "accuracy": round(correct / total * 100, 2) if total > 0 else 0,
        "elapsed_seconds": round(elapsed, 1),
        "questions_per_second": round(total / elapsed, 2) if elapsed > 0 else 0,
        "by_category": {},
    }

    for cat, scores in category_scores.items():
        metrics["by_category"][cat] = {
            "name": CATEGORIES.get(cat, cat),
            "n": len(scores),
            "correct": sum(scores),
            "accuracy": round(sum(scores) / len(scores) * 100, 2),
        }

    return metrics, results


# ── CLI ────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Mnemos LongMemEval Benchmark")
    parser.add_argument("--dataset", default="longmemeval_s", help="数据集名称")
    parser.add_argument("--subset", type=int, default=50, help="子集大小")
    parser.add_argument("--db", default="benchmark.db", help="数据库路径")
    parser.add_argument("--output", default="results", help="输出目录")
    parser.add_argument("--mock", action="store_true", help="使用模拟数据")
    args = parser.parse_args()

    output_dir = Path(args.output) / datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"🔬 Mnemos LongMemEval Benchmark")
    print(f"   数据库: {args.db}")
    print(f"   输出: {output_dir}")

    # 加载数据
    if args.mock:
        print("   模式: 模拟数据（无 HuggingFace）")
        samples = _generate_mock_samples(args.subset)
    else:
        try:
            from datasets import load_dataset
            print(f"   数据集: {args.dataset}")
            ds = load_dataset("lmsys/longmemeval", args.dataset, split="test", trust_remote_code=True)
            samples = [dict(s) for s in ds]
            print(f"   加载: {len(samples)} 样本")
        except Exception as e:
            print(f"   ⚠️ 无法加载 HuggingFace 数据集: {e}")
            print("   使用模拟数据")
            samples = _generate_mock_samples(args.subset)

    if args.subset > 0:
        samples = samples[:args.subset]

    # 构建记忆
    print(f"\n📝 构建记忆...")
    store = PalimpsestStore(args.db)
    store.connect()
    build_benchmark_memory(store, samples)
    mem_count = store.count()
    print(f"   已写入: {mem_count}")

    # 运行评测
    print(f"\n🚀 运行评测 ({len(samples)} 样本)...")
    metrics, results = run_benchmark(store, samples)

    # 保存结果
    with open(output_dir / "metrics.json", "w") as f:
        json.dump(metrics, f, indent=2, ensure_ascii=False)

    with open(output_dir / "results.jsonl", "w") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    store.close()

    # 输出摘要
    print(f"\n{'='*50}")
    print(f"📊 Mnemos LongMemEval 结果")
    print(f"{'='*50}")
    print(f"总分: {metrics['accuracy']}% ({metrics['correct']}/{metrics['total_questions']})")
    print(f"耗时: {metrics['elapsed_seconds']}s")
    print(f"\n分类得分:")
    for cat, info in sorted(metrics["by_category"].items()):
        bar = "█" * int(info["accuracy"] / 5) + "░" * (20 - int(info["accuracy"] / 5))
        print(f"  {info['name']:20s} {bar} {info['accuracy']:.1f}%")
    print(f"\n详细结果: {output_dir}")


def _generate_mock_samples(n: int) -> list[dict]:
    """生成模拟 LongMemEval 测试数据"""
    samples = []
    for i in range(n):
        samples.append({
            "user_id": f"user_{i}",
            "history": [
                {
                    "turns": [
                        {"role": "user", "content": f"我的名字是用户{i}，我住在城市{i%10}"},
                        {"role": "assistant", "content": f"你好用户{i}！我记住了你住在城市{i%10}"},
                        {"role": "user", "content": f"我喜欢颜色{i%7}和食物{i%5}"},
                        {"role": "assistant", "content": f"好的，我记住了你的偏好"},
                    ]
                }
            ],
            "questions": [
                {
                    "question": f"用户{i}住在哪里？",
                    "answer": f"城市{i%10}",
                    "category": "single-session-user",
                },
                {
                    "question": f"用户{i}喜欢什么颜色？",
                    "answer": f"颜色{i%7}",
                    "category": "single-session-preference",
                },
            ],
        })
    return samples


if __name__ == "__main__":
    main()
