# Autoresearch Mirofish - Foundation Spec

**Project:** Synthetic student simulation engine + autoresearch curriculum optimization loop for AP Statistics
**Inspired by:** public descriptions of Austin Way's synthetic-student workflow and Karpathy's autoresearch keep-if-better loop
**Date:** 2026-03-16

---

## 0. Verification Status

This document is a **foundation spec**, not a proof that every external claim in the originating conversation is settled fact.

### Verified locally against neighboring repos

- `curriculum_render` contains the canonical AP Stats item bank in `data/curriculum.js`, AP framework data in `data/frameworks.js`, and FRQ grading logic in `js/grading/frq-grading-rules.js` plus `js/grading/grading-engine.js`.
- `lrsl-driller` contains cartridge manifests, generators, and grading rules. At least some generators return the exact shape `{ context, graphConfig, answers, scenario }`.
- `Agent` contains a dependency-resolving task runner that explicitly uses Kahn's algorithm / topological waves, plus lesson registry and model profile files.
- `grid-bot-v3` contains the self-tuning belief-weight pattern and a persistent guardian loop pattern.

### Verified from public primary sources

- Karpathy's `autoresearch` repo exists and really does use a fixed evaluation harness (`prepare.py`), a single mutable surface (`train.py`), a dedicated `autoresearch/<tag>` branch, and a `results.tsv` keep/discard loop.
- Qwen3-8B exists as an official open model with native 32,768 context and 131,072 with YaRN.
- Ollama officially supports Qwen 3 and exposes explicit thinking controls via the `think` field in API calls and `/set nothink` in interactive mode.
- vLLM and SGLang explicitly position themselves around high-throughput serving, continuous batching, and prefix caching.

### Not independently verified here

- The exact Austin Way implementation details, especially the literal operational meaning of "100,000 students", the precise infra used, and the economics behind that run. Treat those as inspiration, not as a pinned implementation target.
- Model availability and pricing on hosted inference providers can drift quickly. Provider-specific deployment choices must be re-checked at implementation time.

### Design consequence

Where a claim is unverified or volatile, this spec uses it only as direction. The build plan should anchor on:

1. Local repo facts
2. Official model/runtime docs
3. Measured performance from your own evaluation harness

---

## 1. System Overview

An autonomous loop where:
1. The **Agent pipeline** generates curriculum artifacts (worksheets, drills, Blookets) from source material
2. **Qwen 3 8B** (non-thinking mode) acts as N synthetic AP Stats students with epistemically-constrained, cumulative memory
3. Students work through the generated artifacts, unit by unit, retaining knowledge across units
4. Responses are graded by the existing E/P/I grading stack
5. Failure patterns are analyzed by a stronger outer model
6. The Agent pipeline **regenerates** the artifacts with targeted improvements
7. Keep if metrics improve, revert if not — iterate until converged, then advance to the next unit
8. Students carry all prior-unit knowledge forward, so later units are tested against realistic cumulative understanding

### Design Principles

**Epistemic constraint over role-play.** The student model may only "know" what its memory state says it knows. Naive "act like a student" prompts fail due to the competence paradox (pretrained knowledge leaks through). Enforce constraints via structured KC state + context gating, not just prompting.

**Goodhart guardrail.** The loop will exploit quirks of the simulator and grader unless we use holdout sets, multi-metric scoring, and real-student anchoring. Never optimize against a single scalar.

**Weak student, strong optimizer.** Qwen 3 8B (non-thinking, mid-quantization) for student simulation. Claude/GPT-4/Codex for failure analysis and curriculum rewriting. The same model must never both define failures and fix them.

**Bridge existing JS systems before rewriting them.** Your curriculum, grading, and cartridge generation logic already exist in neighboring JavaScript repos. Phase 0 and Phase 1 should call that logic through thin adapters instead of immediately re-implementing it in Python.

**Sequential unit progression with cumulative memory.** Students learn Unit 1 first. Once the loop converges on Unit 1 material, students advance to Unit 2 carrying everything they learned (and partially forgot) from Unit 1. This mirrors how real students experience the course and means later-unit optimization accounts for prerequisite decay — the most valuable signal for curriculum improvement.

---

