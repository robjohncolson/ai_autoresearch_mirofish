"""Single-iteration experiment runner for autoresearch.

Usage:
    python scripts/run_experiment.py [--unit 1] [--n-students 10] [--config config/experiment.json]

Steps:
1. Load config, personas, items for the specified unit
2. Create a StudentCohort from personas (or from snapshots if resuming)
3. Run cohort.run_evaluation() against the items
4. Grade all responses (call Node adapters via subprocess for MCQ/FRQ)
5. Update student memories based on grades
6. Compute and display IterationMetrics
7. Save results to logs/runs/{run_id}/
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

# Ensure repo root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from simulator import StudentPersona, StudentCohort, SyntheticStudent
from loop.metrics import compute_metrics, metrics_to_dict


# ---------------------------------------------------------------------------
# Grading helpers
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


def grade_response(item: dict, response: dict) -> dict:
    """Grade a single student response against an item.

    Tries Node.js adapters first, falls back to simple matching.
    """
    item_type = item.get("item_type", "mcq").lower()
    student_answer = response.get("response", "")
    expected = item.get("expected", {})

    if item_type == "mcq":
        # Try Node adapter
        node_input = {"answer": student_answer, "expected": expected}
        node_result = _grade_via_node("grade_mcq.mjs", node_input)
        if node_result is not None:
            return node_result

        # Fallback: simple letter comparison
        correct_key = expected.get("answer_key", "").upper()
        if student_answer.upper() == correct_key:
            return {"score": "E"}
        else:
            return {"score": "I"}

    elif item_type == "frq":
        # Try Node adapter
        rule_id = expected.get("ruleId", expected.get("rule_id", ""))
        node_input = {
            "answer": student_answer,
            "ruleId": rule_id,
            "context": expected.get("context", {}),
        }
        node_result = _grade_via_node("grade_frq.mjs", node_input)
        if node_result is not None:
            return node_result

        # Fallback: mark as partial (no way to grade FRQ without rubric)
        return {"score": "P"}

    else:
        return {"score": "I"}


# ---------------------------------------------------------------------------
# Persona loading
# ---------------------------------------------------------------------------

def load_personas(config_path: str, n_students: int) -> list[StudentPersona]:
    """Load persona definitions from config/personas.json."""
    personas_path = PROJECT_ROOT / "config" / "personas.json"
    with open(personas_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    personas_raw = data.get("personas", [])
    selected = personas_raw[:n_students]

    personas = []
    for p in selected:
        personas.append(StudentPersona(
            persona_id=p["persona_id"],
            ability_tier=p["ability_tier"],
            kc_acquisition_rate=p["kc_acquisition_rate"],
            carelessness=p["carelessness"],
            guess_strategy=p["guess_strategy"],
            misconception_persistence=p["misconception_persistence"],
            reading_comprehension=p["reading_comprehension"],
            working_memory_slots=p["working_memory_slots"],
        ))
    return personas


def load_items(unit: int) -> list[dict]:
    """Load items for a specific unit from data/items/curriculum_render.json."""
    items_path = PROJECT_ROOT / "data" / "items" / "curriculum_render.json"
    if not items_path.exists():
        print(f"ERROR: Items file not found at {items_path}", file=sys.stderr)
        sys.exit(1)

    with open(items_path, "r", encoding="utf-8") as f:
        all_items = json.load(f)

    return [it for it in all_items if it.get("unit") == unit]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def run_experiment(unit: int, n_students: int, config_path: str) -> None:
    """Run a single evaluation pass."""
    # 1. Load config
    config: dict = {}
    if os.path.isfile(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

    # Load provider config
    provider_path = PROJECT_ROOT / "config" / "provider.json"
    provider: dict = {}
    if provider_path.exists():
        with open(provider_path, "r", encoding="utf-8") as f:
            provider = json.load(f)

    endpoint = provider.get("student", {}).get("endpoint", "http://localhost:11434")
    model = provider.get("student", {}).get("model", "qwen3:8b")

    # 2. Load items and personas
    items = load_items(unit)
    if not items:
        print(f"No items found for unit {unit}.", file=sys.stderr)
        sys.exit(1)

    print(f"Loaded {len(items)} items for unit {unit}")

    personas = load_personas(config_path, n_students)
    print(f"Loaded {len(personas)} student personas")

    # 3. Create cohort
    cohort = StudentCohort.from_personas(personas)

    # 4. Run evaluation
    print(f"Running evaluation against {endpoint} ({model})...")
    try:
        responses = await cohort.run_evaluation(
            items=items,
            endpoint=endpoint,
            model=model,
            max_concurrent=provider.get("student", {}).get("max_concurrent_requests", 5),
        )
    except Exception as exc:
        print(f"ERROR during evaluation: {exc}", file=sys.stderr)
        print("(Is Ollama running?)", file=sys.stderr)
        sys.exit(1)

    print(f"Got {len(responses)} responses")

    # 5. Grade all responses
    items_by_id = {it["item_id"]: it for it in items}
    grades: list[dict] = []
    now = time.time()

    for resp in responses:
        item = items_by_id.get(resp.get("item_id", ""), {})
        grade = grade_response(item, resp)

        grade_entry = {
            "student_id": resp.get("student_id", "unknown"),
            "item_id": resp.get("item_id", "unknown"),
            "item_type": item.get("item_type", "mcq"),
            "unit": item.get("unit", unit),
            "kc_tags": item.get("kc_tags", []),
            "response": resp.get("response", ""),
            **grade,
        }
        grades.append(grade_entry)

        # 6. Update student memory
        student = None
        for s in cohort.students:
            if s.persona.persona_id == resp.get("student_id"):
                student = s
                break
        if student and item:
            student.update_memory_from_grade(item, grade, now)

    # 7. Compute metrics
    run_id = f"run-{int(time.time())}"
    metrics = compute_metrics(
        grades,
        curriculum_version=run_id,
        iteration_id=1,
        scoring_weights=config.get("scoring_weights", {"E": 3, "P": 2, "I": 1}),
    )

    # 8. Display summary
    print()
    print("=" * 60)
    print(f"  EXPERIMENT RESULTS — Unit {unit}")
    print("=" * 60)
    print(f"  Students:       {metrics.n_students}")
    print(f"  Items:          {metrics.n_items}")
    print(f"  Mean score:     {metrics.mean_score:.4f}")
    print(f"  MCQ accuracy:   {metrics.mcq_accuracy:.1%}")
    print(f"  FRQ E-rate:     {metrics.frq_e_rate:.1%}")
    print(f"  FRQ P-rate:     {metrics.frq_p_rate:.1%}")
    print(f"  FRQ I-rate:     {metrics.frq_i_rate:.1%}")
    if metrics.top_failure_kcs:
        print(f"  Top failures:   {metrics.top_failure_kcs[:5]}")
    print("=" * 60)

    # 9. Save results
    run_dir = PROJECT_ROOT / "logs" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # Save grades
    grades_path = run_dir / "grades.jsonl"
    with open(grades_path, "w", encoding="utf-8") as f:
        for g in grades:
            f.write(json.dumps(g, ensure_ascii=False) + "\n")

    # Save metrics
    metrics_path = run_dir / "metrics.json"
    with open(metrics_path, "w", encoding="utf-8") as f:
        json.dump(metrics_to_dict(metrics), f, indent=2)

    # Save student snapshots
    snap_dir = run_dir / "snapshots"
    cohort.save_snapshots(str(snap_dir))

    print(f"\nResults saved to {run_dir}")


def main():
    parser = argparse.ArgumentParser(
        description="Run a single evaluation iteration of the autoresearch experiment."
    )
    parser.add_argument("--unit", type=int, default=1,
                        help="Unit number to evaluate (default: 1)")
    parser.add_argument("--n-students", type=int, default=10,
                        help="Number of students in the cohort (default: 10)")
    parser.add_argument("--config", type=str, default="config/experiment.json",
                        help="Path to experiment config file")
    args = parser.parse_args()

    asyncio.run(run_experiment(args.unit, args.n_students, args.config))


if __name__ == "__main__":
    main()
