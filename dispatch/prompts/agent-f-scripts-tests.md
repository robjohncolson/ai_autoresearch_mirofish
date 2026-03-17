# Agent F: Scripts & Tests

Build the entry-point CLI scripts and test suite that integrate all modules from Agents A–E.

## Hard Constraints
- Only create/modify files under `scripts/` (except `scripts/extract_items.py` which already exists) and `tests/`
- Python 3.12, stdlib + project imports only
- Scripts must be runnable from the repo root: `python scripts/run_experiment.py`
- Tests must be runnable with: `python -m pytest tests/`
- All scripts should accept `--help` via argparse
- Do NOT modify any files outside scripts/ and tests/

## Available Modules (already implemented)

```python
# simulator/ (Agent B)
from simulator import KCState, StudentMemory, recall_probability
from simulator import StudentPersona, SyntheticStudent
from simulator import StudentCohort
from simulator import build_student_system_prompt, build_item_prompt

# loop/ (Agent D)
from loop import IterationMetrics, compute_metrics, is_improvement
from loop import create_branch, get_current_commit, commit_changes, revert_to_commit
from loop import AutoresearchRunner
from loop import CourseProgression

# optimizer/ (Agent E)
from optimizer import FailureAnalyzer, CurriculumPatcher, PatchGates, OptimizerConsensus

# config files (Agent C)
# config/personas.json — 100 student personas
# config/provider.json — Ollama + optimizer endpoint config
# config/experiment.json — experiment parameters
# data/frameworks.json — AP framework data
# data/kc_tags.json — KC vocabulary

# adapters (Agent A) — called via subprocess
# node adapters/curriculum_render/extract_items.mjs
# echo '{"answer":"B","expected":{"answer_key":"C"}}' | node adapters/curriculum_render/grade_mcq.mjs
# echo '{"answer":"...","ruleId":"...","context":{}}' | node adapters/curriculum_render/grade_frq.mjs
```

## Deliverables

### 1. `scripts/run_experiment.py` — Single Iteration Runner

The main Phase 1 entry point. Runs one evaluation pass:

```python
"""
Usage: python scripts/run_experiment.py [--unit 1] [--n-students 10] [--config config/experiment.json]

Steps:
1. Load config, personas, items for the specified unit
2. Create a StudentCohort from personas (or from snapshots if resuming)
3. Run cohort.run_evaluation() against the items
4. Grade all responses (call Node adapters via subprocess for MCQ/FRQ)
5. Update student memories based on grades
6. Compute and display IterationMetrics
7. Save results to logs/runs/{run_id}/
"""
```

Key implementation details:
- Load items from `data/items/curriculum_render.json`, filter by unit
- For grading, implement a `grade_response(item, response)` function that:
  - MCQ: pipes to `node adapters/curriculum_render/grade_mcq.mjs` via subprocess
  - FRQ: pipes to `node adapters/curriculum_render/grade_frq.mjs` via subprocess
  - Falls back to simple pattern matching if node isn't available
- Use `asyncio.run()` to drive the async cohort evaluation
- Print a formatted summary table at the end

### 2. `scripts/run_loop.py` — Full Autoresearch Loop (one unit)

```python
"""
Usage: python scripts/run_loop.py [--unit 1] [--max-iterations 50] [--config config/experiment.json]

Runs the inner autoresearch loop on a single unit until convergence.
Wraps AutoresearchRunner with concrete implementations of grade_fn, analyze_fn, apply_fn.
"""
```

Wire up:
- `grade_fn`: calls Node adapters
- `analyze_fn`: instantiates FailureAnalyzer, calls cluster_failures + classify_failure_sources (skip LLM for MVP)
- `apply_fn`: instantiates CurriculumPatcher, applies patches
- Handle KeyboardInterrupt (runner already does, but wrap the outer call too)

### 3. `scripts/run_course.py` — Full Course Progression