## 2. Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                    OUTER LOOP (per unit, sequential)                 │
│                                                                     │
│  ┌──────────────┐    ┌──────────────┐    ┌───────────────┐         │
│  │ Agent Pipeline│───▶│  Synthetic   │───▶│   Grading     │         │
│  │ (generates   │    │  Students    │    │   Pipeline    │         │
│  │  worksheets, │    │  Qwen3-8B ×N │    │  (frozen)     │         │
│  │  drills,     │    │  cumulative  │    └───────┬───────┘         │
│  │  Blookets)   │    │  memory ────────────────────────┐           │
│  └─────▲─────┘    └──────────────┘              │      │           │
│        │                                         │      │           │
│        │          ┌──────────────┐                │      │           │
│        └──────────│   Optimizer  │◀───────────────┘      │           │
│                   │  (strong LLM)│                        │           │
│                   │  + Analysis  │──▶ git commit/revert  │           │
│                   └──────────────┘                        │           │
│                                                          │           │
│  ┌───────────────────────────────────────────────────────▼────────┐ │
│  │              STUDENT MEMORY (persists across units)             │ │
│  │  U1 KCs: VAR-1.A=0.75, UNC-1.A=0.40 (decaying)               │ │
│  │  U2 KCs: UNC-2.A=0.70, UNC-2.B=0.65 (fresh)                  │ │
│  │  U3 KCs: (not yet learned)                                     │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                                                                     │
│  When Unit N converges → snapshot student memory → advance to N+1   │
└─────────────────────────────────────────────────────────────────────┘
```

### Repo Boundaries

| Repo | Role in System | Read/Write |
|------|---------------|------------|
| `ai_autoresearch_mirofish` | Loop orchestrator, student simulator, analysis engine, experiment logs | **Primary workspace** |
| `curriculum_render` | Question bank, frameworks, grading rules | **Read** for eval items + grading; **Write** when converged improvements are promoted to production |
| `lrsl-driller` | Cartridge manifests, generators, grading rules | **Read** for problem generation + grading; **Write** when converged cartridge improvements are promoted |
| `apstats-live-worksheet` | Follow-along worksheets | **Write** target — regenerated by Agent pipeline with optimized content |
| `Agent` | Lesson-prep pipeline orchestrator (video ingest → worksheet → drills → Blooket → Schoology) | **Direct integration** — the autoresearch loop wraps around the Agent pipeline, using it to regenerate artifacts each iteration |
| `grid-bot-v3` | Belief engine / consensus patterns | **Pattern reference** (port weighting logic) |

### How the Agent pipeline fits in

The Agent repo's `lesson-prep.mjs` already has a 10-step pipeline: video ingest → worksheet generation → drill cartridge generation → Manim animations → Blooket upload → Schoology posting. The autoresearch loop does NOT replace this pipeline — it wraps around it:

1. **Agent pipeline generates** the initial artifacts for a unit/lesson
2. **Autoresearch loop tests** those artifacts with synthetic students
3. **Optimizer proposes** targeted improvements (better exposition, reordered scaffolding, clearer hints)
4. **Agent pipeline regenerates** the artifacts incorporating those improvements
5. **Loop re-tests** — keep if better, revert if not
6. When converged, promote the best version to the production repos

---

## 3. Qwen 3 8B Deployment

### Development (local, Windows 11, no admin)

**Primary: Ollama** — installs to `%USERPROFILE%`, no admin required, exposes `http://localhost:11434`

```bash
# Install (user-space, no admin)
# Download from ollama.com → Windows installer

# Pull Qwen3 8B
ollama pull qwen3:8b          # ~5.2GB, pre-quantized

# Serve (starts automatically, or manually)
ollama serve

# API endpoint
# POST http://localhost:11434/api/chat
# POST http://localhost:11434/api/generate
```

**Fallback: llama.cpp** — prebuilt Windows x64 binaries, CPU/Vulkan/CUDA

```bash
# Download release from github.com/ggerganov/llama.cpp/releases
# Use llama-server for OpenAI-compatible API
llama-server -m qwen3-8b-q4_k_m.gguf --port 8080
```

### Configuration

| Setting | Value | Rationale |
|---------|-------|-----------|
| Mode | **Non-thinking** (`think: false` in Ollama API, `/set nothink` in interactive Ollama, or `enable_thinking=false` in Qwen/vLLM-style runtimes) | Prevents unrealistically strong reasoning chains |
| Quantization | **Q4_K_M** or **Q5_K_M** | Keeps outputs fluent but "imperfect" — desirable for student sim |
| Temperature | **0.7–0.9** | Variability in student responses |
| Max tokens (MCQ) | **5** | Force letter-only output |
| Max tokens (FRQ) | **200** | Prevent over-elaboration |
| Context window | **4096** (capped) | Students don't have perfect recall of long lessons |

### Scale (cloud, for overnight runs)

Use a **verified-runtime-first** approach instead of pinning the project to one provider's March 2026 catalog.

| Path | Verified status | Recommended use |
|------|-----------------|-----------------|
| RunPod + vLLM/SGLang | Verified | Primary path for throughput experiments and overnight runs. Best fit when you want direct control over batching, KV cache, and prefix caching. |
| Fireworks AI serverless or on-demand deployment | Verified for Qwen3-8B | Good managed option if you want hosted deployment. Qwen3-8B currently has both serverless pricing and on-demand deployment listed. |
| Together AI | Partially verified | Treat as optional. Check live model availability at implementation time instead of hardcoding Qwen3-8B into the spec. |
| CPU-only local run | Verified | Good for MVP correctness checks only. Not the target for large overnight sweeps. |

**Key insight:** "100,000 instances" = 100,000 async sessions multiplexed through a small number of inference servers via continuous batching (vLLM PagedAttention / SGLang RadixAttention). Not 100K separate processes.

**Prefix caching** is critical: all students share the same curriculum prompt prefix. SGLang's RadixAttention or vLLM's automatic prefix caching means the shared prefix is computed once.

**Operational recommendation:** treat hosted pricing and model availability as runtime configuration, not as spec constants. This repo should accept provider/model settings from config files and record the resolved provider, model, and cost assumptions in each experiment log.

---

## 4. Synthetic Student Model

### 4.1 Knowledge Component (KC) State Machine

Each synthetic student maintains a per-KC memory state:

```python
@dataclass
class KCState:
    kc_id: str                    # e.g., "VAR-1.A", "UNC-3.B"
    strength: float               # 0.0–1.0 (probability of correct recall)
    last_seen_at: float           # unix timestamp
    last_recalled_at: float       # unix timestamp of last correct retrieval
    error_mode: str               # "none" | "misconception_A" | "misconception_B" | ...
    error_strength: float         # 0.0–1.0 (how entrenched the misconception is)
    exposure_count: int           # times this KC appeared in curriculum
    correct_count: int            # times correctly answered
```

