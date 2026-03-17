"""KC State Machine + Forgetting Curves.

Each synthetic student maintains a per-KC memory state that evolves via
Ebbinghaus-inspired exponential decay with spaced-retrieval boosts.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# KC state dataclass
# ---------------------------------------------------------------------------

@dataclass
class KCState:
    """State of a single Knowledge Component in a student's memory."""

    kc_id: str                          # e.g., "VAR-1.A", "UNC-3.B"
    strength: float = 0.0               # 0.0-1.0 (probability of correct recall)
    last_seen_at: float = 0.0           # unix timestamp
    last_recalled_at: float = 0.0       # unix timestamp of last correct retrieval
    error_mode: str = "none"            # "none" | "misconception_A" | ...
    error_strength: float = 0.0         # 0.0-1.0 (how entrenched the misconception)
    exposure_count: int = 0             # times this KC appeared in curriculum
    correct_count: int = 0              # times correctly answered


# ---------------------------------------------------------------------------
# Forgetting curve
# ---------------------------------------------------------------------------

def recall_probability(kc: KCState, now: float) -> float:
    """Ebbinghaus-inspired exponential decay with spacing effect.

    Half-life increases with successful retrievals:
        half_life_hours = 2.0 * (1.5 ** correct_count)
    so 2 h -> 3 h -> 4.5 h -> 6.75 h -> ...

    Returns a value in [0.0, 1.0].
    """
    if kc.strength <= 0.0:
        return 0.0

    age = now - kc.last_recalled_at
    if age <= 0.0:
        # No time has passed (or clock went backwards) -> no decay
        return max(0.0, min(1.0, kc.strength))

    half_life_hours = 2.0 * (1.5 ** kc.correct_count)
    half_life_seconds = half_life_hours * 3600.0
    decay = 0.5 ** (age / half_life_seconds)
    prob = kc.strength * decay
    return max(0.0, min(1.0, prob))


# ---------------------------------------------------------------------------
# KC update helpers
# ---------------------------------------------------------------------------

def update_on_correct(
    kc: KCState,
    now: float,
    acquisition_rate: float = 0.15,
) -> KCState:
    """Update KC state after a correct response.

    - Boosts strength by acquisition_rate (capped at 1.0)
    - Increments correct_count and exposure_count
    - Updates timestamps
    - Reduces error_strength by 30 %
    """
    new_strength = min(1.0, kc.strength + acquisition_rate)
    new_error_strength = max(0.0, kc.error_strength * 0.70)
    # If the misconception is negligible, clear it
    new_error_mode = kc.error_mode if new_error_strength > 0.01 else "none"
    if new_error_mode == "none":
        new_error_strength = 0.0

    return KCState(
        kc_id=kc.kc_id,
        strength=new_strength,
        last_seen_at=now,
        last_recalled_at=now,
        error_mode=new_error_mode,
        error_strength=new_error_strength,
        exposure_count=kc.exposure_count + 1,
        correct_count=kc.correct_count + 1,
    )


def update_on_incorrect(
    kc: KCState,
    now: float,
    error_mode: str = "none",
    misconception_persistence: float = 0.8,
) -> KCState:
    """Update KC state after an incorrect response.

    - Reduces strength slightly (multiplicative decay of 0.9)
    - If *error_mode* is provided (not "none"), sets or reinforces the
      misconception using *misconception_persistence* as the persistence factor.
    - Increments exposure_count (but NOT correct_count)
    """
    new_strength = max(0.0, kc.strength * 0.9)

    new_error_mode = kc.error_mode
    new_error_strength = kc.error_strength

    if error_mode != "none":
        if kc.error_mode == error_mode:
            # Same misconception -- reinforce it
            new_error_strength = min(
                1.0,
                kc.error_strength + (1.0 - kc.error_strength) * misconception_persistence * 0.3,
            )
        else:
            # New misconception replaces old one
            new_error_mode = error_mode
            new_error_strength = misconception_persistence * 0.4

    return KCState(
        kc_id=kc.kc_id,
        strength=new_strength,
        last_seen_at=now,
        last_recalled_at=kc.last_recalled_at,  # NOT updated on incorrect
        error_mode=new_error_mode,
        error_strength=new_error_strength,
        exposure_count=kc.exposure_count + 1,
        correct_count=kc.correct_count,
    )


