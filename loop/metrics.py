"""Score computation and improvement-check logic for the autoresearch loop.

All grading data flows in as plain dicts so this module has zero imports
from simulator/ or optimizer/.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from typing import Optional


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

@dataclass
class IterationMetrics:
    """Aggregated metrics for one autoresearch iteration."""

    curriculum_version: str       # git commit hash
    iteration_id: int
    timestamp: float
    n_students: int
    n_items: int

    # Primary metrics
    mean_score: float             # weighted E=3, P=2, I=1, averaged
    mcq_accuracy: float           # fraction of MCQ items scored E
    frq_e_rate: float             # fraction of FRQ items scored E
    frq_p_rate: float             # fraction of FRQ items scored P
    frq_i_rate: float             # fraction of FRQ items scored I

    # Per-unit breakdown
    unit_scores: dict = field(default_factory=dict)   # {unit_num: mean_score}

    # Per-KC breakdown
    kc_mastery: dict = field(default_factory=dict)     # {kc_id: fraction_correct}

    # Failure clustering
    top_failure_kcs: list = field(default_factory=list)        # [(kc_id, error_rate), ...]
    misconception_counts: dict = field(default_factory=dict)   # {type: count}

    # Holdout (computed less frequently)
    holdout_score: Optional[float] = None


# ---------------------------------------------------------------------------
# Metric computation
# ---------------------------------------------------------------------------

_DEFAULT_WEIGHTS = {"E": 3, "P": 2, "I": 1}


def compute_metrics(
    grades: list[dict],
    curriculum_version: str,
    iteration_id: int,
    scoring_weights: dict | None = None,
) -> IterationMetrics:
    """Compute all metrics from a batch of grading results.

    Each element of *grades* is expected to carry at least::

        {
            "student_id": str,
            "item_id":    str,
            "item_type":  "MCQ" | "FRQ",
            "unit":       int | str,
            "kc_tags":    list[str],
            "score":      "E" | "P" | "I",
            ...                             # extra keys are ignored
        }
    """
    weights = scoring_weights or _DEFAULT_WEIGHTS

    if not grades:
        return IterationMetrics(
            curriculum_version=curriculum_version,
            iteration_id=iteration_id,
            timestamp=time.time(),
            n_students=0,
            n_items=0,
            mean_score=0.0,
            mcq_accuracy=0.0,
            frq_e_rate=0.0,
            frq_p_rate=0.0,
            frq_i_rate=0.0,
        )

    # Unique counts
    students = {g["student_id"] for g in grades}
    items = {g["item_id"] for g in grades}

    # ---- Primary scalar metrics ----
    weighted_total = 0.0
    mcq_total = 0
    mcq_e = 0
    frq_total = 0
    frq_e = 0
    frq_p = 0
    frq_i = 0

    # Per-unit accumulators: {unit: [weighted_score, ...]}
    unit_accum: dict[str, list[float]] = {}

    # Per-KC accumulators: {kc: [is_correct, ...]}  (E counts as correct)
    kc_accum: dict[str, list[int]] = {}

    # Misconception counter
    misconception_counts: dict[str, int] = {}

    for g in grades:
        score_label = g.get("score", "I")
        w = weights.get(score_label, 1)
        weighted_total += w

        item_type = g.get("item_type", "MCQ").upper()
        if item_type == "MCQ":
            mcq_total += 1
            if score_label == "E":
                mcq_e += 1
        else:
            frq_total += 1
            if score_label == "E":
                frq_e += 1
            elif score_label == "P":
                frq_p += 1
            else:
                frq_i += 1

        # Per-unit
        unit_key = str(g.get("unit", "unknown"))
        unit_accum.setdefault(unit_key, []).append(w)

        # Per-KC
        is_correct = 1 if score_label == "E" else 0
        for kc in g.get("kc_tags", []):
            kc_accum.setdefault(kc, []).append(is_correct)

        # Misconceptions (from grading feedback)
        for m in g.get("missing", []):
            misconception_counts[m] = misconception_counts.get(m, 0) + 1

    n = len(grades)
    max_possible = weights["E"]  # normalise to [0, max_weight]
    mean_score = (weighted_total / n) if n else 0.0

    mcq_accuracy = (mcq_e / mcq_total) if mcq_total else 0.0
    frq_e_rate = (frq_e / frq_total) if frq_total else 0.0
    frq_p_rate = (frq_p / frq_total) if frq_total else 0.0
    frq_i_rate = (frq_i / frq_total) if frq_total else 0.0

    # Per-unit mean weighted score
    unit_scores = {
        u: sum(vals) / len(vals) for u, vals in unit_accum.items()
    }

    # Per-KC mastery
    kc_mastery = {
        kc: sum(vals) / len(vals) for kc, vals in kc_accum.items()
    }

    # Top-10 failure KCs (lowest mastery)
    sorted_kcs = sorted(kc_mastery.items(), key=lambda kv: kv[1])
    top_failure_kcs = [
        (kc, round(1.0 - mastery, 4)) for kc, mastery in sorted_kcs[:10]
    ]

    return IterationMetrics(
        curriculum_version=curriculum_version,
        iteration_id=iteration_id,
        timestamp=time.time(),
        n_students=len(students),
        n_items=len(items),
        mean_score=round(mean_score, 4),
        mcq_accuracy=round(mcq_accuracy, 4),
        frq_e_rate=round(frq_e_rate, 4),
        frq_p_rate=round(frq_p_rate, 4),
        frq_i_rate=round(frq_i_rate, 4),
        unit_scores=unit_scores,
        kc_mastery=kc_mastery,
        top_failure_kcs=top_failure_kcs,
        misconception_counts=misconception_counts,
        holdout_score=None,
    )


# ---------------------------------------------------------------------------
# Improvement guard
# ---------------------------------------------------------------------------

_DEFAULT_GUARDS = {
    "max_unit_regression": 0.1,
    "max_holdout_divergence": 0.05,
}


def is_improvement(
    current: IterationMetrics,
    best: IterationMetrics,
    guards: dict | None = None,
) -> bool:
    """Keep-if-better decision with multi-metric guardrails.

    Rules
    -----
    1. ``current.mean_score`` must strictly exceed ``best.mean_score``.
    2. No individual unit may regress by more than
       ``guards["max_unit_regression"]`` (default 0.1).
    3. If holdout scores are available on both sides, the current holdout
       must not fall below the best holdout by more than
       ``guards["max_holdout_divergence"]`` (default 0.05).
    """
    g = {**_DEFAULT_GUARDS, **(guards or {})}

    # Rule 1 — primary metric must improve
    if current.mean_score <= best.mean_score:
        return False

    # Rule 2 — per-unit regression guard
    max_reg = g["max_unit_regression"]
    for unit, score in current.unit_scores.items():
        prior = best.unit_scores.get(unit, 0.0)
        if score < prior - max_reg:
            return False

    # Rule 3 — holdout divergence guard
    if current.holdout_score is not None and best.holdout_score is not None:
        max_div = g["max_holdout_divergence"]
        if current.holdout_score < best.holdout_score - max_div:
            return False

    return True


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------

def metrics_to_dict(m: IterationMetrics) -> dict:
    """Serialize an ``IterationMetrics`` to a JSON-compatible dict."""
    d = asdict(m)
    # Convert tuple list back to list-of-lists for JSON
    d["top_failure_kcs"] = [list(pair) for pair in d["top_failure_kcs"]]
    return d


def dict_to_metrics(d: dict) -> IterationMetrics:
    """Deserialize a dict (e.g. from JSON) back to ``IterationMetrics``."""
    d = dict(d)  # shallow copy
    # Restore tuples in top_failure_kcs
    d["top_failure_kcs"] = [tuple(pair) for pair in d.get("top_failure_kcs", [])]
    return IterationMetrics(**d)


_TSV_HEADER = (
    "iteration_id\tcurriculum_version\tmean_score\tmcq_accuracy\t"
    "frq_e_rate\tfrq_p_rate\tfrq_i_rate\tn_students\tn_items\t"
    "holdout_score\tkept\tpatch_desc\ttimestamp"
)


def metrics_tsv_header() -> str:
    """Return the TSV header line (no trailing newline)."""
    return _TSV_HEADER


def metrics_to_tsv_row(m: IterationMetrics, kept: bool, patch_desc: str) -> str:
    """Format a single TSV row for ``logs/summary.tsv`` (no trailing newline)."""
    holdout = "" if m.holdout_score is None else f"{m.holdout_score:.4f}"
    return (
        f"{m.iteration_id}\t{m.curriculum_version}\t{m.mean_score:.4f}\t"
        f"{m.mcq_accuracy:.4f}\t{m.frq_e_rate:.4f}\t{m.frq_p_rate:.4f}\t"
        f"{m.frq_i_rate:.4f}\t{m.n_students}\t{m.n_items}\t"
        f"{holdout}\t{'KEEP' if kept else 'REVERT'}\t{patch_desc}\t"
        f"{m.timestamp:.2f}"
    )
