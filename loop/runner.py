"""Inner autoresearch loop runner (per-unit keep-if-better iteration).

Depends only on sibling modules inside ``loop/`` and the Python stdlib.
External components (simulator cohort, grading function, optimizer
callbacks) are accepted as duck-typed callables / objects so there are
zero imports from ``simulator/`` or ``optimizer/``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path

from .metrics import (
    IterationMetrics,
    compute_metrics,
    dict_to_metrics,
    is_improvement,
    metrics_to_dict,
    metrics_to_tsv_row,
    metrics_tsv_header,
)
from .git_ops import commit_changes, get_current_commit, revert_to_commit

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _logs_dir() -> Path:
    return _PROJECT_ROOT / "logs"


def _ensure_dir(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p


# ---------------------------------------------------------------------------
# AutoresearchRunner
# ---------------------------------------------------------------------------

class AutoresearchRunner:
    """Inner loop: keep-if-better iteration on a single unit.

    The runner is intentionally agnostic about the concrete student
    simulator and the optimizer.  It accepts:

    * A *cohort* object whose ``run_evaluation(items, endpoint, model)``
      method returns a list of response dicts.
    * A *grade_fn(item, response) -> grade_dict* callable.
    * An *analyze_fn(metrics, best_metrics) -> list[improvement_dicts]*
      callable that proposes changes.
    * An *apply_fn(improvements) -> None* callable that mutates the
      curriculum on disk.
    """

    def __init__(self, config_path: str = "config/experiment.json"):
        # Allow config file to not exist yet (for testing / early dev)
        self.config: dict = {}
        self.config_path = config_path
        if os.path.isfile(config_path):
            with open(config_path, "r", encoding="utf-8") as fh:
                self.config = json.load(fh)

        self.best_metrics: IterationMetrics | None = None
        self.best_commit: str | None = None
        self.iteration: int = 0

        # Loop behaviour knobs (with sensible defaults)
        loop_cfg = self.config.get("loop", {})
        self.max_iterations: int = loop_cfg.get("max_iterations", 50)
        self.no_improvement_limit: int = loop_cfg.get("no_improvement_streak", 5)
        self.scoring_weights: dict = loop_cfg.get("scoring_weights", {"E": 3, "P": 2, "I": 1})
        self.guards: dict = loop_cfg.get("guards", {
            "max_unit_regression": 0.1,
            "max_holdout_divergence": 0.05,
        })

        # Runtime bookkeeping
        self._no_improvement_streak: int = 0
        self._converged: bool = False
        self.run_id: str = loop_cfg.get("run_id", f"run-{int(time.time())}")

    # ----- single iteration ------------------------------------------------

    async def run_iteration(
        self,
        items: list[dict],
        cohort,                    # duck-typed: has .run_evaluation()
        grade_fn,                  # callable(item, response) -> grade_dict
        endpoint: str,
        model: str,
    ) -> IterationMetrics:
        """Execute one evaluate-grade-metrics cycle.

        Steps
        -----
        1. Run the cohort through the items.
        2. Grade every response.
        3. Compute aggregate metrics.
        4. Return the metrics (caller decides keep/revert).
        """
        self.iteration += 1
        logger.info("=== Iteration %d ===", self.iteration)

        # 1. Run evaluation  (may be sync or async)
        if asyncio.iscoroutinefunction(getattr(cohort, "run_evaluation", None)):
            responses = await cohort.run_evaluation(items, endpoint, model)
        else:
            responses = cohort.run_evaluation(items, endpoint, model)

        # 2. Grade
        grades: list[dict] = []
        items_by_id = {it["item_id"]: it for it in items}
        for resp in responses:
            item = items_by_id.get(resp.get("item_id", ""), {})
            grade = grade_fn(item, resp)
            # Merge item metadata into the grade dict for metrics
            merged = {
                "student_id": resp.get("student_id", "unknown"),
                "item_id": resp.get("item_id", "unknown"),
                "item_type": item.get("item_type", "MCQ"),
                "unit": item.get("unit", "unknown"),
                "kc_tags": item.get("kc_tags", []),
                **grade,
            }
            grades.append(merged)

        # 3. Update student memories if cohort supports it
        if hasattr(cohort, "update_memories"):
            if asyncio.iscoroutinefunction(cohort.update_memories):
                await cohort.update_memories(grades)
            else:
                cohort.update_memories(grades)

        # 4. Compute metrics
        commit_hash = get_current_commit()
        metrics = compute_metrics(
            grades,
            curriculum_version=commit_hash,
            iteration_id=self.iteration,
            scoring_weights=self.scoring_weights,
        )

        # 5. Log iteration
        self._log_iteration(metrics)

        return metrics

    # ----- decide -----------------------------------------------------------

    def decide(self, metrics: IterationMetrics) -> bool:
        """Compare *metrics* to the best-known and keep or revert.

        * If this is the first iteration, accept unconditionally.
        * If ``is_improvement`` returns True, update ``best_metrics``
          and ``best_commit``.
        * Otherwise, hard-revert to ``best_commit``.

        Returns ``True`` if the iteration was kept.
        """
        if self.best_metrics is None:
            # First iteration — accept unconditionally
            self.best_metrics = metrics
            self.best_commit = metrics.curriculum_version
            self._no_improvement_streak = 0
            logger.info("First iteration accepted (mean_score=%.4f)", metrics.mean_score)
            return True

        if is_improvement(metrics, self.best_metrics, guards=self.guards):
            old_score = self.best_metrics.mean_score
            self.best_metrics = metrics
            self.best_commit = metrics.curriculum_version
            self._no_improvement_streak = 0
            logger.info(
                "KEEP: mean_score %.4f -> %.4f", old_score, metrics.mean_score
            )
            return True

        # Regression — revert
        logger.info(
            "REVERT: mean_score %.4f did not beat %.4f (reverting to %s)",
            metrics.mean_score,
            self.best_metrics.mean_score,
            self.best_commit,
        )
        self._no_improvement_streak += 1
        if self.best_commit:
            revert_to_commit(self.best_commit)
        return False

    # ----- full loop --------------------------------------------------------

    async def run_loop(
        self,
        items: list[dict],
        cohort,
        grade_fn,
        analyze_fn,               # callable(metrics, best) -> list[dict]
        apply_fn,                  # callable(improvements) -> None
        endpoint: str,
        model: str,
    ):
        """Run the full inner keep-if-better loop until convergence.

        Handles ``KeyboardInterrupt`` gracefully by saving state and
        returning early.
        """
        logger.info("Starting autoresearch loop (run_id=%s, max_iter=%d)",
                     self.run_id, self.max_iterations)
        try:
            while self.iteration < self.max_iterations and not self._converged:
                # 1. Evaluate
                metrics = await self.run_iteration(
                    items, cohort, grade_fn, endpoint, model,
                )

                # 2. Decide keep/revert
                kept = self.decide(metrics)

                # 3. Log to summary.tsv
                patch_desc = f"iter-{self.iteration:03d}"
                self._append_summary_tsv(metrics, kept, patch_desc)

                # 4. Check convergence
                if self.is_converged():
                    logger.info("Converged after %d iterations.", self.iteration)
                    break

                # 5. If kept and not converged, propose + apply improvements
                if kept:
                    if asyncio.iscoroutinefunction(analyze_fn):
                        improvements = await analyze_fn(metrics, self.best_metrics)
                    else:
                        improvements = analyze_fn(metrics, self.best_metrics)

                    if improvements:
                        if asyncio.iscoroutinefunction(apply_fn):
                            await apply_fn(improvements)
                        else:
                            apply_fn(improvements)

                        # Commit the changes
                        msg = (
                            f"iter-{self.iteration:03d}: "
                            f"mean_score {metrics.mean_score:.2f}, "
                            f"applied {len(improvements)} patches"
                        )
                        commit_changes(msg)
                else:
                    # Revert already happened in decide(); the optimizer
                    # should still try a *different* patch direction.
                    if asyncio.iscoroutinefunction(analyze_fn):
                        improvements = await analyze_fn(metrics, self.best_metrics)
                    else:
                        improvements = analyze_fn(metrics, self.best_metrics)

                    if improvements:
                        if asyncio.iscoroutinefunction(apply_fn):
                            await apply_fn(improvements)
                        else:
                            apply_fn(improvements)

                        msg = (
                            f"iter-{self.iteration:03d}: "
                            f"retry after revert, "
                            f"applied {len(improvements)} patches"
                        )
                        commit_changes(msg)

        except KeyboardInterrupt:
            logger.warning("KeyboardInterrupt — saving state and exiting.")
        finally:
            state_path = str(
                _ensure_dir(_logs_dir() / "runs" / self.run_id) / "state.json"
            )
            self.save_state(state_path)
            logger.info("State saved to %s", state_path)

    # ----- convergence ------------------------------------------------------

    def is_converged(self) -> bool:
        """Return ``True`` when the no-improvement streak exceeds the limit."""
        if self._no_improvement_streak >= self.no_improvement_limit:
            self._converged = True
        return self._converged

    # ----- state persistence ------------------------------------------------

    def save_state(self, path: str) -> None:
        """Persist runner state to a JSON file so the loop can be resumed."""
        _ensure_dir(Path(path).parent)
        state = {
            "run_id": self.run_id,
            "iteration": self.iteration,
            "max_iterations": self.max_iterations,
            "no_improvement_limit": self.no_improvement_limit,
            "no_improvement_streak": self._no_improvement_streak,
            "converged": self._converged,
            "scoring_weights": self.scoring_weights,
            "guards": self.guards,
            "best_commit": self.best_commit,
            "best_metrics": metrics_to_dict(self.best_metrics) if self.best_metrics else None,
            "config_path": self.config_path,
        }
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2)

    @classmethod
    def load_state(cls, path: str) -> "AutoresearchRunner":
        """Resume a runner from a previously-saved state file."""
        with open(path, "r", encoding="utf-8") as fh:
            state = json.load(fh)

        runner = cls(config_path=state.get("config_path", "config/experiment.json"))
        runner.run_id = state["run_id"]
        runner.iteration = state["iteration"]
        runner.max_iterations = state["max_iterations"]
        runner.no_improvement_limit = state["no_improvement_limit"]
        runner._no_improvement_streak = state["no_improvement_streak"]
        runner._converged = state["converged"]
        runner.scoring_weights = state["scoring_weights"]
        runner.guards = state["guards"]
        runner.best_commit = state["best_commit"]
        runner.best_metrics = (
            dict_to_metrics(state["best_metrics"])
            if state["best_metrics"]
            else None
        )
        return runner

    # ----- logging helpers --------------------------------------------------

    def _log_iteration(self, metrics: IterationMetrics) -> None:
        """Write per-iteration metrics JSON into ``logs/runs/{run_id}/``."""
        run_dir = _ensure_dir(_logs_dir() / "runs" / self.run_id)
        out_path = run_dir / f"iter-{self.iteration:03d}.json"
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(metrics_to_dict(metrics), fh, indent=2)
        logger.debug("Iteration metrics written to %s", out_path)

    def _append_summary_tsv(
        self, metrics: IterationMetrics, kept: bool, patch_desc: str
    ) -> None:
        """Append one row to ``logs/summary.tsv``, creating it with a
        header if it doesn't exist yet."""
        tsv_path = _logs_dir() / "summary.tsv"
        _ensure_dir(tsv_path.parent)
        write_header = not tsv_path.exists()
        with open(tsv_path, "a", encoding="utf-8") as fh:
            if write_header:
                fh.write(metrics_tsv_header() + "\n")
            fh.write(metrics_to_tsv_row(metrics, kept, patch_desc) + "\n")
