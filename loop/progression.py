"""Outer autoresearch loop: unit-by-unit course progression.

Manages the sequential advancement through Units 1-9, including
student-memory snapshotting and inter-unit forgetting.  Like the inner
runner, this module is simulator/optimizer-agnostic — it accepts
duck-typed objects and callables.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

from .metrics import IterationMetrics, metrics_to_dict, dict_to_metrics
from .runner import AutoresearchRunner

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

_SNAPSHOT_DIR = _PROJECT_ROOT / "snapshots"


def _ensure_dir(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p


# ---------------------------------------------------------------------------
# CourseProgression
# ---------------------------------------------------------------------------

class CourseProgression:
    """Outer loop: advance through units 1-9 sequentially.

    Each unit is optimised by an :class:`~loop.runner.AutoresearchRunner`
    inner loop.  Between units the student cohort's memory is
    snapshotted (so that later units see cumulative knowledge, with
    forgetting).
    """

    def __init__(self, config_path: str = "config/experiment.json"):
        self.config: dict = {}
        self.config_path = config_path
        if os.path.isfile(config_path):
            with open(config_path, "r", encoding="utf-8") as fh:
                self.config = json.load(fh)

        self.current_unit: int = self.config.get("current_unit", 1)
        self.total_units: int = self.config.get("total_units", 9)
        self.unit_results: dict[int, dict] = {}  # {unit: metrics_dict}

        # Inter-unit forgetting gap (simulated time between units, seconds)
        self.inter_unit_gap: float = self.config.get("inter_unit_gap", 7 * 24 * 3600)  # 1 week default

    # ----- snapshots --------------------------------------------------------

    def _snapshot_dir_for_unit(self, unit: int) -> Path:
        return _ensure_dir(_SNAPSHOT_DIR / f"unit_{unit}")

    def snapshot_cohort(self, unit: int, cohort) -> None:
        """Save every student's memory state after *unit* converges.

        Expects *cohort* to expose an iterable of student objects, each
        having ``persona_id`` (str) and ``get_all_kc_states()`` (-> dict).
        """
        snap_dir = self._snapshot_dir_for_unit(unit)
        students = getattr(cohort, "students", cohort)  # allow bare list
        for student in students:
            persona_id = getattr(student, "persona_id", str(id(student)))
            snapshot = {
                "persona_id": persona_id,
                "unit_completed": unit,
                "kc_states": (
                    student.get_all_kc_states()
                    if hasattr(student, "get_all_kc_states")
                    else {}
                ),
                "timestamp": time.time(),
            }
            out = snap_dir / f"{persona_id}.json"
            with open(out, "w", encoding="utf-8") as fh:
                json.dump(snapshot, fh, indent=2)
        logger.info("Snapshot saved for %d students (unit %d)", len(list(students)), unit)

    def restore_cohort(self, unit: int, cohort) -> None:
        """Restore student memories from the snapshot taken after *unit*.

        Expects each student to have ``restore_kc_states(kc_dict)``
        and ``apply_forgetting(elapsed_time=float)`` methods.
        """
        snap_dir = self._snapshot_dir_for_unit(unit)
        if not snap_dir.exists():
            logger.warning("No snapshot directory for unit %d — skipping restore.", unit)
            return

        students = getattr(cohort, "students", cohort)
        students_by_id = {
            getattr(s, "persona_id", str(id(s))): s for s in students
        }

        for snap_file in snap_dir.glob("*.json"):
            with open(snap_file, "r", encoding="utf-8") as fh:
                snap = json.load(fh)
            pid = snap["persona_id"]
            student = students_by_id.get(pid)
            if student is None:
                logger.debug("Snapshot for %s has no matching student — skipped.", pid)
                continue
            if hasattr(student, "restore_kc_states"):
                student.restore_kc_states(snap["kc_states"])
            if hasattr(student, "apply_forgetting"):
                student.apply_forgetting(elapsed_time=self.inter_unit_gap)

        logger.info("Restored cohort from unit-%d snapshot (gap=%.0f s)", unit, self.inter_unit_gap)

    # ----- single unit ------------------------------------------------------

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
        """Run the inner autoresearch loop on one unit.

        Steps
        -----
        1. If *unit* > 1, restore cohort from prior-unit snapshot and
           apply inter-unit forgetting.
        2. Run :meth:`AutoresearchRunner.run_loop`.
        3. Snapshot cohort memory.
        4. Return the best metrics achieved.
        """
        logger.info("===== Unit %d =====", unit)

        # 1. Restore from prior unit (if applicable)
        if unit > 1:
            self.restore_cohort(unit - 1, cohort)
        else:
            logger.info("Unit 1 — starting with fresh cohort memory.")

        # 2. Inner loop
        runner = AutoresearchRunner(config_path=self.config_path)
        runner.run_id = f"unit-{unit}-{int(time.time())}"

        await runner.run_loop(
            items=items_for_unit,
            cohort=cohort,
            grade_fn=grade_fn,
            analyze_fn=analyze_fn,
            apply_fn=apply_fn,
            endpoint=endpoint,
            model=model,
        )

        # 3. Snapshot cohort
        self.snapshot_cohort(unit, cohort)

        # 4. Record results
        best = runner.best_metrics
        if best is not None:
            self.unit_results[unit] = metrics_to_dict(best)
        logger.info(
            "Unit %d complete — best mean_score=%.4f",
            unit,
            best.mean_score if best else 0.0,
        )
        return best  # type: ignore[return-value]

    # ----- full course ------------------------------------------------------

    async def run_course(
        self,
        cohort,
        items_by_unit: dict[int, list[dict]],
        grade_fn,
        analyze_fn,
        apply_fn,
        endpoint: str,
        model: str,
    ):
        """Sequential outer loop: iterate through all remaining units.

        Parameters
        ----------
        items_by_unit : dict mapping unit number (int) to the list of
            item dicts for that unit.
        """
        logger.info(
            "Starting course progression from unit %d to %d",
            self.current_unit,
            self.total_units,
        )
        try:
            for unit in range(self.current_unit, self.total_units + 1):
                unit_items = items_by_unit.get(unit, [])
                if not unit_items:
                    logger.warning("No items for unit %d — skipping.", unit)
                    continue

                best = await self.run_unit(
                    unit=unit,
                    cohort=cohort,
                    items_for_unit=unit_items,
                    grade_fn=grade_fn,
                    analyze_fn=analyze_fn,
                    apply_fn=apply_fn,
                    endpoint=endpoint,
                    model=model,
                )

                # Advance pointer
                self.current_unit = unit + 1
                self.save_state(
                    str(_ensure_dir(_PROJECT_ROOT / "logs") / "progression_state.json")
                )

                logger.info(
                    "Unit %d promoted.  Advancing to unit %d.",
                    unit,
                    self.current_unit,
                )
        except KeyboardInterrupt:
            logger.warning("KeyboardInterrupt during course progression — saving state.")
        finally:
            self.save_state(
                str(_ensure_dir(_PROJECT_ROOT / "logs") / "progression_state.json")
            )

    # ----- state persistence ------------------------------------------------

    def save_state(self, path: str) -> None:
        """Persist progression state to JSON for resumption."""
        _ensure_dir(Path(path).parent)
        state = {
            "current_unit": self.current_unit,
            "total_units": self.total_units,
            "inter_unit_gap": self.inter_unit_gap,
            "config_path": self.config_path,
            "unit_results": {
                str(k): v for k, v in self.unit_results.items()
            },
        }
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2)
        logger.info("Progression state saved to %s", path)

    @classmethod
    def load_state(cls, path: str) -> "CourseProgression":
        """Resume from a previously-saved progression state."""
        with open(path, "r", encoding="utf-8") as fh:
            state = json.load(fh)

        prog = cls(config_path=state.get("config_path", "config/experiment.json"))
        prog.current_unit = state["current_unit"]
        prog.total_units = state["total_units"]
        prog.inter_unit_gap = state.get("inter_unit_gap", 7 * 24 * 3600)
        prog.unit_results = {
            int(k): v for k, v in state.get("unit_results", {}).items()
        }
        return prog
