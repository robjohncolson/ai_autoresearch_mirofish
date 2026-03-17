"""Test metrics computation and improvement check."""

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loop.metrics import compute_metrics, is_improvement, IterationMetrics


def test_compute_metrics_basic():
    grades = [
        {"student_id": "s1", "item_id": "i1", "item_type": "mcq", "unit": 1, "kc_tags": ["VAR-1.A"], "score": "E"},
        {"student_id": "s1", "item_id": "i2", "item_type": "frq", "unit": 1, "kc_tags": ["UNC-1.A"], "score": "P"},
        {"student_id": "s2", "item_id": "i1", "item_type": "mcq", "unit": 1, "kc_tags": ["VAR-1.A"], "score": "I"},
    ]
    m = compute_metrics(grades, "abc123", 1)
    assert m.n_students == 2
    assert m.n_items == 2
    assert 0 < m.mean_score < 3


def test_compute_metrics_empty():
    m = compute_metrics([], "abc", 0)
    assert m.n_students == 0
    assert m.n_items == 0
    assert m.mean_score == 0.0


def test_compute_metrics_all_correct():
    grades = [
        {"student_id": "s1", "item_id": "i1", "item_type": "mcq", "unit": 1, "kc_tags": ["VAR-1.A"], "score": "E"},
        {"student_id": "s2", "item_id": "i1", "item_type": "mcq", "unit": 1, "kc_tags": ["VAR-1.A"], "score": "E"},
    ]
    m = compute_metrics(grades, "test", 1)
    assert m.mcq_accuracy == 1.0
    assert m.mean_score == 3.0


def test_compute_metrics_mcq_accuracy():
    grades = [
        {"student_id": "s1", "item_id": "i1", "item_type": "mcq", "unit": 1, "kc_tags": [], "score": "E"},
        {"student_id": "s2", "item_id": "i1", "item_type": "mcq", "unit": 1, "kc_tags": [], "score": "I"},
        {"student_id": "s3", "item_id": "i1", "item_type": "mcq", "unit": 1, "kc_tags": [], "score": "E"},
        {"student_id": "s4", "item_id": "i1", "item_type": "mcq", "unit": 1, "kc_tags": [], "score": "I"},
    ]
    m = compute_metrics(grades, "test", 1)
    assert m.mcq_accuracy == pytest.approx(0.5)


def test_compute_metrics_frq_rates():
    grades = [
        {"student_id": "s1", "item_id": "f1", "item_type": "frq", "unit": 1, "kc_tags": [], "score": "E"},
        {"student_id": "s2", "item_id": "f1", "item_type": "frq", "unit": 1, "kc_tags": [], "score": "P"},
        {"student_id": "s3", "item_id": "f1", "item_type": "frq", "unit": 1, "kc_tags": [], "score": "I"},
    ]
    m = compute_metrics(grades, "test", 1)
    assert m.frq_e_rate == pytest.approx(1 / 3, abs=0.01)
    assert m.frq_p_rate == pytest.approx(1 / 3, abs=0.01)
    assert m.frq_i_rate == pytest.approx(1 / 3, abs=0.01)


def test_compute_metrics_kc_mastery():
    grades = [
        {"student_id": "s1", "item_id": "i1", "item_type": "mcq", "unit": 1, "kc_tags": ["VAR-1.A"], "score": "E"},
        {"student_id": "s2", "item_id": "i1", "item_type": "mcq", "unit": 1, "kc_tags": ["VAR-1.A"], "score": "I"},
    ]
    m = compute_metrics(grades, "test", 1)
    assert "VAR-1.A" in m.kc_mastery
    assert m.kc_mastery["VAR-1.A"] == pytest.approx(0.5)


