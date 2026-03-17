# Agent B: Simulator Core

Build the synthetic student simulation engine — the KC memory system, prompt templates, student class, and cohort manager.

## Hard Constraints
- Only create/modify files under `simulator/`
- Pure Python 3.12, no external dependencies beyond stdlib
- All classes use `@dataclass` from dataclasses module
- Must be importable as a library (no script-level side effects)
- Use `asyncio` for cohort-level parallelism (async HTTP calls to Ollama)

## Deliverables

### 1. `simulator/memory.py` — KC State Machine + Forgetting Curves

```python
from dataclasses import dataclass, field
import math, time

@dataclass
class KCState:
    kc_id: str                    # e.g., "VAR-1.A", "UNC-3.B"
    strength: float = 0.0         # 0.0–1.0 (probability of correct recall)
    last_seen_at: float = 0.0     # unix timestamp
    last_recalled_at: float = 0.0 # unix timestamp of last correct retrieval
    error_mode: str = "none"      # "none" | "misconception_A" | "misconception_B" | ...
    error_strength: float = 0.0   # 0.0–1.0 (how entrenched the misconception is)
    exposure_count: int = 0       # times this KC appeared in curriculum
    correct_count: int = 0        # times correctly answered
```

Implement these functions:
- `recall_probability(kc: KCState, now: float) -> float` — Ebbinghaus-inspired exponential decay. Half-life increases with successful retrievals: `half_life_hours = 2.0 * (1.5 ** kc.correct_count)`. Return `kc.strength * 0.5 ** (age / (half_life_hours * 3600))`.
- `update_on_correct(kc: KCState, now: float) -> KCState` — Boost strength by acquisition rate, increment correct_count, update timestamps, reduce error_strength by 30%.
- `update_on_incorrect(kc: KCState, now: float, error_mode: str = "none") -> KCState` — Reduce strength slightly, if error_mode given: set/reinforce misconception with persistence factor.
- `apply_forgetting(kc: KCState, elapsed_seconds: float) -> KCState` — Apply decay without an interaction event (for inter-unit gaps).

Also implement:
```python
class StudentMemory:
    """Manages all KC states for one student."""
    def __init__(self):
        self.kc_states: dict[str, KCState] = {}  # kc_id -> KCState

    def get_known_kcs(self, now: float, threshold: float = 0.3) -> list[KCState]:
        """Return KCs with recall_probability > threshold."""

    def update(self, kc_id: str, correct: bool, now: float, error_mode: str = "none"):
        """Update a KC after an assessment. Creates KC if not seen before."""

    def apply_inter_unit_gap(self, gap_seconds: float):
        """Apply forgetting to all KCs (called between units)."""

    def snapshot(self) -> dict:
        """Serialize all KC states to a JSON-compatible dict."""

    @classmethod
    def from_snapshot(cls, data: dict) -> 'StudentMemory':
        """Restore from a snapshot dict."""
```

### 2. `simulator/prompts.py` — System Prompt Templates

```python
def build_student_system_prompt(
    persona: 'StudentPersona',  # from student.py
    memory: 'StudentMemory',    # from memory.py
    now: float,                 # current simulated timestamp
) -> str:
    """Build the system prompt for a synthetic student."""
```

The system prompt template (return as a formatted string):
```
You are a high school student in AP Statistics. Your performance level is {ability_tier}/5.
You may ONLY use knowledge from your MEMORY below. Do NOT use any facts, formulas,
or concepts not present in your memory.

## YOUR MEMORY (what you currently know)
{for each KC with recall_probability > 0.3, render: "- {kc_id}: {description} (confidence: {recall_prob:.0%})"}
{if no KCs above threshold: "You have not learned any statistics concepts yet."}

## INSTRUCTIONS
- For multiple choice: respond with ONLY a single letter (A/B/C/D/E). Nothing else.
- For free response: write a short answer. Use this format:
  Answer: [your answer]
  Work: [show your reasoning]
  Conclusion: [state your conclusion in context]
- If you don't know something, guess. Students often confuse:
  - correlation with causation
  - population parameters with sample statistics
  - conditional probability with joint probability
  - one-sided vs two-sided tests
- You sometimes make arithmetic mistakes (about {carelessness*100:.0f}% of the time)
- You can only hold {working_memory_slots} ideas in your head at once
```

Also implement:
```python
def build_item_prompt(item: dict, lesson_text: str | None = None) -> str:
    """Build the user message for a specific question.
    item is a canonical item dict with keys: prompt, choices, item_type
    lesson_text is optional exposition the student just read.
    """
```
- For MCQ: show the prompt + lettered choices, end with "Your answer (single letter):"
- For FRQ: show the prompt, end with "Your response:"
- If lesson_text provided, prepend it as "## TODAY'S LESSON\n{lesson_text}"

