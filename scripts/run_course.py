"""Full course progression: sequential unit-by-unit autoresearch.

Usage:
    python scripts/run_course.py [--start-unit 1] [--end-unit 9] [--config config/experiment.json]

Runs the outer loop: sequential unit-by-unit progression with cumulative
student memory and inter-unit forgetting.
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
from loop.progression import CourseProgression
from loop.metrics import metrics_to_dict
from optimizer.analyzer import FailureAnalyzer
from optimizer.patcher import CurriculumPatcher


# ---------------------------------------------------------------------------
# Grade / analyze / apply functions (reuse pattern from run_loop.py)
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


def make_analyze_fn(provider_config: dict, unit: int):
    """Return an analyze_fn closure for failure analysis."""
    analyzer = FailureAnalyzer(provider_config)

    def analyze_fn(metrics, best_metrics) -> list[dict]:
        kc_mastery = metrics.kc_mastery if metrics else {}

        synthetic_grades: list[dict] = []
        for kc_id, mastery in kc_mastery.items():
            n_total = 10
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
        classifications = analyzer.classify_failure_sources(
            failure_clusters=clusters,
            student_memories=[],
            current_unit=unit,
        )

        improvements: list[dict] = []
        for cls in classifications[:3]:
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
# Loading helpers
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


def load_items_by_unit(start_unit: int, end_unit: int) -> dict[int, list[dict]]:
    """Load items grouped by unit."""
    items_path = PROJECT_ROOT / "data" / "items" / "curriculum_render.json"
    if not items_path.exists():
        print(f"ERROR: Items not found at {items_path}", file=sys.stderr)
        sys.exit(1)
    with open(items_path, "r", encoding="utf-8") as f:
        all_items = json.load(f)

    items_by_unit: dict[int, list[dict]] = {}
    for it in all_items:
        u = it.get("unit")
        if u is not None and start_unit <= u <= end_unit:
            items_by_unit.setdefault(u, []).append(it)
    return items_by_unit


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def run_course(start_unit: int, end_unit: int, config_path: str) -> None:
    """Run the full course progression."""
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

    items_by_unit = load_items_by_unit(start_unit, end_unit)
    personas = load_personas(n_students)
    cohort = StudentCohort.from_personas(personas)

    print(f"Starting course progression: units {start_unit}-{end_unit}, "
          f"students={len(personas)}")
    for u, items in sorted(items_by_unit.items()):
        print(f"  Unit {u}: {len(items)} items")

    progression = CourseProgression(config_path=config_path)
    progression.current_unit = start_unit
    progression.total_units = end_unit

    # NOTE: analyze_fn needs to know the current unit, but the outer loop
    # advances it. We create a mutable wrapper.
    current_unit_ref = [start_unit]

    def analyze_fn(metrics, best_metrics) -> list[dict]:
        fn = make_analyze_fn(optimizer_config, current_unit_ref[0])
        return fn(metrics, best_metrics)

    apply = make_apply_fn()

    try:
        await progression.run_course(
            cohort=cohort,
            items_by_unit=items_by_unit,
            grade_fn=grade_fn,
            analyze_fn=analyze_fn,
            apply_fn=apply,
            endpoint=endpoint,
            model=model,
        )
    except KeyboardInterrupt:
        print("\nInterrupted by user. Progression state has been saved.")

    # Final summary
    print()
    print("=" * 60)
    print("  COURSE PROGRESSION COMPLETE")
    print("=" * 60)
    for u, result in sorted(progression.unit_results.items()):
        score = result.get("mean_score", 0.0)
        print(f"  Unit {u}: mean_score = {score:.4f}")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="Run the full course progression (sequential unit-by-unit)."
    )
    parser.add_argument("--start-unit", type=int, default=1,
                        help="First unit to run (default: 1)")
    parser.add_argument("--end-unit", type=int, default=9,
                        help="Last unit to run (default: 9)")
    parser.add_argument("--config", type=str, default="config/experiment.json",
                        help="Path to experiment config")
    args = parser.parse_args()

    asyncio.run(run_course(args.start_unit, args.end_unit, args.config))


if __name__ == "__main__":
    main()
