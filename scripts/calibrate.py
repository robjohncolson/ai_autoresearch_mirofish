"""Calibration comparison: synthetic vs real student data.

Usage:
    python scripts/calibrate.py [--synthetic logs/runs/latest/grades.jsonl] [--real data/real_student_export.json]

Compares synthetic student error patterns to real student data.
Computes:
- Per-item difficulty correlation (Spearman)
- Per-KC mastery correlation
- Misconception distribution overlap

Phase 3 stub: loads data and reports status.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def load_synthetic_grades(path: str) -> list[dict]:
    """Load synthetic grades from a JSONL file."""
    grades: list[dict] = []
    fpath = Path(path)
    if not fpath.is_absolute():
        fpath = PROJECT_ROOT / fpath

    if not fpath.exists():
        print(f"WARNING: Synthetic grades file not found: {fpath}", file=sys.stderr)
        return grades

    with open(fpath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    grades.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return grades


def load_real_data(path: str) -> list[dict]:
    """Load real student data from a JSON file."""
    fpath = Path(path)
    if not fpath.is_absolute():
        fpath = PROJECT_ROOT / fpath

    if not fpath.exists():
        return []

    with open(fpath, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        return data
    elif isinstance(data, dict):
        return data.get("grades", data.get("records", []))
    return []


def compute_item_difficulty(grades: list[dict]) -> dict[str, float]:
    """Compute per-item difficulty (fraction incorrect)."""
    item_total: dict[str, int] = {}
    item_errors: dict[str, int] = {}
    for g in grades:
        iid = g.get("item_id", "")
        item_total[iid] = item_total.get(iid, 0) + 1
        if g.get("score", "") == "I":
            item_errors[iid] = item_errors.get(iid, 0) + 1
    return {
        iid: item_errors.get(iid, 0) / total
        for iid, total in item_total.items()
        if total > 0
    }


def compute_kc_mastery(grades: list[dict]) -> dict[str, float]:
    """Compute per-KC mastery (fraction correct)."""
    kc_total: dict[str, int] = {}
    kc_correct: dict[str, int] = {}
    for g in grades:
        for kc in g.get("kc_tags", []):
            kc_total[kc] = kc_total.get(kc, 0) + 1
            if g.get("score", "") == "E":
                kc_correct[kc] = kc_correct.get(kc, 0) + 1
    return {
        kc: kc_correct.get(kc, 0) / total
        for kc, total in kc_total.items()
        if total > 0
    }


def main():
    parser = argparse.ArgumentParser(
        description="Compare synthetic student error patterns to real student data."
    )
    parser.add_argument("--synthetic", type=str,
                        default="logs/runs/latest/grades.jsonl",
                        help="Path to synthetic grades JSONL file")
    parser.add_argument("--real", type=str,
                        default="data/real_student_export.json",
                        help="Path to real student data JSON file")
    args = parser.parse_args()

    print("=" * 60)
    print("  CALIBRATION COMPARISON")
    print("=" * 60)

    # Load synthetic grades
    synthetic = load_synthetic_grades(args.synthetic)
    print(f"Synthetic grades loaded: {len(synthetic)} records")

    # Load real data
    real = load_real_data(args.real)
    print(f"Real student data loaded: {len(real)} records")

    if not real:
        print()
        print("Calibration not yet implemented -- need real student export.")
        print()
        print("To run calibration:")
        print("  1. Export real student data to data/real_student_export.json")
        print("  2. Re-run: python scripts/calibrate.py --real data/real_student_export.json")
        print()
        print("Expected format: JSON array of grade objects with keys:")
        print('  {"item_id": "...", "score": "E"|"P"|"I", "kc_tags": [...]}')
        return

    if synthetic:
        syn_difficulty = compute_item_difficulty(synthetic)
        syn_mastery = compute_kc_mastery(synthetic)
        print(f"  Synthetic items tracked: {len(syn_difficulty)}")
        print(f"  Synthetic KCs tracked:   {len(syn_mastery)}")

    if real:
        real_difficulty = compute_item_difficulty(real)
        real_mastery = compute_kc_mastery(real)
        print(f"  Real items tracked: {len(real_difficulty)}")
        print(f"  Real KCs tracked:   {len(real_mastery)}")

    # Phase 3: Spearman correlation, misconception overlap, etc.
    print()
    print("Full correlation analysis will be implemented in Phase 3.")
    print("Structure is ready for:")
    print("  - Per-item difficulty correlation (Spearman)")
    print("  - Per-KC mastery correlation")
    print("  - Misconception distribution overlap")


if __name__ == "__main__":
    main()
