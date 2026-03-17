# Agent E: Optimizer

Build the failure analysis, curriculum patch generation, quality gates, and multi-model consensus modules.

## Hard Constraints
- Only create/modify files under `optimizer/`
- Pure Python 3.12, stdlib only (urllib for HTTP, json for IO)
- Must be importable as a library
- LLM calls use generic HTTP POST (urllib.request) to support any OpenAI-compatible endpoint
- Do NOT import from other project modules — accept data as dicts

## Interface Contracts

```python
# IterationMetrics fields you'll receive as a dict:
# {
#   "mean_score": float,
#   "mcq_accuracy": float,
#   "frq_e_rate": float, "frq_p_rate": float, "frq_i_rate": float,
#   "unit_scores": {unit_num: score},
#   "kc_mastery": {kc_id: fraction_correct},
#   "top_failure_kcs": [(kc_id, error_rate), ...],
#   "misconception_counts": {misconception_type: count}
# }

# Grade dicts:
# {"student_id": str, "item_id": str, "score": "E"/"P"/"I", "kc_tags": [str], "unit": int}
```

## Deliverables

### 1. `optimizer/analyzer.py` — Failure Pattern Analysis + Source Classification

```python
class FailureAnalyzer:
    """Analyze grading results to identify pedagogical root causes."""

    def __init__(self, provider_config: dict):
        """
        provider_config: from config/provider.json["optimizer"]
        e.g., {"provider": "anthropic", "model": "claude-sonnet-4-6", "api_key_env": "ANTHROPIC_API_KEY"}
        """
        self.config = provider_config

    def cluster_failures(
        self,
        grades: list[dict],
        metrics: dict,
    ) -> list[dict]:
        """
        Group failures by KC, compute error rates, identify top problem areas.
        Returns: [{"kc_id": str, "error_rate": float, "n_errors": int, "common_wrong_answers": list}]
        Pure computation, no LLM call.
        """

    def classify_failure_sources(
        self,
        failure_clusters: list[dict],
        student_memories: list[dict],    # snapshot dicts showing KC states
        current_unit: int,
    ) -> list[dict]:
        """
        For each failure cluster, classify root cause:
        - "new_material": KC belongs to current unit and strength is low
        - "prerequisite_decay": KC belongs to prior unit and strength has decayed
        - "misconception": KC has active error_mode in student memories
        - "question_wording": high error rate even among strong students (tier 4-5)

        Returns: [{"kc_id": str, "source": str, "evidence": str, "priority": float}]
        Pure computation based on memory states + unit mapping.
        """

    async def analyze_with_llm(
        self,
        failure_clusters: list[dict],
        source_classifications: list[dict],
        curriculum_text: dict,     # {kc_id: exposition text}
        framework_context: dict,   # from data/frameworks.json
    ) -> list[dict]:
        """
        Call the optimizer LLM to propose improvements.
        Build the analysis prompt (see below), send to LLM, parse structured response.

        Returns: [{
            "target": "worksheet" | "driller_cartridge" | "blooket",
            "unit": int,
            "lesson": int,
            "kc_id": str,
            "source": str,
            "improvement": str,     # description of what to change
            "patch": dict,          # structured patch data
            "priority": float,
        }]
        """
```

The LLM analysis prompt should include:
- Iteration results (mean_score, top failure KCs)
- Source classifications (new material vs prerequisite vs misconception)
- Current curriculum text for failing KCs
- AP framework requirements
- Instructions to output JSON patches targeting specific artifacts

Implement `_call_llm(self, messages: list[dict]) -> str` as a helper:
- If provider is "anthropic": POST to https://api.anthropic.com/v1/messages
- If provider is "openai" compatible: POST to the endpoint with /v1/chat/completions
- Read API key from environment variable specified in config
- Handle errors gracefully, return error string on failure

### 2. `optimizer/patcher.py` — Patch Generation + Application

```python
class CurriculumPatcher:
    """Apply improvement patches to curriculum artifacts."""

    def apply_patch(
        self,
        patch: dict,
        base_dir: str = "curriculum_patches",
    ) -> str:
        """
        Write a patch to the curriculum_patches directory.
        patch = {"target": "worksheet", "unit": 1, "lesson": 2, "field": "exposition", "content": "..."}
        Returns: path to the written file.
        """

    def generate_improvement_params(
        self,
        improvements: list[dict],
    ) -> dict:
        """
        Convert LLM-proposed improvements into structured parameters
        that can be passed to the Agent pipeline for artifact regeneration.

        Returns: {
            "worksheet_improvements": [{unit, lesson, section, new_text}],
            "driller_improvements": [{cartridge_id, field, new_value}],
            "blooket_improvements": [{unit, lesson, question_changes}],
        }
        """

    def revert_patches(self, commit_hash: str):
        """Revert curriculum_patches/ to state at given commit."""
```