### 3. `simulator/student.py` — Student Class

```python
from dataclasses import dataclass

@dataclass
class StudentPersona:
    persona_id: str
    ability_tier: int             # 1–5
    kc_acquisition_rate: float    # 0.05–0.30
    carelessness: float           # 0.0–0.15
    guess_strategy: str           # "random" | "misconception_driven" | "partial_knowledge"
    misconception_persistence: float  # 0.5–0.95
    reading_comprehension: float  # 0.6–1.0
    working_memory_slots: int     # 3–7

class SyntheticStudent:
    def __init__(self, persona: StudentPersona, memory: StudentMemory | None = None):
        self.persona = persona
        self.memory = memory or StudentMemory()
        self.response_log: list[dict] = []  # log of all responses

    async def answer_item(
        self,
        item: dict,              # canonical item
        endpoint: str,           # Ollama API URL
        model: str = "qwen3:8b",
        lesson_text: str | None = None,
        now: float | None = None,
    ) -> dict:
        """
        Send the item to the LLM and return the response.
        Returns: {"item_id": str, "response": str, "raw_output": str, "timestamp": float}

        Implementation:
        1. Build system prompt via build_student_system_prompt()
        2. Build user prompt via build_item_prompt()
        3. POST to endpoint/api/chat with:
           - model: model
           - messages: [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]
           - options: {"temperature": 0.8, "num_predict": 5 if MCQ else 200}
           - think: false  (non-thinking mode for Ollama)
           - stream: false
        4. Parse response, log it, return result dict
        """

    def update_memory_from_grade(
        self,
        item: dict,        # canonical item with kc_tags
        grade: dict,        # {"score": "E"/"P"/"I", ...}
        now: float,
    ):
        """Update KC states based on grading result.
        E = correct (update_on_correct for all kc_tags)
        P = partial (update_on_correct for matched, update_on_incorrect for missing)
        I = incorrect (update_on_incorrect for all kc_tags)
        """

    def snapshot(self) -> dict:
        """Full student state for persistence."""
        return {
            "persona": self.persona.__dict__,
            "memory": self.memory.snapshot(),
            "response_log_count": len(self.response_log),
        }

    @classmethod
    def from_snapshot(cls, data: dict) -> 'SyntheticStudent':
        """Restore from snapshot."""
```

Use `aiohttp` or `urllib.request` for HTTP calls. Prefer stdlib `urllib` to avoid extra dependencies, but use `asyncio` patterns. If using urllib (sync), wrap in `asyncio.to_thread()` for concurrency.

### 4. `simulator/cohort.py` — Cohort Manager

```python
class StudentCohort:
    def __init__(self, students: list[SyntheticStudent]):
        self.students = students

    @classmethod
    def from_personas(cls, personas: list[StudentPersona]) -> 'StudentCohort':
        """Create a cohort of fresh students from persona definitions."""

    @classmethod
    def from_snapshots(cls, snapshot_dir: str) -> 'StudentCohort':
        """Restore a cohort from a directory of snapshot JSON files."""

    async def run_evaluation(
        self,
        items: list[dict],          # canonical items
        endpoint: str,
        model: str = "qwen3:8b",
        lesson_texts: dict[str, str] | None = None,  # item_id -> lesson text
        max_concurrent: int = 5,    # limit concurrent Ollama requests
    ) -> list[dict]:
        """
        Run all students through all items.
        Returns list of response dicts: [{student_id, item_id, response, timestamp}, ...]
        Use asyncio.Semaphore(max_concurrent) to throttle.
        """

    def apply_inter_unit_gap(self, gap_seconds: float):
        """Apply forgetting curves to all students."""

    def save_snapshots(self, output_dir: str):
        """Save each student's state to output_dir/{persona_id}.json"""

    def get_summary(self) -> dict:
        """Return summary stats: n_students, avg KC strength, etc."""
```

### 5. `simulator/__init__.py`
Export the main classes:
```python
from .memory import KCState, StudentMemory, recall_probability
from .student import StudentPersona, SyntheticStudent
from .cohort import StudentCohort
from .prompts import build_student_system_prompt, build_item_prompt
```

## Testing Notes
- All snapshot/restore round-trips must be lossless
- Forgetting curves must be monotonically decreasing
- recall_probability(kc, now) must return values in [0, 1]
- Persona tier 5 students should outperform tier 1 students on average
