# Agent D: Loop Engine

Build the autoresearch loop orchestration — metrics computation, git operations, inner runner, and outer progression manager.

## Hard Constraints
- Only create/modify files under `loop/`
- Pure Python 3.12, stdlib only (subprocess for git, json for IO)
- Must be importable as a library
- Git operations use subprocess calls to `git` CLI
- Do NOT import from `simulator/` or `optimizer/` directly — use duck typing and accept dicts/dataclasses as parameters. This allows parallel development.

## Interface Contracts (from other agents)

These types will exist in other modules. Accept them as dicts or use structural typing:

```python
# From simulator (Agent B) — will be in simulator.student
# StudentPersona and SyntheticStudent classes exist but don't import them.
# Just work with response dicts: {"item_id": str, "response": str, "student_id": str, "timestamp": float}
# And grade dicts: {"score": "E"/"P"/"I", "feedback": str, "matched": list, "missing": list}

# From config (Agent C) — will be in config/experiment.json
# Read experiment config with json.load()
```

## Deliverables

### 1. `loop/metrics.py` — Score Computation + Improvement Check

```python
from dataclasses import dataclass, field

@dataclass
class IterationMetrics:
    curriculum_version: str       # git commit hash
    iteration_id: int
    timestamp: float
    n_students: int
    n_items: int

    # Primary metrics
    mean_score: float             # weighted E=3, P=2, I=1, averaged over all student×item
    mcq_accuracy: float           # fraction of MCQ items scored E
    frq_e_rate: float             # fraction of FRQ items scored E
    frq_p_rate: float             # fraction of FRQ items scored P
    frq_i_rate: float             # fraction of FRQ items scored I

    # Per-unit breakdown
    unit_scores: dict = field(default_factory=dict)  # {unit_num: mean_score}

    # Per-KC breakdown
    kc_mastery: dict = field(default_factory=dict)    # {kc_id: fraction_correct}

    # Failure clustering
    top_failure_kcs: list = field(default_factory=list)  # [(kc_id, error_rate), ...] top 10
    misconception_counts: dict = field(default_factory=dict)  # {misconception_type: count}

    # Holdout (computed less frequently)
    holdout_score: float | None = None

def compute_metrics(
    grades: list[dict],           # [{"student_id", "item_id", "item_type", "unit", "kc_tags", "score", ...}]
    curriculum_version: str,
    iteration_id: int,
    scoring_weights: dict | None = None,  # {"E": 3, "P": 2, "I": 1}
) -> IterationMetrics:
    """Compute all metrics from a batch of grading results."""
    # Default weights
    weights = scoring_weights or {"E": 3, "P": 2, "I": 1}
    # Compute mean_score, mcq_accuracy, frq rates, per-unit, per-KC, top failures
    ...

def is_improvement(current: IterationMetrics, best: IterationMetrics, guards: dict | None = None) -> bool:
    """
    Keep-if-better decision with multi-metric guardrails.
    guards = {"max_unit_regression": 0.1, "max_holdout_divergence": 0.05}

    Rules:
    1. current.mean_score must be > best.mean_score
    2. No unit may regress by more than guards["max_unit_regression"]
    3. If holdout scores available, current must not diverge by more than guards["max_holdout_divergence"]
    """

def metrics_to_dict(m: IterationMetrics) -> dict:
    """Serialize to JSON-compatible dict."""

def metrics_to_tsv_row(m: IterationMetrics, kept: bool, patch_desc: str) -> str:
    """Format as a single TSV line for summary.tsv"""
```

### 2. `loop/git_ops.py` — Git Branch Management

```python
import subprocess

def create_branch(branch_name: str) -> bool:
    """Create and checkout a new branch. Returns True if created, False if already exists."""

def get_current_commit() -> str:
    """Return current HEAD commit hash (short)."""

def commit_changes(message: str, paths: list[str] | None = None) -> str:
    """Stage paths (or all changes) and commit. Return commit hash."""

def revert_to_commit(commit_hash: str) -> bool:
    """Hard reset to a specific commit. Use with care."""

def get_branch_name() -> str:
    """Return current branch name."""

def ensure_autoresearch_branch(experiment_id: str) -> str:
    """
    Create or checkout autoresearch/{experiment_id} branch.
    If it already exists, checkout it. If not, create from current HEAD.
    Returns the branch name.
    """

def push_branch(branch_name: str | None = None) -> bool:
    """Push current branch to origin. Returns True on success."""
```