def apply_forgetting(kc: KCState, elapsed_seconds: float) -> KCState:
    """Apply decay to a KC without an interaction event.

    Used to simulate inter-unit time gaps.  The new strength is the recall
    probability at the end of the elapsed interval, so the student's memory
    *starts* the next unit at the decayed level.
    """
    if kc.strength <= 0.0 or elapsed_seconds <= 0.0:
        return kc

    half_life_hours = 2.0 * (1.5 ** kc.correct_count)
    half_life_seconds = half_life_hours * 3600.0
    decay = 0.5 ** (elapsed_seconds / half_life_seconds)
    new_strength = max(0.0, kc.strength * decay)

    # Also decay error_strength (misconceptions fade too, but slower)
    error_decay = 0.5 ** (elapsed_seconds / (half_life_seconds * 2.0))
    new_error_strength = max(0.0, kc.error_strength * error_decay)
    new_error_mode = kc.error_mode if new_error_strength > 0.01 else "none"
    if new_error_mode == "none":
        new_error_strength = 0.0

    return KCState(
        kc_id=kc.kc_id,
        strength=new_strength,
        last_seen_at=kc.last_seen_at,
        last_recalled_at=kc.last_recalled_at,
        error_mode=new_error_mode,
        error_strength=new_error_strength,
        exposure_count=kc.exposure_count,
        correct_count=kc.correct_count,
    )


# ---------------------------------------------------------------------------
# Student memory manager
# ---------------------------------------------------------------------------

class StudentMemory:
    """Manages all KC states for one student."""

    def __init__(self) -> None:
        self.kc_states: dict[str, KCState] = {}

    # -- queries --

    def get_known_kcs(self, now: float, threshold: float = 0.3) -> list[KCState]:
        """Return KCs whose recall_probability exceeds *threshold*."""
        results: list[KCState] = []
        for kc in self.kc_states.values():
            if recall_probability(kc, now) > threshold:
                results.append(kc)
        # Sort by recall probability descending for deterministic rendering
        results.sort(key=lambda k: recall_probability(k, now), reverse=True)
        return results

    # -- mutations --

    def update(
        self,
        kc_id: str,
        correct: bool,
        now: float,
        error_mode: str = "none",
        acquisition_rate: float = 0.15,
        misconception_persistence: float = 0.8,
    ) -> None:
        """Update a KC after an assessment.  Creates KC if not seen before."""
        if kc_id not in self.kc_states:
            self.kc_states[kc_id] = KCState(
                kc_id=kc_id,
                strength=0.0,
                last_seen_at=now,
                last_recalled_at=now,
            )

        kc = self.kc_states[kc_id]
        if correct:
            self.kc_states[kc_id] = update_on_correct(kc, now, acquisition_rate)
        else:
            self.kc_states[kc_id] = update_on_incorrect(
                kc, now, error_mode, misconception_persistence,
            )

    def apply_inter_unit_gap(self, gap_seconds: float) -> None:
        """Apply forgetting to all KCs (called between units)."""
        for kc_id in list(self.kc_states):
            self.kc_states[kc_id] = apply_forgetting(
                self.kc_states[kc_id], gap_seconds,
            )

    # -- serialization --

    def snapshot(self) -> dict:
        """Serialize all KC states to a JSON-compatible dict."""
        return {
            "kc_states": {
                kc_id: {
                    "kc_id": kc.kc_id,
                    "strength": kc.strength,
                    "last_seen_at": kc.last_seen_at,
                    "last_recalled_at": kc.last_recalled_at,
                    "error_mode": kc.error_mode,
                    "error_strength": kc.error_strength,
                    "exposure_count": kc.exposure_count,
                    "correct_count": kc.correct_count,
                }
                for kc_id, kc in self.kc_states.items()
            },
        }

    @classmethod
    def from_snapshot(cls, data: dict) -> StudentMemory:
        """Restore from a snapshot dict."""
        mem = cls()
        for kc_id, kc_data in data.get("kc_states", {}).items():
            mem.kc_states[kc_id] = KCState(
                kc_id=kc_data["kc_id"],
                strength=kc_data["strength"],
                last_seen_at=kc_data["last_seen_at"],
                last_recalled_at=kc_data["last_recalled_at"],
                error_mode=kc_data.get("error_mode", "none"),
                error_strength=kc_data.get("error_strength", 0.0),
                exposure_count=kc_data.get("exposure_count", 0),
                correct_count=kc_data.get("correct_count", 0),
            )
        return mem
