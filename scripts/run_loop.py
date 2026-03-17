"""Full autoresearch loop on a single unit.

Usage:
    python scripts/run_loop.py [--unit 1] [--max-iterations 50] [--config config/experiment.json]

Runs the inner autoresearch loop on a single unit until convergence.
Wraps AutoresearchRunner with concrete implementations of grade_fn,
analyze_fn, and apply_fn.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from simulator import StudentPersona, StudentCohort
from loop.runner import AutoresearchRunner
from loop.metrics import metrics_to_dict
from optimizer.analyzer import FailureAnalyzer
from optimizer.patcher import CurriculumPatcher


# ---------------------------------------------------------------------------
# Grade function (same as run_experiment but formatted for runner interface)
# ---------------------------------------------------------------------------

def _grade_via_node(script: str, input_data: dict) -> dict | None:
    """Run a Node.js grading adapter and return parsed JSON output."""
    script_path = PROJECT_ROOT / "adapters" / "curriculum_render" / script
    if not script_path.exists():
        return None
    try:
        result = subprocess.run(
            ["node", str(script_path)],
            input=json.dumps(input_data),
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(PROJECT_ROOT),
        )
        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout)
    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError):
        pass
    return None


def grade_fn(item: dict, response: dict) -> dict:
    """Grade a single student response against an item."""
    item_type = item.get("item_type", "mcq").lower()
    student_answer = response.get("response", "")
    expected = item.get("expected", {})

    if item_type == "mcq":
        node_input = {"answer": student_answer, "expected": expected}
        node_result = _grade_via_node("grade_mcq.mjs", node_input)
        if node_result is not None:
            return node_result
        correct_key = expected.get("answer_key", "").upper()
        return {"score": "E"} if student_answer.upper() == correct_key else {"score": "I"}

    elif item_type == "frq":
        rule_id = expected.get("ruleId", expected.get("rule_id", ""))
        node_input = {
            "answer": student_answer,
            "ruleId": rule_id,
            "context": expected.get("context", {}),
        }
        node_result = _grade_via_node("grade_frq.mjs", node_input)
        if node_result is not None:
            return node_result
        return {"score": "P"}

    return {"score": "I"}


# ---------------------------------------------------------------------------
# Analyze function (pure computation -- skips LLM for MVP)
# ---------------------------------------------------------------------------

def make_analyze_fn(provider_config: dict, unit: int):
    """Return an analyze_fn closure that clusters and classifies failures."""
    analyzer = FailureAnalyzer(provider_config)

    def analyze_fn(metrics, best_metrics) -> list[dict]:
        # Metrics are IterationMetrics dataclasses; build grades proxy
        # from top_failure_kcs since we don't carry raw grades forward.
        # For MVP: use the cluster_failures + classify_failure_sources approach.
        # We reconstruct minimal grade-like dicts from the metrics.
        failure_kcs = metrics.top_failure_kcs if metrics else []
        kc_mastery = metrics.kc_mastery if metrics else {}

        # Build synthetic grade list from kc_mastery for clustering
        synthetic_grades: list[dict] = []
        for kc_id, mastery in kc_mastery.items():
            # Create pseudo-grades to reflect the mastery rate
            n_total = 10  # approximate
            n_correct = int(mastery * n_total)
            for _ in range(n_correct):
                synthetic_grades.append({
                    "student_id": "aggregate",
                    "item_id": f"pseudo-{kc_id}",
                    "score": "E",
                    "kc_tags": [kc_id],
                    "unit": unit,
                })
            for _ in range(n_total - n_correct):
                synthetic_grades.append({
                    "student_id": "aggregate",
                    "item_id": f"pseudo-{kc_id}",
                    "score": "I",
                    "kc_tags": [kc_id],
                    "unit": unit,
                })

        metrics_dict = metrics_to_dict(metrics) if metrics else {}
        clusters = analyzer.cluster_failures(synthetic_grades, metrics_dict)

        # Classify sources (skip LLM, use pure computation)
        classifications = analyzer.classify_failure_sources(
            failure_clusters=clusters,
            student_memories=[],  # no student memory data in MVP
            current_unit=unit,
        )

        # Convert classifications to improvement dicts
        improvements: list[dict] = []
        for cls in classifications[:3]:  # limit to top 3
            improvements.append({
                "target": "worksheet",
                "unit": unit,
                "lesson": 1,
                "kc_id": cls["kc_id"],
                "source": cls["source"],
                "improvement": f"Improve exposition for {cls['kc_id']} ({cls['source']})",
                "patch": {
                    "target": "worksheet",
                    "unit": unit,
                    "lesson": 1,
                    "field": "exposition",
                    "section": cls["kc_id"],
                    "content": f"[Auto-generated improvement for {cls['kc_id']}]",
                },
                "priority": cls.get("priority", 0.5),
            })

        return improvements

    return analyze_fn


# ---------------------------------------------------------------------------
# Apply function
# ---------------------------------------------------------------------------

def make_apply_fn():
    """Return an apply_fn closure that writes patches to disk."""
    patcher = CurriculumPatcher()

    def apply_fn(improvements: list[dict]) -> None:
        for imp in improvements:
            patch = imp.get("patch", imp)
            path = patcher.apply_patch(patch, base_dir="curriculum_patches")
            print(f"  Patch written: {path}")

    return apply_fn


# ---------------------------------------------------------------------------
# Persona / item loading
# ---------------------------------------------------------------------------

def load_personas(n_students: int) -> list[StudentPersona]:
    """Load personas from config/personas.json."""
    personas_path = PROJECT_ROOT / "config" / "personas.json"
    with open(personas_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    personas_raw = data.get("personas", [])[:n_students]
    return [
        StudentPersona(
            persona_id=p["persona_id"],
            ability_tier=p["ability_tier"],
            kc_acquisition_rate=p["kc_acquisition_rate"],
            carelessness=p["carelessness"],
            guess_strategy=p["guess_strategy"],
            misconception_persistence=p["misconception_persistence"],
            reading_comprehension=p["reading_comprehension"],
            working_memory_slots=p["working_memory_slots"],
        )
        for p in personas_raw
    ]


def load_items(unit: int, eval_set: str | None = None) -> list[dict]:
    """Load items for a specific unit.

    If *eval_set* is given, load the frozen eval set from
    ``eval_sets/{eval_set}.json``.  Otherwise filter the full item file.
    """
    if eval_set:
        es_path = PROJECT_ROOT / "eval_sets" / f"{eval_set}.json"
        if es_path.exists():
            with open(es_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            items = data.get("items", data) if isinstance(data, dict) else data
            print(f"Loaded eval set '{eval_set}' ({len(items)} items)")
            return items
        else:
            print(f"WARNING: eval set '{eval_set}' not found at {es_path}, "
                  "falling back to full item file", file=sys.stderr)

    items_path = PROJECT_ROOT / "data" / "items" / "curriculum_render.json"
    if not items_path.exists():
        print(f"ERROR: Items not found at {items_path}", file=sys.stderr)
        sys.exit(1)
    with open(items_path, "r", encoding="utf-8") as f:
        all_items = json.load(f)
    return [it for it in all_items if it.get("unit") == unit]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def run_loop(unit: int, max_iterations: int, config_path: str) -> None:
    """Run the full inner autoresearch loop on one unit."""
    # Load configs
    config: dict = {}
    if os.path.isfile(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

    provider_path = PROJECT_ROOT / "config" / "provider.json"
    provider: dict = {}
    if provider_path.exists():
        with open(provider_path, "r", encoding="utf-8") as f:
            provider = json.load(f)

    endpoint = provider.get("student", {}).get("endpoint", "http://localhost:11434")
    model = provider.get("student", {}).get("model", "qwen3:8b")
    optimizer_config = provider.get("optimizer", {})

    n_students = config.get("n_students", 10)

    # Load items and create cohort
    eval_set = config.get("eval_set")
    items = load_items(unit, eval_set=eval_set)
    if not items:
        print(f"No items found for unit {unit}.", file=sys.stderr)
        sys.exit(1)

    personas = load_personas(n_students)
    cohort = StudentCohort.from_personas(personas)

    print(f"Starting autoresearch loop: unit={unit}, items={len(items)}, "
          f"students={len(personas)}, max_iter={max_iterations}")

    # Create runner with overridden max_iterations
    runner = AutoresearchRunner(config_path=config_path)
    runner.max_iterations = max_iterations

    # Wire up callbacks
    analyze = make_analyze_fn(optimizer_config, unit)
    apply = make_apply_fn()

    try:
        await runner.run_loop(
            items=items,
            cohort=cohort,
            grade_fn=grade_fn,
            analyze_fn=analyze,
            apply_fn=apply,
            endpoint=endpoint,
            model=model,
        )
    except KeyboardInterrupt:
        print("\nInterrupted by user. State has been saved.")

    # Print final summary
    if runner.best_metrics:
        m = runner.best_metrics
        print()
        print("=" * 60)
        print(f"  LOOP COMPLETE — Unit {unit}")
        print("=" * 60)
        print(f"  Iterations:     {runner.iteration}")
        print(f"  Best score:     {m.mean_score:.4f}")
        print(f"  MCQ accuracy:   {m.mcq_accuracy:.1%}")
        print(f"  Converged:      {runner.is_converged()}")
        print("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="Run the full autoresearch loop on a single unit."
    )
    parser.add_argument("--unit", type=int, default=1,
                        help="Unit number to optimise (default: 1)")
    parser.add_argument("--max-iterations", type=int, default=50,
                        help="Maximum loop iterations (default: 50)")
    parser.add_argument("--config", type=str, default="config/experiment.json",
                        help="Path to experiment config")
    args = parser.parse_args()

    asyncio.run(run_loop(args.unit, args.max_iterations, args.config))


if __name__ == "__main__":
    main()