def test_compute_metrics_unit_scores():
    grades = [
        {"student_id": "s1", "item_id": "i1", "item_type": "mcq", "unit": 1, "kc_tags": [], "score": "E"},
        {"student_id": "s1", "item_id": "i2", "item_type": "mcq", "unit": 2, "kc_tags": [], "score": "I"},
    ]
    m = compute_metrics(grades, "test", 1)
    assert "1" in m.unit_scores
    assert "2" in m.unit_scores
    assert m.unit_scores["1"] > m.unit_scores["2"]


def test_is_improvement_basic():
    best = IterationMetrics(
        curriculum_version="a", iteration_id=1, timestamp=0, n_students=10,
        n_items=5, mean_score=2.0, mcq_accuracy=0.5, frq_e_rate=0.2,
        frq_p_rate=0.3, frq_i_rate=0.5, unit_scores={1: 2.0},
    )
    better = IterationMetrics(
        curriculum_version="b", iteration_id=2, timestamp=1, n_students=10,
        n_items=5, mean_score=2.3, mcq_accuracy=0.6, frq_e_rate=0.3,
        frq_p_rate=0.3, frq_i_rate=0.4, unit_scores={1: 2.3},
    )
    assert is_improvement(better, best)


def test_is_improvement_rejects_regression():
    best = IterationMetrics(
        curriculum_version="a", iteration_id=1, timestamp=0, n_students=10,
        n_items=5, mean_score=2.5, mcq_accuracy=0.5, frq_e_rate=0.2,
        frq_p_rate=0.3, frq_i_rate=0.5, unit_scores={1: 2.5},
    )
    worse = IterationMetrics(
        curriculum_version="b", iteration_id=2, timestamp=1, n_students=10,
        n_items=5, mean_score=2.3, mcq_accuracy=0.4, frq_e_rate=0.1,
        frq_p_rate=0.3, frq_i_rate=0.6, unit_scores={1: 2.3},
    )
    assert not is_improvement(worse, best)


def test_is_improvement_rejects_equal():
    m = IterationMetrics(
        curriculum_version="a", iteration_id=1, timestamp=0, n_students=10,
        n_items=5, mean_score=2.0, mcq_accuracy=0.5, frq_e_rate=0.2,
        frq_p_rate=0.3, frq_i_rate=0.5, unit_scores={1: 2.0},
    )
    assert not is_improvement(m, m)


def test_is_improvement_rejects_unit_regression():
    """Even if mean improves, a big per-unit regression should be rejected."""
    best = IterationMetrics(
        curriculum_version="a", iteration_id=1, timestamp=0, n_students=10,
        n_items=5, mean_score=2.0, mcq_accuracy=0.5, frq_e_rate=0.2,
        frq_p_rate=0.3, frq_i_rate=0.5, unit_scores={1: 2.5, 2: 1.5},
    )
    candidate = IterationMetrics(
        curriculum_version="b", iteration_id=2, timestamp=1, n_students=10,
        n_items=5, mean_score=2.1, mcq_accuracy=0.6, frq_e_rate=0.3,
        frq_p_rate=0.3, frq_i_rate=0.4,
        unit_scores={1: 2.0, 2: 2.2},  # unit 1 regressed by 0.5
    )
    assert not is_improvement(candidate, best)


def test_is_improvement_holdout_guard():
    """Holdout divergence guard should block."""
    best = IterationMetrics(
        curriculum_version="a", iteration_id=1, timestamp=0, n_students=10,
        n_items=5, mean_score=2.0, mcq_accuracy=0.5, frq_e_rate=0.2,
        frq_p_rate=0.3, frq_i_rate=0.5, unit_scores={1: 2.0},
        holdout_score=2.0,
    )
    candidate = IterationMetrics(
        curriculum_version="b", iteration_id=2, timestamp=1, n_students=10,
        n_items=5, mean_score=2.5, mcq_accuracy=0.6, frq_e_rate=0.3,
        frq_p_rate=0.3, frq_i_rate=0.4, unit_scores={1: 2.5},
        holdout_score=1.8,  # holdout dropped by 0.2
    )
    assert not is_improvement(candidate, best)
