"""Test the KC state machine and forgetting curves."""

import pytest
import sys
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from simulator.memory import (
    KCState,
    StudentMemory,
    recall_probability,
    update_on_correct,
    update_on_incorrect,
    apply_forgetting,
)


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


def test_recall_probability_zero_strength():
    kc = KCState(kc_id="VAR-1.A", strength=0.0, last_recalled_at=0.0)
    assert recall_probability(kc, 3600) == 0.0


def test_recall_probability_no_time_elapsed():
    kc = KCState(kc_id="VAR-1.A", strength=0.8, last_recalled_at=100.0)
    p = recall_probability(kc, 100.0)
    assert p == pytest.approx(0.8)


def test_spacing_effect():
    """More correct retrievals = slower forgetting."""
    kc_low = KCState(kc_id="VAR-1.A", strength=0.8, last_recalled_at=0.0, correct_count=1)
    kc_high = KCState(kc_id="VAR-1.A", strength=0.8, last_recalled_at=0.0, correct_count=5)
    t = 86400  # 24 hours
    assert recall_probability(kc_high, t) > recall_probability(kc_low, t)


def test_update_on_correct_boosts_strength():
    kc = KCState(kc_id="VAR-1.A", strength=0.5, last_recalled_at=0.0)
    updated = update_on_correct(kc, now=1000.0, acquisition_rate=0.15)
    assert updated.strength == pytest.approx(0.65)
    assert updated.correct_count == 1
    assert updated.exposure_count == 1
    assert updated.last_recalled_at == 1000.0


def test_update_on_correct_caps_at_one():
    kc = KCState(kc_id="VAR-1.A", strength=0.95)
    updated = update_on_correct(kc, now=1000.0, acquisition_rate=0.15)
    assert updated.strength == 1.0


def test_update_on_incorrect_reduces_strength():
    kc = KCState(kc_id="VAR-1.A", strength=0.5, last_recalled_at=0.0)
    updated = update_on_incorrect(kc, now=1000.0)
    assert updated.strength == pytest.approx(0.45)
    assert updated.correct_count == 0
    assert updated.exposure_count == 1
    assert updated.last_recalled_at == 0.0  # NOT updated on incorrect


def test_update_on_incorrect_sets_error_mode():
    kc = KCState(kc_id="VAR-1.A", strength=0.5)
    updated = update_on_incorrect(kc, now=1000.0, error_mode="misconception_A")
    assert updated.error_mode == "misconception_A"
    assert updated.error_strength > 0.0


def test_update_on_incorrect_reinforces_same_misconception():
    kc = KCState(kc_id="VAR-1.A", strength=0.5,
                 error_mode="misconception_A", error_strength=0.3)
    updated = update_on_incorrect(kc, now=1000.0,
                                   error_mode="misconception_A",
                                   misconception_persistence=0.8)
    assert updated.error_strength > 0.3
    assert updated.error_mode == "misconception_A"


def test_apply_forgetting_reduces_strength():
    kc = KCState(kc_id="VAR-1.A", strength=0.8, last_recalled_at=0.0)
    decayed = apply_forgetting(kc, 86400)  # 24 hours
    assert decayed.strength < 0.8
    assert decayed.strength > 0.0


def test_apply_forgetting_no_change_on_zero_elapsed():
    kc = KCState(kc_id="VAR-1.A", strength=0.8)
    decayed = apply_forgetting(kc, 0.0)
    assert decayed.strength == 0.8


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


def test_get_known_kcs():
    mem = StudentMemory()
    mem.update("VAR-1.A", True, 0.0, acquisition_rate=0.5)
    mem.update("UNC-1.A", True, 0.0, acquisition_rate=0.5)
    known = mem.get_known_kcs(0.0, threshold=0.3)
    assert len(known) == 2


def test_memory_creates_new_kc_on_first_update():
    mem = StudentMemory()
    assert "VAR-1.A" not in mem.kc_states
    mem.update("VAR-1.A", True, 1000.0)
    assert "VAR-1.A" in mem.kc_states