### 4.2 Forgetting Curve

Exponential decay with spaced-retrieval boost:

```python
def recall_probability(kc: KCState, now: float) -> float:
    """Ebbinghaus-inspired: fast initial forgetting, slower decay."""
    age = now - kc.last_recalled_at
    # Half-life increases with successful retrievals (spacing effect)
    half_life_hours = 2.0 * (1.5 ** kc.correct_count)  # 2h → 3h → 4.5h → ...
    decay = 0.5 ** (age / (half_life_hours * 3600))
    return kc.strength * decay
```

### 4.3 Persona Parameters

Each synthetic student is parameterized by a persona seed that controls:

```python
@dataclass
class StudentPersona:
    persona_id: str               # deterministic seed for reproducibility
    ability_tier: int             # 1–5 (maps to target AP score)
    kc_acquisition_rate: float    # 0.05–0.30 (how much each lesson boosts strength)
    carelessness: float           # 0.0–0.15 (probability of slip even when KC is known)
    guess_strategy: str           # "random" | "misconception_driven" | "partial_knowledge"
    misconception_persistence: float  # 0.5–0.95 (how sticky wrong mental models are)
    reading_comprehension: float  # 0.6–1.0 (probability of correctly parsing the question)
    working_memory_slots: int     # 3–7 (max concurrent facts in reasoning chain)
```

**Tier distribution** (calibrate to match real AP Stats score distribution):

| Tier | Target AP Score | Population % | Acquisition Rate | Carelessness |
|------|----------------|-------------|-----------------|-------------|
| 1 | 1 | 15% | 0.05 | 0.10 |
| 2 | 2 | 20% | 0.10 | 0.08 |
| 3 | 3 | 25% | 0.15 | 0.06 |
| 4 | 4 | 25% | 0.22 | 0.04 |
| 5 | 5 | 15% | 0.30 | 0.02 |

### 4.4 System Prompt Template

```
You are a high school student in AP Statistics. You are in your {persona.ability_tier}
performance tier. You may ONLY use knowledge from your MEMORY below. Do NOT use any
facts, formulas, or concepts not present in your memory.

## YOUR MEMORY (what you currently know)
{rendered_kc_states — only KCs with recall_probability > 0.3}

## TODAY'S LESSON
{exposition_text — the curriculum content being tested}

## INSTRUCTIONS
- For multiple choice: respond with ONLY a single letter (A/B/C/D/E)
- For free response: write a short answer using Answer/Work/Conclusion format
- If you don't know something, guess using common student misconceptions
- You make arithmetic mistakes {persona.carelessness * 100}% of the time
- You can hold {persona.working_memory_slots} facts in your head at once
```

---

## 5. Curriculum Data Model

### 5.1 Canonical Item Schema

Bridges `curriculum_render` questions and `lrsl-driller` cartridge problems into a single evaluation format:

```python
@dataclass
class CanonicalItem:
    item_id: str                  # stable ID: "CR:U1-L2-Q01" or "DR:apstats-lsrl:l03:seed42"
    source: str                   # "curriculum_render" | "lrsl_driller"
    item_type: str                # "mcq" | "frq" | "frq_multipart"
    unit: int                     # 1–9
    lesson: int
    kc_tags: list[str]            # ["VAR-1.A", "UNC-2.B"] — from frameworks.js
    prompt: str                   # rendered question text
    choices: list[dict] | None    # [{"key": "A", "value": "..."}] for MCQ
    expected: dict                # {"answer_key": "B"} or {"rubric_rule": "describeDistributionSOCS"}
    seed: int | None              # for reproducible generator output (driller only)
    difficulty_estimate: float    # 0.0–1.0 (calibrated from real data or heuristic)
```

### 5.2 KC Tag Mapping

Map every question to AP framework learning objectives:

```python
# Source: curriculum_render/data/frameworks.js
# Format: {unit: {lesson: {learningObjectives: [{id: "VAR-1.A", ...}]}}}

# The KC tag vocabulary is the set of all framework IDs:
# VAR-1.A, VAR-1.B, UNC-1.A, UNC-2.A, ..., DAT-3.A, etc.
# Plus skill codes: 1.A, 1.B, 2.A, 2.B, 3.A, 3.B, 4.A, 4.B
```

**Critical missing piece:** curriculum_render questions don't currently have `kc_tags`. Phase 0 work includes tagging them (can be LLM-assisted given the frameworks.js context).

### 5.3 Evaluation Set Structure

```python
@dataclass
class EvaluationSet:
    set_id: str                   # "dev_v1", "holdout_v1", "full_practice_exam_v1"
    set_type: str                 # "dev" | "holdout" | "real_anchor"
    items: list[CanonicalItem]
    persona_seeds: list[str]      # fixed persona IDs for paired comparisons
    frozen_at: str                # git commit hash when this set was pinned
```

Three splits (Goodhart guardrail):
- **`dev`** — small (20–40 items), used every iteration, fast feedback
- **`holdout`** — larger (full practice exam), used every 10th iteration, never informs edits
- **`real_anchor`** — derived from real student performance data in Supabase, used for calibration checks

---

