"""FinEcho 对抗式核验评测脚本。

读取 data/eval_cases.json 标注数据集，逐 case 运行分析图，
输出三分类混淆矩阵、per-class precision/recall/F1 与 hotspot 二分类 AUC。

用法:
    python tests/evaluate_verdicts.py
    # 或作为 pytest 运行（--no-header 关闭日志）:
    python -m pytest tests/evaluate_verdicts.py -q
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from agent.graph import build_analysis_graph
from agent.llm import OptionalPolicyLLM
from src.services.rag_service import GraphRAGService

VERDICTS = ["high_confidence", "watch", "hotspot_risk"]
# hotspot 二分类：把 high_confidence 视为负类、watch/hotspot_risk 视为正类，
# 用于评估"识别非受益/蹭热点"的鉴别能力。
HOTSPOT_POSITIVE = {"watch", "hotspot_risk"}


def _confusion(actual: list[str], predicted: list[str]) -> dict[str, dict[str, int]]:
    matrix = {a: {p: 0 for p in VERDICTS} for a in VERDICTS}
    for a, p in zip(actual, predicted, strict=True):
        matrix[a][p] += 1
    return matrix


def _metrics(matrix: dict[str, dict[str, int]]) -> dict[str, dict[str, float]]:
    metrics: dict[str, dict[str, float]] = {}
    for cls in VERDICTS:
        tp = matrix[cls][cls]
        fp = sum(matrix[a][cls] for a in VERDICTS if a != cls)
        fn = sum(matrix[cls][p] for p in VERDICTS if p != cls)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        metrics[cls] = {
            "precision": round(precision, 3),
            "recall": round(recall, 3),
            "f1": round(f1, 3),
            "support": tp + fn,
        }
    return metrics


def _auc(actual_binary: list[int], scores: list[float]) -> float:
    """梯形法计算二分类 AUC；样本数不足 2 类时返回 0.5。"""
    pairs = sorted(zip(scores, actual_binary, strict=True), key=lambda pair: pair[0])
    if len({b for _, b in pairs}) < 2:
        return 0.5
    pos = sum(b for _, b in pairs)
    neg = len(pairs) - pos
    if pos == 0 or neg == 0:
        return 0.5
    # 按分数升序累加：rank 从 1 起，AUC = (sum_pos_rank - pos*(pos+1)/2) / (pos*neg)
    sum_pos_rank = 0.0
    i = 0
    while i < len(pairs):
        j = i
        while j + 1 < len(pairs) and pairs[j + 1][0] == pairs[i][0]:
            j += 1
        avg_rank = (i + 1 + j + 1) / 2
        for k in range(i, j + 1):
            if pairs[k][1] == 1:
                sum_pos_rank += avg_rank
        i = j + 1
    return (sum_pos_rank - pos * (pos + 1) / 2) / (pos * neg)


async def _run_case(graph, case: dict) -> tuple[str, float]:
    state = await graph.ainvoke(
        {
            "task_id": f"eval-{case['case_id']}",
            "request": {
                "policy_title": case["policy_title"],
                "policy_text": case["policy_text"],
                "target_companies": [case["target_company"]],
            },
            "warnings": [],
            "match_attempts": 0,
            "evidence_attempts": 0,
            "max_match_attempts": 3,
            "max_evidence_attempts": 3,
            "lenient_matching": False,
        },
        config={"recursion_limit": 50},
    )
    for verdict in state.get("verdicts", []):
        if verdict.company_id == case["target_company"]:
            return verdict.verdict, verdict.benefit_probability
    return "watch", 0.5


async def _evaluate() -> dict:
    rag = GraphRAGService(PROJECT_ROOT / "data")
    graph = build_analysis_graph(rag, OptionalPolicyLLM(api_key="", model="gpt-4.1-mini"))
    with (PROJECT_ROOT / "data" / "eval_cases.json").open(encoding="utf-8") as handle:
        cases = json.load(handle)["cases"]

    actual: list[str] = []
    predicted: list[str] = []
    binary_actual: list[int] = []
    hotspot_scores: list[float] = []
    detail = []
    for case in cases:
        pred, score = await _run_case(graph, case)
        exp = case["expected_verdict"]
        actual.append(exp)
        predicted.append(pred)
        binary_actual.append(1 if exp in HOTSPOT_POSITIVE else 0)
        # hotspot 统一用 1 - benefit_probability 作为分数：热点（watch/hotspot_risk）分越高越像非真实受益，
        # 高置信负类分越低，保证全体样本在同一个分数尺度上排序（单调），AUC 才有意义。
        hotspot_scores.append(1 - score)
        detail.append(
            {
                "case_id": case["case_id"],
                "expected": exp,
                "predicted": pred,
                "benefit_probability": score,
                "match": exp == pred,
            }
        )

    matrix = _confusion(actual, predicted)
    metrics = _metrics(matrix)
    auc = round(_auc(binary_actual, hotspot_scores), 3)
    accuracy = round(sum(a == p for a, p in zip(actual, predicted, strict=True)) / len(actual), 3)
    return {
        "n_cases": len(cases),
        "accuracy": accuracy,
        "hotspot_auc": auc,
        "confusion_matrix": matrix,
        "per_class": metrics,
        "detail": detail,
    }


def main() -> int:
    result = asyncio.run(_evaluate())

    print("=" * 60)
    print("FinEcho 对抗式核验评测报告")
    print("=" * 60)
    print(f"样本数            : {result['n_cases']}")
    print(f"总体准确率 (ACC)  : {result['accuracy']}")
    print(f"Hotspot AUC       : {result['hotspot_auc']}")
    print()
    print("混淆矩阵 (行=真实, 列=预测):")
    header = "            " + "".join(f"{v:>14}" for v in VERDICTS)
    print(header)
    for actual_cls in VERDICTS:
        row = result["confusion_matrix"][actual_cls]
        print(f"{actual_cls:12s} " + "".join(f"{row[p]:>14}" for p in VERDICTS))
    print()
    print("Per-class 指标:")
    print(f"{'class':<14} {'precision':>10} {'recall':>8} {'f1':>6} {'support':>8}")
    for cls, m in result["per_class"].items():
        print(
            f"{cls:<14} {m['precision']:>10.3f} {m['recall']:>8.3f} {m['f1']:>6.3f} {m['support']:>8}"
        )
    print()
    print("逐 case 明细:")
    for d in result["detail"]:
        mark = "OK " if d["match"] else "MIS"
        print(
            f"  [{mark}] {d['case_id']:16s} expected={d['expected']:15s} "
            f"predicted={d['predicted']:15s} p={d['benefit_probability']:.3f}"
        )
    print()
    print("评测口径：verdict 三分类（high_confidence/watch/hotspot_risk），")
    print("hotspot AUC 将 watch+hotspot_risk 视为正类，评估识别非真实受益的能力。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
