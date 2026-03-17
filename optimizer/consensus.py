"""Multi-model consensus for patch proposals.

Ported from grid-bot-v3's belief engine pattern: Bayesian + recency-weighted
accuracy scoring determines which optimizer's patches are most trustworthy.

Each optimizer source (e.g., claude, gpt4, codex) proposes patches for the
same failing KCs.  ``compute_tuned_weights`` tracks historical outcomes and
adjusts trust accordingly, using exponential recency decay with a configurable
half-life so that recent performance matters more than ancient history.
"""

from __future__ import annotations

import json
import math
import os
import time
from collections import defaultdict


class OptimizerConsensus:
    """Multi-model consensus for patch proposals."""

    DEFAULT_WEIGHTS = {
        "claude": 1.0,
        "gpt4": 0.9,
        "codex": 0.7,
    }

    def __init__(self, base_weights: dict | None = None):
        """
        Args:
            base_weights: prior weights per source, e.g. {"claude": 1.0, ...}.
                Uses DEFAULT_WEIGHTS if not provided.
        """
        self.base_weights: dict[str, float] = dict(base_weights or self.DEFAULT_WEIGHTS)
        self.history: list[dict] = []  # [{source, patch, outcome, iteration, timestamp}]

    # ------------------------------------------------------------------
    # Bayesian + recency-weighted tuning
    # ------------------------------------------------------------------

    def compute_tuned_weights(
        self,
        half_life_iterations: float = 5.0,
        floor: float = 0.05,
    ) -> dict[str, float]:
        """Compute trust weights using Bayesian prior + recency-weighted accuracy.

        Algorithm (ported from grid-bot-v3 ``compute_tuned_weights``):

        1. Start from the prior (``base_weights``).
        2. For each historical outcome, compute a recency weight using
           exponential decay: ``w = 2^(-age / half_life)``, where ``age``
           is measured in iterations from the most recent entry.
        3. Accumulate weighted successes and weighted totals per source.
        4. Posterior weight = prior * (weighted_accuracy + floor).
        5. Normalise so all weights sum to 1.0.

        Args:
            half_life_iterations: number of iterations for the recency weight
                to halve.  Default 5.0 per FOUNDATION_SPEC section 9.2.
            floor: minimum weight to prevent any source from being zeroed out.

        Returns:
            Normalised weight dict summing to 1.0.
        """
        sources = set(self.base_weights.keys())

        # Also include any source that appears in history
        for entry in self.history:
            sources.add(entry.get("source", ""))

        if not sources:
            return {}

        # Find the maximum iteration in history for computing age
        max_iter = 0
        for entry in self.history:
            it = entry.get("iteration", 0)
            if it > max_iter:
                max_iter = it

        # Accumulate recency-weighted success / total per source
        weighted_successes: dict[str, float] = defaultdict(float)
        weighted_totals: dict[str, float] = defaultdict(float)

        decay_constant = math.log(2) / half_life_iterations if half_life_iterations > 0 else 0.0

        for entry in self.history:
            source = entry.get("source", "")
            improved = entry.get("outcome", False)
            iteration = entry.get("iteration", 0)

            age = max_iter - iteration
            recency_weight = math.exp(-decay_constant * age)

            weighted_totals[source] += recency_weight
            if improved:
                weighted_successes[source] += recency_weight

        # Compute posterior weights
        raw_weights: dict[str, float] = {}
        for source in sources:
            prior = self.base_weights.get(source, 0.5)
            total = weighted_totals.get(source, 0.0)

            if total > 0:
                accuracy = weighted_successes.get(source, 0.0) / total
            else:
                # No history: use a neutral accuracy so the prior dominates
                accuracy = 0.5

            raw_weights[source] = prior * (accuracy + floor)

        # Normalise to sum to 1.0
        total_weight = sum(raw_weights.values())
        if total_weight <= 0:
            # Uniform fallback
            n = len(raw_weights)
            return {s: 1.0 / n for s in raw_weights}

        return {s: round(w / total_weight, 6) for s, w in raw_weights.items()}

    # ------------------------------------------------------------------
    # Patch selection
    # ------------------------------------------------------------------

    def select_best_patch(
        self,
        proposals: dict[str, list[dict]],
        weights: dict[str, float] | None = None,
    ) -> list[dict]:
        """Select patches by weighted priority when multiple optimizers propose.

        When several sources propose patches for the same KC, this method
        picks the highest-weighted proposal per KC, then returns all
        selected patches sorted by weighted priority.

        Args:
            proposals: {source: [patch_dict, ...]} where each patch_dict
                includes at least "kc_id" and "priority".
            weights: per-source weights (if None, uses compute_tuned_weights).

        Returns:
            Ordered list of patches to apply (best first), each enriched
            with "_source" and "_weighted_priority" keys.
        """
        if weights is None:
            weights = self.compute_tuned_weights()

        # Collect all proposals, annotated with source and weighted priority
        all_proposals: list[dict] = []
        for source, patches in proposals.items():
            source_weight = weights.get(source, 0.0)
            for patch in patches:
                annotated = dict(patch)
                annotated["_source"] = source
                raw_priority = patch.get("priority", 0.5)
                annotated["_weighted_priority"] = raw_priority * source_weight
                all_proposals.append(annotated)

        # When multiple sources propose for the same KC, keep only the
        # highest-weighted proposal per KC
        best_per_kc: dict[str, dict] = {}
        for prop in all_proposals:
            kc = prop.get("kc_id", "")
            if not kc:
                # No KC key — keep as-is (generic patch)
                kc = f"_no_kc_{id(prop)}"
            existing = best_per_kc.get(kc)
            if existing is None or prop["_weighted_priority"] > existing["_weighted_priority"]:
                best_per_kc[kc] = prop

        # Sort by weighted priority descending
        selected = sorted(
            best_per_kc.values(),
            key=lambda p: -p["_weighted_priority"],
        )
        return selected

    # ------------------------------------------------------------------
    # Outcome tracking
    # ------------------------------------------------------------------

    def record_outcome(
        self,
        source: str,
        patch: dict,
        improved: bool,
        iteration: int,
    ) -> None:
        """Record whether a patch from this source led to improvement.

        Args:
            source: optimizer name (e.g., "claude", "gpt4")
            patch: the patch dict that was applied
            improved: True if the patch improved scores
            iteration: the iteration number
        """
        self.history.append({
            "source": source,
            "patch": patch,
            "outcome": improved,
            "iteration": iteration,
            "timestamp": time.time(),
        })

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_history(self, path: str) -> None:
        """Persist history to a JSON file for cross-session continuity.

        Args:
            path: file path to write (will be created/overwritten).
        """
        dir_name = os.path.dirname(path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)

        data = {
            "base_weights": self.base_weights,
            "history": self._serialisable_history(),
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    @classmethod
    def load_history(cls, path: str) -> "OptimizerConsensus":
        """Restore an OptimizerConsensus from a saved history file.

        Args:
            path: file path to read.

        Returns:
            A new OptimizerConsensus with restored weights and history.

        Raises:
            FileNotFoundError: if the file does not exist.
        """
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        base_weights = data.get("base_weights", cls.DEFAULT_WEIGHTS)
        instance = cls(base_weights=base_weights)
        instance.history = data.get("history", [])
        return instance

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _serialisable_history(self) -> list[dict]:
        """Return history with patch dicts converted for JSON serialisation.

        Large patch content is summarised to keep the file size manageable.
        """
        clean: list[dict] = []
        for entry in self.history:
            h = dict(entry)
            # Summarise patch to key identifiers only
            patch = h.get("patch", {})
            if isinstance(patch, dict):
                h["patch"] = {
                    k: v
                    for k, v in patch.items()
                    if k in ("target", "unit", "lesson", "kc_id", "field", "section")
                }
            clean.append(h)
        return clean
