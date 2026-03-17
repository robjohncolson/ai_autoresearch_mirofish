"""Cohort manager for parallel synthetic student evaluation.

A ``StudentCohort`` holds N ``SyntheticStudent`` instances and can run
them all through a set of canonical assessment items concurrently,
throttled by an ``asyncio.Semaphore`` to avoid overwhelming the local
Ollama server.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

from .memory import StudentMemory, recall_probability
from .student import StudentPersona, SyntheticStudent


class StudentCohort:
    """Manages a cohort of synthetic students."""

    def __init__(self, students: list[SyntheticStudent]) -> None:
        self.students = students

    # -- factory methods ------------------------------------------------

    @classmethod
    def from_personas(cls, personas: list[StudentPersona]) -> StudentCohort:
        """Create a cohort of fresh students from persona definitions."""
        students = [SyntheticStudent(persona=p) for p in personas]
        return cls(students=students)

    @classmethod
    def from_snapshots(cls, snapshot_dir: str) -> StudentCohort:
        """Restore a cohort from a directory of snapshot JSON files.

        Each file in *snapshot_dir* should be a JSON file produced by
        ``SyntheticStudent.snapshot()``.
        """
        students: list[SyntheticStudent] = []
        snap_path = Path(snapshot_dir)
        if not snap_path.is_dir():
            raise FileNotFoundError(f"Snapshot directory not found: {snapshot_dir}")

        for fpath in sorted(snap_path.glob("*.json")):
            with open(fpath, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            students.append(SyntheticStudent.from_snapshot(data))

        return cls(students=students)

    # -- parallel evaluation --------------------------------------------

    async def run_evaluation(
        self,
        items: list[dict],
        endpoint: str,
        model: str = "qwen3:8b",
        lesson_texts: dict[str, str] | None = None,
        max_concurrent: int = 5,
    ) -> list[dict]:
        """Run all students through all items.

        Parameters
        ----------
        items : list[dict]
            Canonical assessment items.
        endpoint : str
            Ollama API base URL (e.g. ``"http://localhost:11434"``).
        model : str
            Ollama model tag.
        lesson_texts : dict[str, str] | None
            Optional mapping from ``item_id`` to lesson exposition text.
        max_concurrent : int
            Maximum number of concurrent LLM requests (controlled via
            ``asyncio.Semaphore``).

        Returns
        -------
        list[dict]
            One result dict per student-item pair:
            ``{"student_id": str, "item_id": str, "response": str, "timestamp": float}``
        """
        semaphore = asyncio.Semaphore(max_concurrent)
        results: list[dict] = []
        results_lock = asyncio.Lock()

        async def _run_one(student: SyntheticStudent, item: dict) -> None:
            async with semaphore:
                item_id = item.get("item_id", "")
                lesson_text = (lesson_texts or {}).get(item_id)
                result = await student.answer_item(
                    item=item,
                    endpoint=endpoint,
                    model=model,
                    lesson_text=lesson_text,
                )
                entry = {
                    "student_id": student.persona.persona_id,
                    "item_id": result["item_id"],
                    "response": result["response"],
                    "raw_output": result["raw_output"],
                    "timestamp": result["timestamp"],
                }
                async with results_lock:
                    results.append(entry)

        # Build list of tasks: every student x every item
        tasks: list[asyncio.Task] = []
        for student in self.students:
            for item in items:
                tasks.append(asyncio.create_task(_run_one(student, item)))

        # Await all tasks, collecting any exceptions
        done = await asyncio.gather(*tasks, return_exceptions=True)
        # Log errors but don't crash the whole cohort
        for i, outcome in enumerate(done):
            if isinstance(outcome, BaseException):
                # Attach error info to results for diagnostics
                student_idx = i // len(items)
                item_idx = i % len(items)
                student_id = self.students[student_idx].persona.persona_id if student_idx < len(self.students) else "unknown"
                item_id = items[item_idx].get("item_id", "unknown") if item_idx < len(items) else "unknown"
                error_entry = {
                    "student_id": student_id,
                    "item_id": item_id,
                    "response": "",
                    "raw_output": f"ERROR: {outcome}",
                    "timestamp": time.time(),
                    "error": True,
                }
                results.append(error_entry)

        return results

    # -- inter-unit forgetting ------------------------------------------

    def apply_inter_unit_gap(self, gap_seconds: float) -> None:
        """Apply forgetting curves to all students."""
        for student in self.students:
            student.memory.apply_inter_unit_gap(gap_seconds)

    # -- persistence ----------------------------------------------------

    def save_snapshots(self, output_dir: str) -> None:
        """Save each student's state to ``output_dir/{persona_id}.json``."""
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)

        for student in self.students:
            fpath = out_path / f"{student.persona.persona_id}.json"
            snapshot = student.snapshot()
            with open(fpath, "w", encoding="utf-8") as fh:
                json.dump(snapshot, fh, indent=2, ensure_ascii=False)

    # -- summary statistics ---------------------------------------------

    def get_summary(self) -> dict:
        """Return summary stats for the cohort.

        Returns a dict with keys:
        - ``n_students``: number of students
        - ``avg_kc_strength``: average strength across all students and KCs
        - ``avg_known_kcs``: average number of KCs above threshold
        - ``tier_breakdown``: count of students per ability tier
        - ``total_kcs_tracked``: total unique KC ids across the cohort
        """
        now = time.time()

        n = len(self.students)
        if n == 0:
            return {
                "n_students": 0,
                "avg_kc_strength": 0.0,
                "avg_known_kcs": 0.0,
                "tier_breakdown": {},
                "total_kcs_tracked": 0,
            }

        total_strength = 0.0
        total_kc_count = 0
        total_known = 0
        tier_counts: dict[int, int] = {}
        all_kc_ids: set[str] = set()

        for student in self.students:
            tier = student.persona.ability_tier
            tier_counts[tier] = tier_counts.get(tier, 0) + 1

            for kc in student.memory.kc_states.values():
                total_strength += kc.strength
                total_kc_count += 1
                all_kc_ids.add(kc.kc_id)

            known = student.memory.get_known_kcs(now, threshold=0.3)
            total_known += len(known)

        avg_strength = total_strength / total_kc_count if total_kc_count > 0 else 0.0
        avg_known = total_known / n

        return {
            "n_students": n,
            "avg_kc_strength": round(avg_strength, 4),
            "avg_known_kcs": round(avg_known, 2),
            "tier_breakdown": tier_counts,
            "total_kcs_tracked": len(all_kc_ids),
        }
