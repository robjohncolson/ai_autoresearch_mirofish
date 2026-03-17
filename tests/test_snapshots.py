"""Test student memory snapshots across units."""

import pytest
import tempfile
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from simulator.memory import StudentMemory
from simulator.student import StudentPersona, SyntheticStudent
from simulator.cohort import StudentCohort


def _make_personas(n: int) -> list[StudentPersona]:
    """Create n test personas."""
    return [
        StudentPersona(
            persona_id=f"test_{i:03d}",
            ability_tier=3,
            kc_acquisition_rate=0.15,
            carelessness=0.06,
            guess_strategy="random",
            misconception_persistence=0.80,
            reading_comprehension=0.80,
            working_memory_slots=5,
        )
        for i in range(n)
    ]


def test_cohort_snapshot_and_restore():
    personas = _make_personas(3)
    cohort = StudentCohort.from_personas(personas)

    # Simulate some learning
    for student in cohort.students:
        student.memory.update("VAR-1.A", True, 1000.0)
        student.memory.update("UNC-1.A", False, 1000.0, error_mode="misconception_A")

    with tempfile.TemporaryDirectory() as tmpdir:
        cohort.save_snapshots(tmpdir)
        files = os.listdir(tmpdir)
        assert len(files) == 3  # one file per student

        restored = StudentCohort.from_snapshots(tmpdir)
        assert len(restored.students) == 3
        for student in restored.students:
            assert "VAR-1.A" in student.memory.kc_states
            assert student.memory.kc_states["UNC-1.A"].error_mode == "misconception_A"


def test_inter_unit_gap_applies_to_cohort():
    personas = _make_personas(1)
    cohort = StudentCohort.from_personas(personas)
    cohort.students[0].memory.update("VAR-1.A", True, 0.0)
    before = cohort.students[0].memory.kc_states["VAR-1.A"].strength
    cohort.apply_inter_unit_gap(336 * 3600)  # 2 weeks
    after = cohort.students[0].memory.kc_states["VAR-1.A"].strength
    assert after < before


def test_snapshot_preserves_error_mode():
    personas = _make_personas(1)
    cohort = StudentCohort.from_personas(personas)
    cohort.students[0].memory.update("VAR-1.A", False, 1000.0,
                                      error_mode="misconception_B")

    with tempfile.TemporaryDirectory() as tmpdir:
        cohort.save_snapshots(tmpdir)
        restored = StudentCohort.from_snapshots(tmpdir)
        kc = restored.students[0].memory.kc_states["VAR-1.A"]
        assert kc.error_mode == "misconception_B"
        assert kc.error_strength > 0.0


def test_snapshot_preserves_counts():
    personas = _make_personas(1)
    cohort = StudentCohort.from_personas(personas)
    student = cohort.students[0]
    student.memory.update("VAR-1.A", True, 100.0)
    student.memory.update("VAR-1.A", True, 200.0)
    student.memory.update("VAR-1.A", False, 300.0)

    with tempfile.TemporaryDirectory() as tmpdir:
        cohort.save_snapshots(tmpdir)
        restored = StudentCohort.from_snapshots(tmpdir)
        kc = restored.students[0].memory.kc_states["VAR-1.A"]
        assert kc.correct_count == 2
        assert kc.exposure_count == 3


def test_multiple_units_cumulative_memory():
    """Simulate learning across two units with forgetting between them."""
    personas = _make_personas(2)
    cohort = StudentCohort.from_personas(personas)

    # Unit 1: learn VAR-1.A
    for student in cohort.students:
        student.memory.update("VAR-1.A", True, 0.0)

    # Save after unit 1
    with tempfile.TemporaryDirectory() as tmpdir:
        cohort.save_snapshots(tmpdir)

        # Apply inter-unit forgetting
        cohort.apply_inter_unit_gap(7 * 24 * 3600)  # 1 week

        # Unit 2: learn UNC-2.A (prior knowledge decayed)
        for student in cohort.students:
            student.memory.update("UNC-2.A", True, 7 * 24 * 3600)

        # Check cumulative state
        for student in cohort.students:
            assert "VAR-1.A" in student.memory.kc_states
            assert "UNC-2.A" in student.memory.kc_states
            # VAR-1.A should have decayed
            assert student.memory.kc_states["VAR-1.A"].strength < 0.15


def test_cohort_from_personas_creates_fresh_students():
    personas = _make_personas(5)
    cohort = StudentCohort.from_personas(personas)
    assert len(cohort.students) == 5
    for student in cohort.students:
        assert len(student.memory.kc_states) == 0


def test_cohort_summary():
    personas = _make_personas(3)
    cohort = StudentCohort.from_personas(personas)
    summary = cohort.get_summary()
    assert summary["n_students"] == 3
    assert summary["total_kcs_tracked"] == 0


def test_empty_snapshot_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        # Empty directory should produce empty cohort
        cohort = StudentCohort.from_snapshots(tmpdir)
        assert len(cohort.students) == 0


def test_snapshot_dir_not_found():
    with pytest.raises(FileNotFoundError):
        StudentCohort.from_snapshots("/nonexistent/path/that/does/not/exist")
