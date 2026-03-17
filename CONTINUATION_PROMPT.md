# Continuation Prompt — ai_autoresearch_mirofish

**Session date:** 2026-03-16
**Last commit:** `67b0121` on `master`
**Reason for handoff:** Moving to 96 GB RAM laptop for Ollama smoke test

---

## What to do NOW

Run the Phase 1 smoke test: 2 synthetic students answering 76 Unit 1 MCQ items
via Ollama (qwen3:8b). This validates the full pipeline end-to-end.

### Prerequisites

1. Ensure Ollama is running with `qwen3:8b` loaded:
   ```bash
   ollama serve &          # if not already running
   ollama pull qwen3:8b    # if not already pulled
   curl http://localhost:11434/api/tags  # verify model listed
   ```
2. Quick sanity check — model responds:
   ```bash
   curl http://localhost:11434/api/generate \
     -d '{"model":"qwen3:8b","prompt":"What is 2+2?","stream":false}'
   ```

### Run the smoke test

```bash
cd ~/ai_autoresearch_mirofish
python scripts/run_experiment.py --unit 1 --n-students 2
```

**Expected output:**
- Loads eval set `unit_1_dev_v1` (76 items) from `eval_sets/unit_1_dev_v1.json`
- Loads 2 personas from `config/personas.json`
- Calls Ollama 152 times (2 students x 76 items), ~5 tokens per MCQ response
- Grades via simple letter match (MCQ only in Unit 1, no FRQ)
- Prints metrics table: mean_score, MCQ accuracy, top failure KCs
- Saves results to `logs/runs/run-{timestamp}/` (grades.jsonl, metrics.json, snapshots/)

**If it works**, the next step is:
```bash
python scripts/run_experiment.py --unit 1 --n-students 10
```
Then move to the inner loop: `python scripts/run_loop.py --unit 1 --max-iterations 5`

### Known issues to watch for

- **Timeout:** `config/provider.json` has `timeout_seconds: 60`. If qwen3:8b is
  slow on first load, the first few requests may time out. Check
  `simulator/student.py` for the HTTP call and increase if needed.
- **Response parsing:** `simulator/student.py` parses MCQ responses expecting a
  single letter (A-E). If qwen3:8b returns verbose "thinking" output, the parser
  may fail silently and default to wrong answers. Check response samples in the
  grades.jsonl output.
- **Max concurrent:** `config/provider.json` sets `max_concurrent_requests: 5`.
  On 96 GB this should be fine; increase if Ollama can handle more parallelism.

---

## Session commits (this session)

```
67b0121 Persist KC tags on 817 items, add frozen eval set, wire runners to eval_set loading
```

**What was done:**
1. Ran `scripts/tag_kcs.py` — all 817 items in `data/items/curriculum_render.json`
   now have `kc_tags` populated (keyword matching against AP Stats framework).
2. Created `eval_sets/unit_1_dev_v1.json` — frozen 76-item Unit 1 dev eval set
   with metadata wrapper (eval_set_id, source_hash, items array).
3. Updated `scripts/run_experiment.py`, `scripts/run_loop.py`, `scripts/run_course.py`
   to load items from `eval_sets/` when `config.eval_set` is set. Falls back to
   filtering the full item file if no eval set found.

---

## Remaining Phase 0+1 gaps (from prior audit)

| Gap | Status | Notes |
|-----|--------|-------|
| KC tags empty | FIXED | 817/817 tagged via keyword match |
| Frozen eval set missing | FIXED | `eval_sets/unit_1_dev_v1.json` |
| Runners don't use eval_set | FIXED | All 3 scripts wired |
| Smoke test against Ollama | BLOCKED | Needs 96 GB machine — **do this now** |
| Agent pipeline adapter absent | TODO | Spec expects `adapters/agent_pipeline/invoke_lesson_prep.mjs` |
| Inner loop MVP-grade | TODO | `run_loop.py:87` uses synthetic_grades, not real LLM analysis |
| `calibrate.py` is a stub | TODO | Explicitly says "Phase 3 stub" at line 12 |
| No run artifacts exist | TODO | Will be created by first successful smoke test |

---

## Key paths

| Path | Purpose |
|------|---------|
| `config/experiment.json` | Loop config — `eval_set: "unit_1_dev_v1"` |
| `config/provider.json` | LLM endpoints — Ollama student, Claude optimizer |
| `config/personas.json` | 100 student personas across 5 ability tiers |
| `eval_sets/unit_1_dev_v1.json` | Frozen 76-item Unit 1 eval set |
| `data/items/curriculum_render.json` | Full 817-item bank (now with KC tags) |
| `data/kc_tags.json` | 169 KC tag vocabulary |
| `scripts/run_experiment.py` | Single-iteration runner (start here) |
| `scripts/run_loop.py` | Inner keep-if-better loop |
| `simulator/student.py` | SyntheticStudent — makes Ollama calls |
| `loop/runner.py` | AutoresearchRunner — loop logic |
| `FOUNDATION_SPEC.md` | Master specification (911 lines) |

---

## Environment

- **Python:** 3.12
- **Node:** v22.19.0
- **Ollama endpoint:** http://localhost:11434
- **Student model:** qwen3:8b (temp 0.8, max 5 tokens for MCQ)
- **Optimizer model:** claude-sonnet-4-6 (via ANTHROPIC_API_KEY env var)
- **Tests:** `python -m pytest tests/ -q` — 62 tests, all should pass
