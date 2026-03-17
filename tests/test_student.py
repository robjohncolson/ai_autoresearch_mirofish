"""Test the SyntheticStudent class."""

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from simulator.student import StudentPersona, SyntheticStudent
from simulator.memory import StudentMemory


def _make_persona(**overrides) -> StudentPersona:
    """Create a test persona with sensible defaults."""
    defaults = dict(
        persona_id="test_001",
        ability_tier=3,
        kc_acquisition_rate=0.15,
        carelessness=0.06,
        guess_strategy="random",
        misconception_persistence=0.80,
        reading_comprehension=0.80,
        working_memory_slots=5,
    )
    defaults.update(overrides)
    return StudentPersona(**defaults)


def test_persona_creation():
    p = _make_persona(ability_tier=3)
    assert p.ability_tier == 3
    assert p.persona_id == "test_001"


def test_persona_fields():
    p = _make_persona()
    assert p.kc_acquisition_rate == 0.15
    assert p.carelessness == 0.06
    assert p.guess_strategy == "random"
    assert p.misconception_persistence == 0.80
    assert p.reading_comprehension == 0.80
    assert p.working_memory_slots == 5


def test_student_has_empty_memory_by_default():
    p = _make_persona()
    student = SyntheticStudent(p)
    assert len(student.memory.kc_states) == 0
    assert student.response_log == []


def test_student_with_provided_memory():
    p = _make_persona()
    mem = StudentMemory()
    mem.update("VAR-1.A", True, 0.0)
    student = SyntheticStudent(p, memory=mem)
    assert "VAR-1.A" in student.memory.kc_states


def test_student_snapshot_roundtrip():
    p = _make_persona()
    student = SyntheticStudent(p)
    student.memory.update("VAR-1.A", True, 1000.0)
    snap = student.snapshot()
    restored = SyntheticStudent.from_snapshot(snap)
    assert restored.persona.persona_id == "test_001"
    assert "VAR-1.A" in restored.memory.kc_states


def test_snapshot_preserves_all_persona_fields():
    p = _make_persona(persona_id="snap_test", ability_tier=5,
                      kc_acquisition_rate=0.25, carelessness=0.02)
    student = SyntheticStudent(p)
    snap = student.snapshot()
    restored = SyntheticStudent.from_snapshot(snap)
    assert restored.persona.persona_id == "snap_test"
    assert restored.persona.ability_tier == 5
    assert restored.persona.kc_acquisition_rate == 0.25
    assert restored.persona.carelessness == 0.02


def test_update_memory_from_grade_e():
    """Score E should boost all tagged KCs."""
    p = _make_persona()
    student = SyntheticStudent(p)
    item = {"item_id": "CR:U1-L1-Q01", "kc_tags": ["VAR-1.A"]}
    grade = {"score": "E", "matched_kcs": ["VAR-1.A"], "missing_kcs": []}
    student.update_memory_from_grade(item, grade, 1000.0)
    assert student.memory.kc_states["VAR-1.A"].correct_count == 1


def test_update_memory_from_grade_i():
    """Score I should penalize all tagged KCs."""
    p = _make_persona()
    student = SyntheticStudent(p)
    # First give them some knowledge
    student.memory.update("VAR-1.A", True, 500.0)
    before = student.memory.kc_states["VAR-1.A"].strength

    item = {"item_id": "CR:U1-L1-Q01", "kc_tags": ["VAR-1.A"]}
    grade = {"score": "I"}
    student.update_memory_from_grade(item, grade, 1000.0)
    after = student.memory.kc_states["VAR-1.A"].strength
    assert after < before


def test_update_memory_from_grade_p():
    """Score P should boost matched KCs and penalize missing KCs."""
    p = _make_persona()
    student = SyntheticStudent(p)
    item = {"item_id": "CR:U1-L1-Q01", "kc_tags": ["VAR-1.A", "UNC-1.A"]}
    grade = {
        "score": "P",
        "matched_kcs": ["VAR-1.A"],
        "missing_kcs": ["UNC-1.A"],
    }
    student.update_memory_from_grade(item, grade, 1000.0)
    # VAR-1.A should have been boosted (correct)
    assert student.memory.kc_states["VAR-1.A"].correct_count == 1
    # UNC-1.A should have been penalized (incorrect)
    assert student.memory.kc_states["UNC-1.A"].correct_count == 0


def test_update_memory_from_grade_multiple_kcs():
    """Grade E with multiple kc_tags should boost all of them."""
    p = _make_persona()
    student = SyntheticStudent(p)
    item = {"item_id": "Q1", "kc_tags": ["VAR-1.A", "VAR-1.B", "UNC-1.A"]}
    grade = {"score": "E"}
    student.update_memory_from_grade(item, grade, 1000.0)
    for kc_id in ["VAR-1.A", "VAR-1.B", "UNC-1.A"]:
        assert kc_id in student.memory.kc_states
        assert student.memory.kc_states[kc_id].correct_count == 1


def test_parse_response_mcq_single_letter():
    assert SyntheticStudent._parse_response("B", "mcq") == "B"
    assert SyntheticStudent._parse_response("a", "mcq") == "A"


def test_parse_response_mcq_with_paren():
    assert SyntheticStudent._parse_response("The answer is (C)", "mcq") == "C"


def test_parse_response_frq_passthrough():
    text = "The standard deviation is 2.5"
    assert SyntheticStudent._parse_response(text, "frq") == text