## 6. Grading Integration

### 6.1 Grading Pipeline (frozen during optimization)

For synthetic students, use a simplified grading path:

```
MCQ → exact match to answer_key → E or I (no partial credit)
FRQ → regex/rubric from frq-grading-rules.js → E/P/I
FRQ (no rule match) → AI grader via Ollama Qwen3-8B (local) or Groq (remote)
```

**Do NOT use the curriculum_render server** for grading synthetic students — it would create unnecessary load and coupling. Instead, call the existing grading logic through local Node adapters so the evaluation harness stays aligned with the production repos.

### 6.2 Grading Adapters

```json
{
  "adapter": "curriculum_render/grade_frq.mjs",
  "input": {
    "answer": "The distribution is right-skewed with one high outlier.",
    "ruleId": "describeDistributionShape",
    "context": {
      "variable": "completion time"
    }
  },
  "output": {
    "score": "P",
    "feedback": "Good, but consider including center/spread.",
    "matched": ["shape", "outliers"],
    "missing": ["center", "spread"]
  }
}
```

### 6.3 Score Aggregation

Per-iteration metrics computed from all student × item results:

```python
@dataclass
class IterationMetrics:
    curriculum_version: str       # git commit hash
    iteration_id: int
    timestamp: float
    n_students: int
    n_items: int

    # Primary metrics
    mean_score: float             # weighted E=3, P=2, I=1, averaged
    mcq_accuracy: float           # fraction correct
    frq_e_rate: float             # fraction scoring E on FRQ
    frq_p_rate: float             # fraction scoring P
    frq_i_rate: float             # fraction scoring I

    # Per-unit breakdown
    unit_scores: dict[int, float] # {1: 0.72, 2: 0.65, ...}

    # Per-KC breakdown
    kc_mastery: dict[str, float]  # {"VAR-1.A": 0.85, "UNC-2.B": 0.42, ...}

    # Failure clustering
    top_failure_kcs: list[tuple[str, float]]  # worst 10 KCs by error rate
    misconception_counts: dict[str, int]       # misconception type frequencies

    # Holdout (computed less frequently)
    holdout_score: float | None
```

---

## 7. Autoresearch Loop

### 7.1 Two-Level Loop Structure

The system has two nested loops:

**Outer loop: unit-by-unit progression (sequential)**
```
FOR unit = 1 TO 9:
  1. INITIALIZE or RESTORE student memory snapshots from previous unit
  2. RUN inner loop on this unit until converged (or max iterations)
  3. SNAPSHOT all student memory states (KC strengths, misconceptions)
  4. PROMOTE converged artifacts to production repos
  5. ADVANCE to next unit — students carry cumulative memory
```

**Inner loop: keep-if-better iteration (per unit, ported from Karpathy)**
```
WHILE not converged AND iteration < max:
  1. Agent pipeline GENERATES artifacts (worksheet, drills, Blooket) for this unit
  2. RUN synthetic student cohort through the generated material
     - Students already "know" everything from prior units (with decay)
  3. GRADE all responses via existing E/P/I stack
  4. COMPUTE iteration metrics
  5. IF metrics improved over best-known:
       KEEP commit (advance best pointer)
     ELSE:
       REVERT to best commit
  6. ANALYZE failure patterns (strong outer model)
     - Distinguish: is the failure from NEW material or FORGOTTEN prerequisite?
  7. GENERATE targeted improvements to the artifacts
  8. COMMIT to autoresearch branch
  9. GOTO 1
```

### 7.2 Mutable vs Frozen Surfaces

**Mutable (what the loop may edit via the Agent pipeline):**
- `apstats-live-worksheet` worksheets — exposition text, worked examples, scaffolding
- `lrsl-driller` cartridges — hint text, mode sequencing, generator parameters, difficulty ramps
- `curriculum_render` question bank — prompt wording, choice distractors, FRQ rubric hints
- Blooket question sets — regenerated with improved question text
- `curriculum_patches/{unit}/{lesson}/` — intermediate overlay files (pre-promotion)

**Frozen (must not change during a run):**
- Evaluation sets (item bank + seeds)
- Grading rules and rubrics (the scoring logic itself)
- Student persona distribution
- The loop orchestrator itself
- Student memory snapshots from completed prior units

### 7.3 Cumulative Memory Across Units

When the loop finishes Unit N and advances to Unit N+1:

```python
# Snapshot student memory after Unit N converges
for student in cohort:
    snapshot = {
        "persona_id": student.persona_id,
        "unit_completed": N,
        "kc_states": student.get_all_kc_states(),  # full KC map with strengths
        "timestamp": now()
    }
    save_snapshot(f"snapshots/unit_{N}/{student.persona_id}.json", snapshot)

# Restore when starting Unit N+1
for student in cohort:
    prior = load_snapshot(f"snapshots/unit_{N}/{student.persona_id}.json")
    student.restore_kc_states(prior["kc_states"])
    student.apply_forgetting(elapsed_time=INTER_UNIT_GAP)  # simulate time between units
```