### 3. `optimizer/gates.py` — Patch Quality Gates

```python
class PatchGates:
    """Quality gates that patches must pass before being accepted."""

    def __init__(self, provider_config: dict | None = None):
        self.provider_config = provider_config

    def check_all(self, patch: dict, metrics_before: dict, metrics_after: dict) -> dict:
        """
        Run all gates. Returns: {"passed": bool, "results": {gate_name: {passed, reason}}}
        """

    def correctness_gate(self, patch: dict) -> dict:
        """
        Check if new text contains factual errors.
        For MVP: basic checks (no contradictions with AP framework).
        For later: LLM-based fact checking.
        Returns: {"passed": bool, "reason": str}
        """

    def readability_gate(self, patch: dict) -> dict:
        """
        Check if reading level is appropriate for HS students.
        Use Flesch-Kincaid readability formula (pure Python implementation).
        Target: grade level 10-12.
        Returns: {"passed": bool, "reason": str, "grade_level": float}
        """

    def length_gate(self, patch: dict, max_growth_pct: float = 0.30) -> dict:
        """
        Check if the patch doesn't bloat the content excessively.
        Compare new_text length to old_text length.
        Returns: {"passed": bool, "reason": str, "growth_pct": float}
        """

    def framework_gate(self, patch: dict, framework: dict) -> dict:
        """
        Check if the patch still addresses the AP learning objectives.
        Verify that key terms from the framework's learningObjectives appear in the text.
        Returns: {"passed": bool, "reason": str, "coverage": float}
        """

    def regression_gate(self, metrics_before: dict, metrics_after: dict, guards: dict) -> dict:
        """
        Check if any unit score regressed beyond threshold.
        Returns: {"passed": bool, "reason": str, "regressions": list}
        """
```

Implement Flesch-Kincaid in pure Python:
```python
def flesch_kincaid_grade(text: str) -> float:
    sentences = count_sentences(text)
    words = count_words(text)
    syllables = count_syllables(text)
    if words == 0 or sentences == 0:
        return 0.0
    return 0.39 * (words / sentences) + 11.8 * (syllables / words) - 15.59
```

### 4. `optimizer/consensus.py` — Multi-Model Patch Weighting

```python
class OptimizerConsensus:
    """
    Multi-model consensus for patch proposals.
    Ported from grid-bot-v3's belief engine pattern.
    """

    DEFAULT_WEIGHTS = {
        "claude": 1.0,
        "gpt4": 0.9,
        "codex": 0.7,
    }

    def __init__(self, base_weights: dict | None = None):
        self.base_weights = base_weights or self.DEFAULT_WEIGHTS
        self.history: list[dict] = []  # [{source, patch, outcome, timestamp}]

    def compute_tuned_weights(
        self,
        half_life_iterations: float = 5.0,
        floor: float = 0.05,
    ) -> dict:
        """
        Bayesian + recency-weighted accuracy scoring.
        Tracks which optimizer's patches actually improved scores.
        Returns normalized weights summing to 1.0.
        """

    def select_best_patch(
        self,
        proposals: dict,        # {source: list[patch_dicts]}
        weights: dict | None = None,
    ) -> list[dict]:
        """
        When multiple optimizers propose patches for the same KC,
        select by weighted priority score.
        Returns ordered list of patches to apply.
        """

    def record_outcome(self, source: str, patch: dict, improved: bool, iteration: int):
        """Record whether a patch from this source led to improvement."""

    def save_history(self, path: str):
        """Persist history for cross-session continuity."""

    @classmethod
    def load_history(cls, path: str) -> 'OptimizerConsensus':
        """Restore from saved history."""
```

### 5. `optimizer/__init__.py`
```python
from .analyzer import FailureAnalyzer
from .patcher import CurriculumPatcher
from .gates import PatchGates
from .consensus import OptimizerConsensus
```

## Notes
- analyzer.py is the most critical module — the quality of failure analysis determines the quality of improvements
- For Phase 1 MVP, the LLM call in analyze_with_llm can be stubbed (return empty list) and failures can be analyzed purely from the cluster + source classification data
- The Flesch-Kincaid implementation should handle edge cases (empty text, single word)
- consensus.py is Phase 4 functionality but the skeleton should exist now