All functions use `subprocess.run(["git", ...], capture_output=True, text=True, cwd=repo_root)`.
Determine `repo_root` from the file location or accept as parameter.

### 3. `loop/runner.py` — Inner Autoresearch Loop (per unit)

```python
import json, time, asyncio

class AutoresearchRunner:
    """Inner loop: keep-if-better iteration on a single unit."""

    def __init__(self, config_path: str = "config/experiment.json"):
        self.config = json.load(open(config_path))
        self.best_metrics: IterationMetrics | None = None
        self.best_commit: str | None = None
        self.iteration: int = 0

    async def run_iteration(
        self,
        items: list[dict],
        cohort,               # StudentCohort (duck-typed)
        grade_fn,             # callable(item, response) -> grade_dict
        endpoint: str,
        model: str,
    ) -> IterationMetrics:
        """
        Single iteration:
        1. Run cohort through items (cohort.run_evaluation)
        2. Grade all responses (grade_fn)
        3. Update student memories based on grades
        4. Compute metrics
        5. Return metrics
        """

    def decide(self, metrics: IterationMetrics) -> bool:
        """
        Compare to best_metrics using is_improvement().
        If improved: update best_metrics, best_commit, return True.
        If not: revert to best_commit, return False.
        """

    async def run_loop(
        self,
        items: list[dict],
        cohort,
        grade_fn,
        analyze_fn,           # callable(metrics, best_metrics) -> list[improvement_dicts]
        apply_fn,             # callable(improvements) -> None
        endpoint: str,
        model: str,
    ):
        """
        Full inner loop:
        WHILE iteration < max_iterations AND not converged:
          1. run_iteration
          2. decide (keep/revert)
          3. if kept and not converged: analyze_fn -> apply_fn -> commit
          4. check convergence (no_improvement_streak)
          5. log to summary.tsv
        """

    def is_converged(self) -> bool:
        """Check convergence criteria from config."""

    def save_state(self, path: str):
        """Save experiment state to JSON."""

    @classmethod
    def load_state(cls, path: str) -> 'AutoresearchRunner':
        """Resume from saved state."""
```

### 4. `loop/progression.py` — Outer Loop (unit-by-unit)

```python
class CourseProgression:
    """Outer loop: advance through units 1-9 sequentially."""

    def __init__(self, config_path: str = "config/experiment.json"):
        self.config = json.load(open(config_path))
        self.current_unit: int = self.config.get("current_unit", 1)
        self.unit_results: dict = {}  # {unit: best IterationMetrics}

    async def run_unit(
        self,
        unit: int,
        cohort,
        items_for_unit: list[dict],
        grade_fn,
        analyze_fn,
        apply_fn,
        endpoint: str,
        model: str,
    ) -> IterationMetrics:
        """
        Run inner autoresearch loop on one unit.
        1. Restore cohort from prior-unit snapshots (or fresh if unit 1)
        2. Apply inter-unit forgetting gap
        3. Run AutoresearchRunner.run_loop()
        4. Snapshot cohort memory
        5. Return best metrics
        """

    async def run_course(self, ...):
        """
        Sequential outer loop:
        FOR unit = current_unit TO 9:
          1. Load items for this unit
          2. run_unit(unit, ...)
          3. Promote converged artifacts
          4. Advance current_unit
          5. Save progression state
        """

    def save_state(self, path: str):
        """Save progression state."""
```

### 5. `loop/__init__.py`
```python
from .metrics import IterationMetrics, compute_metrics, is_improvement
from .git_ops import create_branch, get_current_commit, commit_changes, revert_to_commit
from .runner import AutoresearchRunner
from .progression import CourseProgression
```

## Notes
- runner.py should log each iteration to both `logs/runs/{run_id}/metrics.json` and append to `logs/summary.tsv`
- Use `os.makedirs(exist_ok=True)` for log directories
- The runner must handle KeyboardInterrupt gracefully (save state before exiting)