**Why this matters:** If Unit 5 (Sampling Distributions) fails because students forgot Unit 1 (describing distributions), the optimizer can respond by:
- Adding a review scaffold at the start of Unit 5's worksheet
- Strengthening the Unit 1 exposition (re-run Unit 1's loop with tighter targets)
- Adjusting the Unit 5 drill cartridge to include prerequisite warm-up problems

This is signal you cannot get without cumulative memory.

### 7.4 Git Strategy

```bash
# Branch naming
autoresearch/apstats-20260316

# Each iteration creates a structured commit
git commit -m "iter-047: mean_score 2.31→2.38, patched U3 exposition (sampling methods)"

# Best-known pointer tracked in experiment state file
# On regression: git reset --hard to best commit, try different patch
```

### 7.5 Improvement Metric (multi-objective)

Single-scalar selection criterion with guardrails:

```python
def is_improvement(current: IterationMetrics, best: IterationMetrics) -> bool:
    """Keep-if-better decision. Multi-metric to resist Goodhart."""
    # Primary: mean score must improve
    if current.mean_score <= best.mean_score:
        return False
    # Guard 1: no unit may regress by more than 0.1
    for unit, score in current.unit_scores.items():
        if score < best.unit_scores.get(unit, 0) - 0.1:
            return False
    # Guard 2: holdout score (when available) must not diverge
    if current.holdout_score and best.holdout_score:
        if current.holdout_score < best.holdout_score - 0.05:
            return False
    return True
```

---

## 8. Outer Optimizer (Failure Analysis + Patch Generation)

### 8.1 Failure Analysis Prompt

Fed to Claude/GPT-4 (the strong outer model):

```
You are an AP Statistics curriculum expert analyzing synthetic student test results.

## ITERATION RESULTS
Mean score: {metrics.mean_score} (previous best: {best.mean_score})
Top 10 failure KCs:
{for kc, rate in metrics.top_failure_kcs}
  - {kc}: {rate*100}% error rate
{endfor}

## COMMON MISCONCEPTIONS OBSERVED
{misconception_counts}

## CURRENT CURRICULUM TEXT (for worst-performing KCs)
{exposition texts for failing KCs}

## AP FRAMEWORK REQUIREMENTS
{relevant learning objectives from frameworks.js}

## FAILURE SOURCE ANALYSIS
For each failing KC, classify the root cause:
- "new_material": the current unit's exposition/examples are unclear
- "prerequisite_decay": student forgot a prior-unit concept (specify which KC)
- "misconception": student holds a specific wrong mental model
- "question_wording": the question prompt is ambiguous or misleading

## TASK
1. Diagnose WHY students are failing on these KCs (pedagogical root cause + source)
2. Propose SPECIFIC edits to the appropriate artifact:
   - Worksheet exposition → {"target": "worksheet", "unit": N, "lesson": N, ...}
   - Drill hint/scaffolding → {"target": "driller_cartridge", "cartridge_id": "...", ...}
   - Blooket question text → {"target": "blooket", "unit": N, "lesson": N, ...}
   - Prerequisite review insert → {"target": "worksheet", "unit": N, "section": "prereq_review", ...}
3. Keep changes minimal and targeted — one concept fix per patch
4. Do NOT change the grading rules or evaluation items
```

### 8.2 Patch Application

```python
def apply_curriculum_patch(patch: dict, branch: str) -> str:
    """Apply a single curriculum patch and commit."""
    path = f"curriculum_patches/{patch['unit']}/{patch['lesson']}/{patch['field']}.json"
    # Read current overlay (or create)
    overlay = load_json(path) if exists(path) else {}
    # Apply edit
    overlay[patch.get("section", "main")] = patch["new_text"]
    # Write
    write_json(path, overlay)
    # Commit
    commit_hash = git_commit(f"iter-{iteration}: patch U{patch['unit']}L{patch['lesson']} {patch['field']}")
    return commit_hash
```

---

## 9. Integration Patterns (from existing repos)

### 9.1 Agent Pipeline Integration (primary)

The Agent repo's `lesson-prep.mjs` pipeline is the artifact generation engine. Each autoresearch iteration invokes relevant steps of this pipeline with improvement parameters:

```python
# One autoresearch iteration = Agent pipeline generate + student test + analyze
ITERATION_STEPS = [
    # --- GENERATION (via Agent pipeline) ---
    {"task": "agent_generate",     "depends_on": [],
     "desc": "Call Agent lesson-prep pipeline to generate/regenerate artifacts"},

    # --- EVALUATION (this repo) ---
    {"task": "load_artifacts",     "depends_on": ["agent_generate"],
     "desc": "Load generated worksheet, drills, Blooket items as canonical items"},
    {"task": "restore_memory",     "depends_on": [],
     "desc": "Restore student KC states from prior-unit snapshots"},
    {"task": "run_students",       "depends_on": ["load_artifacts", "restore_memory"]},
    {"task": "grade_responses",    "depends_on": ["run_students"]},
    {"task": "compute_metrics",    "depends_on": ["grade_responses"]},

    # --- DECISION ---
    {"task": "decide_keep_revert", "depends_on": ["compute_metrics"]},

    # --- OPTIMIZATION (if keeping) ---
    {"task": "analyze_failures",   "depends_on": ["decide_keep_revert"],
     "desc": "Classify failures: new material vs prerequisite decay vs misconception"},
    {"task": "generate_improvements", "depends_on": ["analyze_failures"],
     "desc": "Produce targeted improvement params for next Agent pipeline run"},
    {"task": "commit_and_loop",    "depends_on": ["generate_improvements"]},
]
```

The key difference from vanilla autoresearch: the mutable surface is not a single file — it's the **generation parameters** fed to the Agent pipeline. The pipeline regenerates real artifacts (worksheets, drills, Blookets) each iteration.

### 9.2 Multi-Source Consensus Pattern (from grid-bot-v3)

When multiple outer models propose patches, use weighted consensus:

```python
# Source weights for curriculum patch proposals
OPTIMIZER_WEIGHTS = {
    "claude": 1.0,      # primary optimizer
    "gpt4": 0.9,        # secondary
    "codex": 0.7,       # code-focused patches
}

# Self-tuning: track which optimizer's patches actually improved scores
# Decay by recency (5-iteration half-life) + Brier-style calibration
# Identical to grid-bot-v3's compute_tuned_weights()
```

### 9.3 Gate Pipeline Pattern (from grid-bot-v3 Governor)

Before accepting a patch, run it through quality gates:

```python
PATCH_GATES = [
    "correctness_gate",    # Does the new text contain factual errors? (LLM check)
    "readability_gate",    # Is reading level appropriate for HS students? (Flesch-Kincaid)
    "length_gate",         # Did we bloat the exposition? (word count delta)
    "framework_gate",      # Does it still address the AP learning objectives?
    "regression_gate",     # Did any unit score drop? (from metrics)
]
```

---

## 10. Data Storage

### 10.1 Local File Structure

```
ai_autoresearch_mirofish/
├── FOUNDATION_SPEC.md              # This file
├── config/
│   ├── experiment.json             # Current experiment config (N students, eval set, etc.)
│   ├── personas.json               # Student persona definitions
│   └── provider.json               # Ollama/cloud endpoint config
├── curriculum_patches/             # Intermediate improvement overlays (pre-promotion)
│   ├── 1/                          # Unit 1
│   │   ├── 1/                      # Lesson 1
│   │   │   ├── exposition.json     # Worksheet exposition improvements
│   │   │   ├── hints.json          # Drill hint improvements
│   │   │   ├── scaffolding.json    # Step-by-step breakdown improvements
│   │   │   └── blooket.json        # Blooket question improvements
│   │   └── ...
│   └── ...
├── snapshots/                      # Student memory snapshots (persist across units)
│   ├── unit_1/                     # KC states after Unit 1 converges
│   │   ├── student_tier1_001.json
│   │   ├── student_tier2_001.json
│   │   └── ...
│   ├── unit_2/
│   └── ...
├── eval_sets/                      # Frozen evaluation sets
│   ├── unit_1_dev_v1.json          # Per-unit dev sets
│   ├── unit_2_dev_v1.json
│   ├── holdout_v1.json             # Full-course holdout (all 9 units)
│   └── real_anchor_v1.json         # Derived from Supabase classroom data
├── adapters/                       # Thin bridges into existing JS repos
│   ├── curriculum_render/
│   │   ├── extract_items.mjs       # Read data/curriculum.js -> canonical items
│   │   ├── grade_frq.mjs           # Reuse existing FRQ grading rules/engine
│   │   └── grade_mcq.mjs           # Exact-match MCQ grading wrapper
│   ├── lrsl_driller/
│   │   ├── generate_item.mjs       # Call cartridge generators with seeds
│   │   └── grade_answers.mjs       # Reuse cartridge grading rules/engine
│   └── agent_pipeline/
│       └── invoke_lesson_prep.mjs  # Call Agent lesson-prep steps with improvement params
├── simulator/                      # Synthetic student engine
│   ├── student.py                  # Student class (persona + KC state + forgetting)
│   ├── memory.py                   # KC state machine + forgetting curves
│   ├── cohort.py                   # Manages N students, parallel execution, snapshots
│   └── prompts.py                  # System prompt templates
├── optimizer/                      # Outer loop (analysis + patching)
│   ├── analyzer.py                 # Failure pattern clustering + source classification
│   ├── patcher.py                  # Targeted improvement generation (per artifact type)
│   ├── consensus.py                # Multi-model patch weighting (ported from grid-bot)
│   └── gates.py                    # Patch quality gates
├── loop/                           # Autoresearch loop orchestrator
│   ├── runner.py                   # Inner loop (per-unit keep-if-better)
│   ├── progression.py              # Outer loop (unit-by-unit advancement + memory carry)
│   ├── metrics.py                  # Score computation + improvement check
│   └── git_ops.py                  # Branch management, commit, revert
├── data/                           # Canonical curriculum + item data
│   ├── items/
│   │   ├── curriculum_render.json  # Parsed from curriculum.js
│   │   └── lrsl_driller.json       # Generated from cartridge generators
│   ├── frameworks.json             # Parsed from frameworks.js
│   └── kc_tags.json                # KC tag vocabulary + question mappings
├── logs/                           # Experiment logs (gitignored for large runs)
│   ├── runs/
│   │   └── 20260316_unit1_001/
│   │       ├── config.json
│   │       ├── responses.jsonl
│   │       ├── grades.jsonl
│   │       ├── metrics.json
│   │       ├── failure_analysis.json  # Source-classified failures
│   │       └── patches.json
│   └── summary.tsv                 # One line per iteration (like autoresearch results.tsv)
├── scripts/
│   ├── run_experiment.py           # Single iteration (one unit)
│   ├── run_loop.py                 # Full autoresearch inner loop (one unit)
│   ├── run_course.py               # Full outer loop (all units sequential)
│   ├── extract_items.py            # Python orchestrator over JS adapters
│   ├── tag_kcs.py                  # LLM-assisted KC tagging
│   ├── promote.py                  # Push converged improvements to production repos
│   └── calibrate.py                # Compare synthetic vs real student distributions
└── tests/
    ├── test_student.py
    ├── test_adapters.py
    ├── test_memory.py
    ├── test_snapshots.py
    └── test_loop.py
```

### 10.2 Experiment State File

```json
{
  "experiment_id": "apstats-20260316",
  "branch": "autoresearch/apstats-20260316",
  "iteration": 47,
  "best_iteration": 42,
  "best_commit": "abc123def",
  "best_metrics": {
    "mean_score": 2.38,
    "mcq_accuracy": 0.71,
    "frq_e_rate": 0.35
  },
  "config": {
    "n_students": 100,
    "eval_set": "dev_v1",
    "student_endpoint": "http://localhost:11434/api/chat",
    "student_model": "qwen3:8b",
    "optimizer_provider": "configured-strong-model",
    "optimizer_model": "configured-at-runtime",
    "max_iterations": 500,
    "holdout_interval": 10
  },
  "started_at": "2026-03-16T20:00:00Z",
  "last_iteration_at": "2026-03-17T04:23:00Z"
}
```

### 10.3 Summary TSV (like autoresearch results.tsv)

```
iteration	commit	mean_score	mcq_acc	frq_e	frq_p	frq_i	holdout	kept	patch_desc	timestamp
001	a1b2c3d	2.05	0.58	0.20	0.35	0.45		yes	baseline	2026-03-16T20:00:00Z
002	e4f5g6h	2.12	0.61	0.22	0.36	0.42		yes	U1 exposition clarity	2026-03-16T20:15:00Z
003	i7j8k9l	2.08	0.59	0.21	0.37	0.42		no	U3 sampling rewrite	2026-03-16T20:30:00Z
```

---

## 11. Phased Implementation

### Phase 0: Data Extraction + KC Tagging (prerequisite)

1. Parse `curriculum_render/data/curriculum.js` → `data/items/curriculum_render.json` (canonical items)
2. Parse `curriculum_render/data/frameworks.js` → `data/frameworks.json`
3. LLM-assisted KC tagging: for each question, assign `kc_tags[]` from framework vocabulary
4. Generate sample items from `lrsl-driller` cartridges → `data/items/lrsl_driller.json`
5. Build Node adapters that call existing grading and generation code in `curriculum_render` and `lrsl-driller`
6. Build `eval_sets/dev_v1.json` — Unit 1 items only (20–40 items, mix of MCQ + FRQ)
7. Verify Agent pipeline can be invoked programmatically for a single unit/lesson
8. Decide whether any grading logic actually needs a later Python port; do not assume that up front

### Phase 1: MVP — Single Iteration on Unit 1 (weekend build)

**Goal:** 10 synthetic students, Unit 1 only, measure pass rate, one round of improvement

1. Install Ollama + pull `qwen3:8b`
2. Implement `simulator/student.py` with basic persona + KC state + forgetting curve
3. Implement `simulator/prompts.py` with system prompt template
4. Implement adapter-backed grading calls so the MVP reuses the JS grading logic already in the neighboring repos
5. Implement `loop/metrics.py` (score aggregation)
6. Implement `scripts/run_experiment.py` — single pass: load Unit 1 items → prompt students → grade → report
7. Run once, inspect outputs, validate grading correctness
8. Verify KC states update correctly after the run (strengths increase for correct, misconceptions for incorrect)

**Exit criteria:** Can run 10 students through Unit 1 eval set and get plausible E/P/I distributions. KC states reflect what was learned.

### Phase 2: Autoresearch Loop on Unit 1 (overnight build)

**Goal:** Full keep-if-better loop running 8 hours unattended on Unit 1, regenerating real artifacts

1. Implement `loop/runner.py` — inner autoresearch loop
2. Implement `loop/git_ops.py` — branch management, commit, revert
3. Implement Agent pipeline integration — call `lesson-prep.mjs` steps to regenerate worksheets, drills, Blookets with improvement parameters
4. Implement `optimizer/analyzer.py` — failure pattern analysis with source classification (new material vs prerequisite vs misconception)
5. Implement `optimizer/patcher.py` — targeted improvement generation for each artifact type
6. Implement `optimizer/gates.py` — patch quality gates
7. Scale to 50–100 students
8. Run overnight on Unit 1, measure if mean_score improves across worksheet + drill + Blooket

**Exit criteria:** Automated loop runs unattended, regenerates real artifacts, keeps improving commits, reverts regressions. Unit 1 material measurably better.

### Phase 3: Unit-by-Unit Progression (Units 1–3)

**Goal:** Sequential unit progression with cumulative student memory

1. After Unit 1 converges, snapshot all student KC states
2. Advance to Unit 2 — students carry Unit 1 knowledge (with decay)
3. Run autoresearch loop on Unit 2
   - Failures are classified: "Unit 2 material unclear" vs "forgot Unit 1 prerequisite"
   - If prerequisite decay is the problem, optimizer can either:
     a. Add review scaffolding to Unit 2's worksheet
     b. Flag Unit 1 material for re-optimization
4. After Unit 2 converges, snapshot again (now carrying Units 1+2)
5. Repeat for Unit 3
6. Implement `scripts/calibrate.py` — compare synthetic vs real student error patterns using anonymized Supabase data

**Exit criteria:** Students carry knowledge across 3 units. Failure analysis correctly distinguishes new-material vs prerequisite-decay failures. Spearman correlation > 0.7 between real and synthetic item difficulties for Units 1–3.

### Phase 4: Full Course + Scale (Units 1–9)

**Goal:** Complete AP Statistics curriculum optimization with all artifacts polished

1. Extend to all 9 units sequentially with cumulative memory
2. Switch to verified high-throughput deployment (RunPod + vLLM/SGLang) for overnight runs
3. Scale to 500–1000 students per iteration
4. Implement multi-model optimizer consensus (ported from grid-bot belief engine)
5. Implement holdout evaluation on full practice AP exam (all 9 units)
6. Promote converged artifacts to production repos (`curriculum_render`, `lrsl-driller`, `apstats-live-worksheet`)
7. A/B test improved curriculum on real students
8. Feed real-student results back into persona calibration for next year's run

---

## 12. Statistical Power & Sample Size

For paired comparisons (same persona seeds, different curriculum versions):

| Detectable Effect (Δ mean_score) | σ estimate | N per group (α=0.05, β=0.80) |
|----------------------------------|-----------|-------------------------------|
| 0.5 (large, early iterations) | 0.8 | 42 |
| 0.3 (medium) | 0.8 | 114 |
| 0.1 (small, late iterations) | 0.8 | 1006 |

**MVP at N=100 detects medium effects.** Use paired design (same seeds) to reduce variance by ~40%.

---

## 13. Risk Register

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Competence paradox (student too smart) | Synthetic errors don't match real | Epistemic constraints + non-thinking mode + mid-quantization + Phase 3 calibration |
| Goodhart (optimizing for LLM quirks) | Curriculum helps LLM students but not real ones | Three eval splits + multi-metric + real-anchor checks |
| Grading rules too loose/strict | False signal in metrics | Validate grading against hand-scored examples before loop |
| Ollama throughput on CPU | Overnight runs too slow | Budget for a rented GPU and treat overnight cost as a range, not a fixed number |
| Curriculum patches introduce factual errors | Worse teaching material | Correctness gate (strong model checks patches) + framework alignment check |
| KC tagging errors | Wrong failure attribution | Validate tags against AP CED; iterate tagging with human review |

---

## 14. Cost Estimates

### Local Development (CPU-only, Ollama)
- **Cost:** $0 (runs on your Windows machine)
- **Throughput:** ~2–5 tok/s output → ~15 min per iteration (10 students, 30 items)
- **Overnight (8h):** ~30 iterations

### Hosted inference
- Do **not** pin the system to a single hosted-provider assumption in this spec.
- Fireworks currently lists Qwen3-8B with serverless pricing, so it is a real hosted option rather than a hypothetical one.
- Together model availability should also be checked live before use.
- Practical guidance: treat hosted inference as a **configurable option with volatile economics**, and persist provider + pricing assumptions in each run log.

### GPU rental (RunPod / self-hosted vLLM or SGLang)
- Treat GPU rental as the default scale path because the serving stack is under your control.
- Exact RTX 4090 pricing varies by RunPod product and market tier, so budget using a **range** rather than a single hardcoded figure.
- Practical planning number: budget roughly **$5–$15 for an overnight run** once you include runtime, setup friction, and some headroom.
- This is the preferred path for Phase 4 scale unless hosted availability is re-verified and clearly cheaper.

---

## 15. Open Questions (to resolve before Phase 2)

1. **How to handle chart/graph-based questions?** curriculum_render has chart FRQs with Chart.js configs — synthetic students can't "see" graphs. Options: skip them, convert to text descriptions, or generate text-based equivalents.

2. **Should the JS adapters remain the long-term evaluation layer, or should some logic be ported later?** The neighboring repos already contain working generators and graders. Default to adapters first; only port after a concrete maintenance or performance reason appears.

3. **How to handle multi-part FRQs?** curriculum_render has progressive multi-part FRQs where parts unlock sequentially. Simulate this (each part = separate prompt) or collapse to single prompt?

4. **What's the right "AP score" mapping from E/P/I to 1–5?** Need to define a rubric-to-score conversion that matches AP scoring guidelines.

5. **FERPA compliance:** Real student data used for calibration must be anonymized. Define anonymization protocol before Phase 3.

6. **How should improvement parameters be injected into the Agent pipeline?** The Agent's `lesson-prep.mjs` already supports CLI invocation for `--unit` and `--lesson`, but the autoresearch loop still needs a structured way to pass improvement parameters and capture generated artifact paths. This may require a thin wrapper in the Agent repo or a new pipeline mode.

7. **Inter-unit gap timing for forgetting curves.** How much simulated time elapses between units? Real students have ~2 weeks per unit. The forgetting curve decay needs this parameter. Should it be configurable per experiment?

8. **When to re-optimize prior units.** If Unit 5 failures are traced to Unit 1 prerequisite decay, should the loop automatically re-enter Unit 1's inner loop? Or just flag it for manual review? Re-entering risks infinite recursion; flagging risks ignoring the problem.

9. **Promotion workflow.** When converged improvements are pushed to production repos, what's the git strategy? Feature branch + PR? Direct commit to main? The production repos have their own CI and deployment pipelines to respect.

10. **Convergence criteria.** What defines "converged" for a unit? Options: N consecutive iterations with no improvement, mean_score above threshold, or improvement rate below epsilon. Need to define this before Phase 2.