```python
"""
Usage: python scripts/run_course.py [--start-unit 1] [--end-unit 9] [--config config/experiment.json]

Runs the outer loop: sequential unit-by-unit progression with cumulative memory.
"""
```

Wire up CourseProgression with the same grade_fn, analyze_fn, apply_fn.

### 4. `scripts/tag_kcs.py` — KC Tagging Script

```python
"""
Usage: python scripts/tag_kcs.py [--items data/items/curriculum_render.json] [--frameworks data/frameworks.json]

Assigns kc_tags to items that don't have them yet.
Strategy:
1. Load items and frameworks
2. For each item without kc_tags:
   a. Match unit/lesson to framework learning objectives
   b. Use keyword matching to find the best KC tags
   c. Optionally call LLM for ambiguous items
3. Write updated items back
"""
```

For MVP: use simple keyword matching (check if the question prompt contains terms from the KC's essential knowledge). LLM tagging is Phase 3.

### 5. `scripts/promote.py` — Promote Converged Improvements

```python
"""
Usage: python scripts/promote.py [--unit 1] [--target-repo ../curriculum_render] [--dry-run]

Copies converged curriculum patches from curriculum_patches/{unit}/ to the target production repo.
Dry-run mode by default — shows what would change without writing.
"""
```

### 6. `scripts/calibrate.py` — Calibration Comparison

```python
"""
Usage: python scripts/calibrate.py [--synthetic logs/runs/latest/grades.jsonl] [--real data/real_student_export.json]

Compares synthetic student error patterns to real student data.
Computes:
- Per-item difficulty correlation (Spearman)
- Per-KC mastery correlation
- Misconception distribution overlap
"""
```

For MVP: stub that loads data and prints "calibration not yet implemented — need real student export". The structure should be ready for Phase 3.

### 7. `tests/test_memory.py`

```python
"""Test the KC state machine and forgetting curves."""
import pytest
from simulator.memory import KCState, StudentMemory, recall_probability, update_on_correct, update_on_incorrect, apply_forgetting

def test_recall_probability_decreases_over_time():
    kc = KCState(kc_id="VAR-1.A", strength=1.0, last_recalled_at=0.0)
    p1 = recall_probability(kc, 3600)    # 1 hour
    p2 = recall_probability(kc, 7200)    # 2 hours
    assert p1 > p2 > 0

def test_recall_probability_in_bounds():
    kc = KCState(kc_id="VAR-1.A", strength=0.8, last_recalled_at=0.0, correct_count=3)
    for t in [0, 100, 3600, 86400, 604800]:
        p = recall_probability(kc, t)
        assert 0 <= p <= 1

def test_spacing_effect():
    """More correct retrievals = slower forgetting."""
    kc_low = KCState(kc_id="VAR-1.A", strength=0.8, last_recalled_at=0.0, correct_count=1)
    kc_high = KCState(kc_id="VAR-1.A", strength=0.8, last_recalled_at=0.0, correct_count=5)
    t = 86400  # 24 hours
    assert recall_probability(kc_high, t) > recall_probability(kc_low, t)

def test_snapshot_roundtrip():
    mem = StudentMemory()
    mem.update("VAR-1.A", True, 1000.0)
    mem.update("UNC-2.B", False, 1000.0, error_mode="misconception_A")
    snap = mem.snapshot()
    restored = StudentMemory.from_snapshot(snap)
    assert restored.snapshot() == snap

def test_inter_unit_gap_reduces_strength():
    mem = StudentMemory()
    mem.update("VAR-1.A", True, 0.0)
    before = mem.kc_states["VAR-1.A"].strength
    mem.apply_inter_unit_gap(336 * 3600)  # 2 weeks
    after = mem.kc_states["VAR-1.A"].strength
    assert after < before
```

### 8. `tests/test_student.py`

```python
"""Test the SyntheticStudent class."""
import pytest
from simulator.student import StudentPersona, SyntheticStudent
from simulator.memory import StudentMemory

def test_persona_creation():
    p = StudentPersona(persona_id="test_001", ability_tier=3, kc_acquisition_rate=0.15,
                       carelessness=0.06, guess_strategy="random",
                       misconception_persistence=0.80, reading_comprehension=0.80,
                       working_memory_slots=5)
    assert p.ability_tier == 3

def test_student_snapshot_roundtrip():
    p = StudentPersona(persona_id="test_001", ability_tier=3, kc_acquisition_rate=0.15,
                       carelessness=0.06, guess_strategy="random",
                       misconception_persistence=0.80, reading_comprehension=0.80,
                       working_memory_slots=5)
    student = SyntheticStudent(p)
    student.memory.update("VAR-1.A", True, 1000.0)
    snap = student.snapshot()
    restored = SyntheticStudent.from_snapshot(snap)
    assert restored.persona.persona_id == "test_001"
    assert "VAR-1.A" in restored.memory.kc_states

def test_update_memory_from_grade_e():
    p = StudentPersona(persona_id="test_001", ability_tier=3, kc_acquisition_rate=0.15,
                       carelessness=0.06, guess_strategy="random",
                       misconception_persistence=0.80, reading_comprehension=0.80,
                       working_memory_slots=5)
    student = SyntheticStudent(p)
    item = {"item_id": "CR:U1-L1-Q01", "kc_tags": ["VAR-1.A"]}
    grade = {"score": "E", "matched": ["VAR-1.A"], "missing": []}
    student.update_memory_from_grade(item, grade, 1000.0)
    assert student.memory.kc_states["VAR-1.A"].correct_count == 1
```

### 9. `tests/test_metrics.py`

```python
"""Test metrics computation and improvement check."""
import pytest
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

def test_is_improvement_basic():
    best = IterationMetrics(curriculum_version="a", iteration_id=1, timestamp=0, n_students=10,
                            n_items=5, mean_score=2.0, mcq_accuracy=0.5, frq_e_rate=0.2,
                            frq_p_rate=0.3, frq_i_rate=0.5, unit_scores={1: 2.0})
    better = IterationMetrics(curriculum_version="b", iteration_id=2, timestamp=1, n_students=10,
                              n_items=5, mean_score=2.3, mcq_accuracy=0.6, frq_e_rate=0.3,
                              frq_p_rate=0.3, frq_i_rate=0.4, unit_scores={1: 2.3})
    assert is_improvement(better, best)

def test_is_improvement_rejects_regression():
    best = IterationMetrics(curriculum_version="a", iteration_id=1, timestamp=0, n_students=10,
                            n_items=5, mean_score=2.5, mcq_accuracy=0.5, frq_e_rate=0.2,
                            frq_p_rate=0.3, frq_i_rate=0.5, unit_scores={1: 2.5})
    worse = IterationMetrics(curriculum_version="b", iteration_id=2, timestamp=1, n_students=10,
                             n_items=5, mean_score=2.3, mcq_accuracy=0.4, frq_e_rate=0.1,
                             frq_p_rate=0.3, frq_i_rate=0.6, unit_scores={1: 2.3})
    assert not is_improvement(worse, best)
```

### 10. `tests/test_adapters.py`

```python
"""Test the Node.js adapter subprocess calls."""
import pytest
import subprocess
import json
import shutil

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="Node.js not available"
)

def test_grade_mcq_correct():
    input_data = json.dumps({"answer": "B", "expected": {"answer_key": "B"}})
    result = subprocess.run(
        ["node", "adapters/curriculum_render/grade_mcq.mjs"],
        input=input_data, capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert output["score"] == "E"

def test_grade_mcq_incorrect():
    input_data = json.dumps({"answer": "A", "expected": {"answer_key": "C"}})
    result = subprocess.run(
        ["node", "adapters/curriculum_render/grade_mcq.mjs"],
        input=input_data, capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert output["score"] == "I"
```

### 11. `tests/test_loop.py`

```python
"""Test the autoresearch loop components."""
import pytest
import json
import tempfile
import os
from loop.metrics import compute_metrics, is_improvement, metrics_to_dict, IterationMetrics
from loop.runner import AutoresearchRunner

def test_metrics_serialization_roundtrip():
    grades = [
        {"student_id": "s1", "item_id": "i1", "item_type": "mcq", "unit": 1, "kc_tags": ["VAR-1.A"], "score": "E"},
    ]
    m = compute_metrics(grades, "test", 1)
    d = metrics_to_dict(m)
    assert isinstance(d, dict)
    assert d["mean_score"] == m.mean_score

def test_runner_state_save_load():
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = os.path.join(tmpdir, "experiment.json")
        with open(config_path, "w") as f:
            json.dump({
                "experiment_id": "test-run",
                "max_iterations": 10,
                "convergence": {"no_improvement_streak": 3, "min_iterations": 2, "min_mean_score": None},
                "scoring_weights": {"E": 3, "P": 2, "I": 1},
                "improvement_guards": {"max_unit_regression": 0.1, "max_holdout_divergence": 0.05},
                "holdout_interval": 5
            }, f)
        runner = AutoresearchRunner(config_path=config_path)
        state_path = os.path.join(tmpdir, "state.json")
        runner.save_state(state_path)
        loaded = AutoresearchRunner.load_state(state_path)
        assert loaded.config["experiment_id"] == "test-run"
```

### 12. `tests/test_snapshots.py`

```python
"""Test student memory snapshots across units."""
import pytest
import tempfile
import os
from simulator.memory import StudentMemory
from simulator.student import StudentPersona, SyntheticStudent
from simulator.cohort import StudentCohort

def test_cohort_snapshot_and_restore():
    personas = [
        StudentPersona(persona_id=f"test_{i:03d}", ability_tier=3, kc_acquisition_rate=0.15,
                       carelessness=0.06, guess_strategy="random",
                       misconception_persistence=0.80, reading_comprehension=0.80,
                       working_memory_slots=5)
        for i in range(3)
    ]
    cohort = StudentCohort.from_personas(personas)
    # Simulate some learning
    for student in cohort.students:
        student.memory.update("VAR-1.A", True, 1000.0)
        student.memory.update("UNC-1.A", False, 1000.0, error_mode="misconception_A")

    with tempfile.TemporaryDirectory() as tmpdir:
        cohort.save_snapshots(tmpdir)
        assert len(os.listdir(tmpdir)) == 3  # one file per student

        restored = StudentCohort.from_snapshots(tmpdir)
        assert len(restored.students) == 3
        for student in restored.students:
            assert "VAR-1.A" in student.memory.kc_states
            assert student.memory.kc_states["UNC-1.A"].error_mode == "misconception_A"

def test_inter_unit_gap_applies_to_cohort():
    personas = [
        StudentPersona(persona_id="test_001", ability_tier=3, kc_acquisition_rate=0.15,
                       carelessness=0.06, guess_strategy="random",
                       misconception_persistence=0.80, reading_comprehension=0.80,
                       working_memory_slots=5)
    ]
    cohort = StudentCohort.from_personas(personas)
    cohort.students[0].memory.update("VAR-1.A", True, 0.0)
    before = cohort.students[0].memory.kc_states["VAR-1.A"].strength
    cohort.apply_inter_unit_gap(336 * 3600)  # 2 weeks
    after = cohort.students[0].memory.kc_states["VAR-1.A"].strength
    assert after < before
```

## Notes
- All tests should pass without Ollama running (mock HTTP calls or skip integration tests)
- Tests that need Node.js should be skipped if node isn't available
- Use `pytest.mark.skipif` for conditional skipping
- Keep tests focused and fast — no LLM calls in unit tests
