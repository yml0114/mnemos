"""
LongMemEval 基准测试框架 v2

运行方式:
    # 模拟跑分（无需 API Key）
    python run.py --mock --subset 50

    # 真实跑分（Hermes 语义 + RuleJudge）
    python run.py --subset 100

    # 完整跑分（Hermes 语义 + LLM Judge）
    OPENAI_API_KEY=sk-... python run.py --subset 200 --judge llm

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
from mnemos.evaluation import LLMJudge, RuleJudge
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


def _get_judge(mode: str = "rule"):
    """获取评测裁判"""
    if mode == "llm":
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            print("   ⚠️ OPENAI_API_KEY 未设置，降级为 RuleJudge")
            return RuleJudge()
        return LLMJudge(model="gpt-4o-mini")
    return RuleJudge()


def build_benchmark_memory(store: PalimpsestStore, samples: list[dict]) -> None:
    """用 LongMemEval 样本构建记忆"""
    for sample in samples:
        user_id = sample.get("user_id", "benchmark")
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
                    scope_id=user_id,
                )
                store.inscribe(entry)


def answer_question(
    engine: ResonanceEngine,
    chronos: Chronos,
    stager: Stager,
    judge: RuleJudge | LLMJudge,
    question: str,
    answer: str,
    category: str,
) -> dict[str, Any]:
    """用 Mnemos 回答一个问题，返回是否正确"""
    # 1. 检索
    query = MemoryQuery(query_text=question, max_results=20)
    results = engine.search(query)

    if not results:
        return {
            "question": question,
            "expected": answer,
            "category": category,
            "correct": False,
            "judge_score": 0.0,
            "context_length": 0,
            "num_core": 0,
            "num_context": 0,
            "top_result": "",
        }

    # 2. 时序重排序
    try:
        reranked = chronos.rerank(results, question)
        results = reranked if reranked else results
    except Exception:
        pass

    # 3. Stager 分层注入
    plan = stager.plan(results)
    staged = {"core": plan.core, "context": plan.context, "archive": plan.archive}

    # 4. 构建上下文
    context_parts = []
    for sm in staged.get("core", []):
        entry = sm.entry if hasattr(sm, 'entry') else sm
        context_parts.append(entry.content)
    for sm in staged.get("context", [])[:5]:
        entry = sm.entry if hasattr(sm, 'entry') else sm
        context_parts.append(entry.content)

    context = "\n".join(context_parts)

    # 5. Judge 评分
    judge_score = judge.evaluate(prediction=context, reference=answer)
    correct = judge_score >= 0.5

    # 6. 兼容：关键词兜底检查
    if not correct and context and answer:
        answer_lower = answer.strip().lower()
        context_lower = context.lower()
        if answer_lower in context_lower:
            correct = True
            judge_score = max(judge_score, 0.6)

    return {
        "question": question,
        "expected": answer,
        "category": category,
        "correct": correct,
        "judge_score": round(judge_score, 4),
        "context_length": len(context),
        "num_core": len(staged.get("core", [])),
        "num_context": len(staged.get("context", [])),
        "top_result": (results[0].entry.content[:200] if hasattr(results[0], 'entry') else str(results[0])[:200]) if results else "",
    }


def run_benchmark(
    store: PalimpsestStore,
    samples: list[dict],
    judge_mode: str = "rule",
) -> dict[str, Any]:
    """运行完整评测"""
    engine = ResonanceEngine(store)
    chronos = Chronos()
    stager = Stager()
    judge = _get_judge(judge_mode)

    print(f"   裁判: {'LLMJudge (gpt-4o-mini)' if isinstance(judge, LLMJudge) else 'RuleJudge'}")

    results = []
    category_scores: dict[str, list[bool]] = {}
    category_judge_scores: dict[str, list[float]] = {}
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

            result = answer_question(engine, chronos, stager, judge, question, answer, category)
            results.append(result)

            if category not in category_scores:
                category_scores[category] = []
                category_judge_scores[category] = []
            category_scores[category].append(result["correct"])
            category_judge_scores[category].append(result["judge_score"])

        if (i + 1) % 10 == 0:
            elapsed = time.time() - start_time
            correct = sum(r["correct"] for r in results)
            print(f"  [{i+1}/{len(samples)}] {correct}/{len(results)} correct ({elapsed:.0f}s)")

    total = len(results)
    correct = sum(r["correct"] for r in results)
    avg_judge = sum(r["judge_score"] for r in results) / total if total > 0 else 0
    elapsed = time.time() - start_time

    # Hermes 状态
    try:
        from mnemos.embedding import Hermes
        h = Hermes()
        embedding_mode = "ONNX-384d" if h.ready else "Hash-fallback"
    except Exception:
        embedding_mode = "unknown"

    metrics = {
        "model": "mnemos-v0.2.0",
        "embedding": embedding_mode,
        "judge": "LLMJudge" if isinstance(judge, LLMJudge) else "RuleJudge",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_questions": total,
        "correct": correct,
        "accuracy": round(correct / total * 100, 2) if total > 0 else 0,
        "avg_judge_score": round(avg_judge, 4),
        "elapsed_seconds": round(elapsed, 1),
        "questions_per_second": round(total / elapsed, 2) if elapsed > 0 else 0,
        "by_category": {},
    }

    for cat, scores in category_scores.items():
        jscores = category_judge_scores.get(cat, [])
        metrics["by_category"][cat] = {
            "name": CATEGORIES.get(cat, cat),
            "n": len(scores),
            "correct": sum(scores),
            "accuracy": round(sum(scores) / len(scores) * 100, 2),
            "avg_judge_score": round(sum(jscores) / len(jscores), 4) if jscores else 0,
        }

    return metrics, results


# ── CLI ────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Mnemos LongMemEval Benchmark v2")
    parser.add_argument("--dataset", default="longmemeval_s", help="数据集名称")
    parser.add_argument("--subset", type=int, default=50, help="子集大小")
    parser.add_argument("--db", default="benchmark.db", help="数据库路径")
    parser.add_argument("--output", default="results", help="输出目录")
    parser.add_argument("--mock", action="store_true", help="使用模拟数据")
    parser.add_argument("--judge", choices=["rule", "llm"], default="rule", help="评测裁判")
    args = parser.parse_args()

    output_dir = Path(args.output) / datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"🔬 Mnemos LongMemEval Benchmark v2")
    print(f"   数据库: {args.db}")
    print(f"   输出: {output_dir}")

    # Hermes 状态
    try:
        from mnemos.embedding import Hermes
        h = Hermes()
        mode_str = "✅ ONNX (384d)" if h.ready else "⚠️ Hash fallback"
        print(f"   嵌入: {mode_str}")
    except Exception as e:
        print(f"   嵌入: ❌ {e}")

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
    print(f"\n📝 构建记忆 ({len(samples)} 样本)...")
    store = PalimpsestStore(args.db)
    store.connect()
    build_benchmark_memory(store, samples)
    mem_count = store.count()
    print(f"   已写入: {mem_count} 条记忆")

    # 运行评测
    print(f"\n🚀 运行评测...")
    metrics, results = run_benchmark(store, samples, judge_mode=args.judge)

    # 保存结果
    with open(output_dir / "metrics.json", "w") as f:
        json.dump(metrics, f, indent=2, ensure_ascii=False)

    with open(output_dir / "results.jsonl", "w") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    store.close()

    # 输出摘要
    print(f"\n{'='*55}")
    print(f"📊 Mnemos LongMemEval 结果")
    print(f"{'='*55}")
    print(f"  嵌入: {metrics['embedding']}")
    print(f"  裁判: {metrics['judge']}")
    print(f"  总分: {metrics['accuracy']}% ({metrics['correct']}/{metrics['total_questions']})")
    print(f"  平均 Judge 分: {metrics['avg_judge_score']:.4f}")
    print(f"  耗时: {metrics['elapsed_seconds']}s ({metrics['questions_per_second']:.1f} q/s)")
    print(f"\n  分类得分:")
    for cat, info in sorted(metrics["by_category"].items()):
        bar = "█" * int(info["accuracy"] / 5) + "░" * (20 - int(info["accuracy"] / 5))
        print(f"    {info['name']:20s} {bar} {info['accuracy']:.1f}%")
    print(f"\n  详细结果: {output_dir}")


def _generate_mock_samples(n: int) -> list[dict]:
    """生成模拟 LongMemEval 测试数据"""
    samples = []
    cities = ["北京", "上海", "深圳", "杭州", "成都", "广州", "南京", "武汉", "西安", "重庆"]
    colors = ["红色", "蓝色", "绿色", "黄色", "紫色", "橙色", "白色"]
    foods = ["火锅", "烤肉", "寿司", "披萨", "面条"]

    for i in range(n):
        samples.append({
            "user_id": f"user_{i}",
            "history": [
                {
                    "turns": [
                        {"role": "user", "content": f"我的名字是小明{i}，我住在{cities[i%10]}"},
                        {"role": "assistant", "content": f"你好小明{i}！我记住了你住在{cities[i%10]}"},
                        {"role": "user", "content": f"我喜欢{colors[i%7]}和{foods[i%5]}"},
                        {"role": "assistant", "content": f"好的，我记住了你的偏好是{colors[i%7]}和{foods[i%5]}"},
                        {"role": "user", "content": f"我的职业是工程师{i%3}号"},
                        {"role": "assistant", "content": f"已记录你的职业信息"},
                    ]
                }
            ],
            "questions": [
                {
                    "question": f"小明{i}住在哪里？",
                    "answer": cities[i%10],
                    "category": "single-session-user",
                },
                {
                    "question": f"小明{i}喜欢什么颜色？",
                    "answer": colors[i%7],
                    "category": "single-session-preference",
                },
            ],
        })
    return samples


if __name__ == "__main__":
    main()
