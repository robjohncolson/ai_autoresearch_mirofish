"""Test the autoresearch loop components."""

import pytest
import json
import tempfile
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loop.metrics import (
    compute_metrics,
    is_improvement,
    metrics_to_dict,
    dict_to_metrics,
    IterationMetrics,
)
from loop.runner import AutoresearchRunner


def test_metrics_serialization_roundtrip():
    grades = [
        {"student_id": "s1", "item_id": "i1", "item_type": "mcq",
         "unit": 1, "kc_tags": ["VAR-1.A"], "score": "E"},
    ]
    m = compute_metrics(grades, "test", 1)
    d = metrics_to_dict(m)
    assert isinstance(d, dict)
    assert d["mean_score"] == m.mean_score


def test_metrics_dict_roundtrip():
    grades = [
        {"student_id": "s1", "item_id": "i1", "item_type": "mcq",
         "unit": 1, "kc_tags": ["VAR-1.A"], "score": "E"},
        {"student_id": "s2", "item_id": "i2", "item_type": "frq",
         "unit": 1, "kc_tags": ["UNC-1.A"], "score": "P"},
    ]
    m = compute_metrics(grades, "test", 1)
    d = metrics_to_dict(m)
    restored = dict_to_metrics(d)
    assert restored.mean_score == m.mean_score
    assert restored.n_students == m.n_students
    assert restored.mcq_accuracy == m.mcq_accuracy


def test_metrics_json_serializable():
    grades = [
        {"student_id": "s1", "item_id": "i1", "item_type": "mcq",
         "unit": 1, "kc_tags": ["VAR-1.A"], "score": "E"},
    ]
    m = compute_metrics(grades, "test", 1)
    d = metrics_to_dict(m)
    # Should not raise
    serialized = json.dumps(d)
    parsed = json.loads(serialized)
    assert parsed["mean_score"] == m.mean_score


def test_runner_state_save_load():
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = os.path.join(tmpdir, "experiment.json")
        with open(config_path, "w") as f:
            json.dump({
                "experiment_id": "test-run",
                "loop": {
                    "max_iterations": 10,
                    "no_improvement_streak": 3,
                    "scoring_weights": {"E": 3, "P": 2, "I": 1},
                    "guards": {
                        "max_unit_regression": 0.1,
                        "max_holdout_divergence": 0.05,
                    },
                },
            }, f)
        runner = AutoresearchRunner(config_path=config_path)
        assert runner.max_iterations == 10

        state_path = os.path.join(tmpdir, "state.json")
        runner.save_state(state_path)

        loaded = AutoresearchRunner.load_state(state_path)
        assert loaded.max_iterations == 10
        assert loaded.no_improvement_limit == 3


def test_runner_default_config():
    """Runner should work with a missing config file."""
    runner = AutoresearchRunner(config_path="nonexistent.json")
    assert runner.max_iterations == 50  # default
    assert runner.iteration == 0
    assert runner.best_metrics is None


def test_runner_decide_accepts_first_iteration():
    runner = AutoresearchRunner(config_path="nonexistent.json")
    metrics = IterationMetrics(
        curriculum_version="abc", iteration_id=1, timestamp=0,
        n_students=10, n_items=5, mean_score=2.0, mcq_accuracy=0.5,
        frq_e_rate=0.2, frq_p_rate=0.3, frq_i_rate=0.5,
        unit_scores={1: 2.0},
    )
    kept = runner.decide(metrics)
    assert kept is True
    assert runner.best_metrics is not None
    assert runner.best_metrics.mean_score == 2.0


def test_runner_decide_keeps_improvement():
    runner = AutoresearchRunner(config_path="nonexistent.json")

    first = IterationMetrics(
        curriculum_version="a", iteration_id=1, timestamp=0,
        n_students=10, n_items=5, mean_score=2.0, mcq_accuracy=0.5,
        frq_e_rate=0.2, frq_p_rate=0.3, frq_i_rate=0.5,
        unit_scores={1: 2.0},
    )
    runner.decide(first)

    better = IterationMetrics(
        curriculum_version="b", iteration_id=2, timestamp=1,
        n_students=10, n_items=5, mean_score=2.5, mcq_accuracy=0.6,
        frq_e_rate=0.3, frq_p_rate=0.3, frq_i_rate=0.4,
        unit_scores={1: 2.5},
    )
    # Note: decide() calls revert_to_commit on regression which runs git.
    # For this test we only test the keep path.
    kept = runner.decide(better)
    assert kept is True
    assert runner.best_metrics.mean_score == 2.5


def test_runner_convergence():
    runner = AutoresearchRunner(config_path="nonexistent.json")
    runner.no_improvement_limit = 2
    runner._no_improvement_streak = 0
    assert not runner.is_converged()

    runner._no_improvement_streak = 2
    assert runner.is_converged()
    assert runner._converged is True
