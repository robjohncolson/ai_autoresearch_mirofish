# Local Resident AI — Foundation Spec

**Project:** Local always-on AI assistant with self-tuning autoresearch capability
**Hardware target:** Windows 11 laptop — Intel i7 + Arc iGPU, ~54 GB unified VRAM, 96 GB RAM
**Date:** 2026-03-21

---

## 1. Vision

A persistent, local AI intelligence living on the home laptop that:

1. **Navigates the filesystem** — crawls repos, configs, data files across all projects
2. **Summarizes what it sees** — generates markdown docs, architecture notes, improvement suggestions
3. **Writes scripts and tools** — utility scripts, automation, data transforms
4. **Describes what can be improved** — identifies dead code, stale configs, missing docs, inconsistencies
5. **Runs without internet or API cost** — fully local inference on Intel Arc iGPU
6. **Tunes itself** — uses Karpathy's autoresearch pattern to improve its own prompts and tool definitions

This is NOT a trading bot, NOT a belief generator, NOT a curriculum simulator. It's a **general-purpose local coding/navigation AI** with strong tool-calling ability.

### What this replaces

This repo previously contained a synthetic student simulation engine for AP Statistics curriculum optimization. That approach is abandoned. The repo is repurposed as the home for the local resident AI setup.

### Relationship to other projects

| Project | Role | How it connects |
|---------|------|-----------------|
| `grid-bot-v3` | Trading bot with belief consensus | **Claude Code** (API) handles autoresearch on consensus params — a separate script living in that repo. Not this project's concern. |
| `curriculum_render` | AP Stats question bank | The resident AI can crawl and summarize it, but doesn't modify it |
| `Agent` | Task runner framework | Reference for patterns; the resident AI may borrow dispatch ideas |
| `lrsl-driller` | Lesson cartridge generators | Same as curriculum_render — read-only target for summarization |

---

## 2. Hardware Profile

**Target machine:** Home laptop (96 GB RAM)

| Component | Spec | Implication |
|-----------|------|-------------|
| RAM | 96 GB total | Plenty for model + KV cache + OS + background tasks |
| Unified VRAM | ~54 GB (configurable in BIOS) | Fits 32B model at Q8_0 with 16 GB headroom |
| GPU | Intel Arc integrated (shared memory, DDR5 bandwidth) | SYCL backend required; expect 3-4 t/s at 32B |
| CPU | Intel i7 (generation TBD — document on first boot) | CPU fallback viable for small tasks |
| OS | Windows 11 | IPEX-LLM has Windows portable zips |
| Admin | Unknown for home laptop (work laptop = NO) | Prefer portable/user-space installs |
| Existing software | Ollama installed, qwen3:8b pulled | IPEX-LLM Ollama replaces vanilla Ollama for Arc acceleration |

**First-boot task:** Run `scripts/benchmark.py` to capture actual CPU model, GPU execution units, memory bandwidth, and inference speed. These numbers determine final model/quant choices.

---

## 3. Software Stack

### 3.1 Inference Runtime: IPEX-LLM Ollama (SYCL)

**Primary choice.** Intel's optimized Ollama build with SYCL backend for Arc GPUs.

- **Why:** 30%+ faster than vanilla llama.cpp SYCL on iGPU. Portable zip — no conda, no Docker. Same Ollama CLI and API the machine already has. OpenAI-compatible endpoint at `http://localhost:11434/v1`.
- **Install:** Download Portable Zip from [IPEX-LLM Ollama quickstart](https://github.com/intel/ipex-llm/blob/main/docs/mddocs/Quickstart/ollama_quickstart.md) (Windows section).
- **Config:**
  ```
  set OLLAMA_NUM_GPU=999
  set SYCL_CACHE_PERSISTENT=1
  set no_proxy=localhost,127.0.0.1
  ollama serve
  ```
- **First load:** SYCL kernel compilation takes several minutes. Subsequent loads are cached.

**Fallback:** llama.cpp `llama-server` with SYCL or Vulkan Windows release zips. More control (KV cache quantization flags, monitoring endpoints), less convenient.

### 3.2 Model Selection

**Primary: Qwen3-Coder-Next (80B MoE, 3B active per token)**

This is the top recommendation based on post-commit research. Despite being "80B total,"
only **3B parameters activate per token** (MoE routing), so inference is faster than
a dense 32B while quality is significantly higher.

| Property | Value |
|----------|-------|
| Parameters | 80B total, **3B active per token** (MoE) |
| Context | 256K native (start at 8K, scale after benchmarking) |
| Benchmark | 66.2 Aider, 44.3% SWE-Bench Pro |
| Quantization | **Q4_0** (legacy) or Unsloth UD-Q4_K_XL (~35-40 GB) |
| Weight footprint | ~35-40 GB at Q4 |
| Headroom in 54 GB | ~14-19 GB for KV cache + OS |
| Expected speed | ~5-15 t/s on Arc iGPU (MoE advantage: small active params) |
| Strength | Purpose-built for coding agents, tool calling, autonomous iteration |

**Why this over the 32B?**
- Higher quality: 66.2 Aider vs lower scores for Qwen2.5-Coder-32B
- Faster inference: only 3B active params despite 80B total weight
- Similar VRAM: ~38 GB (32B Q8) vs ~35-40 GB (80B MoE Q4) — comparable footprint
- Designed specifically for agentic coding loops (the exact use case)

**Quantization caveat:** GGUF quants from Unsloth/HuggingFace are mostly K-quants
(Q4_K_XL) and dynamic formats. Legacy Q4_0 may not be available. **On first boot,
benchmark both Q4_K_XL and Q4_0 (if available) to see if the SYCL K-quant penalty
applies to MoE models.** The MoE routing may change the performance characteristics
vs dense models. If K-quants are unacceptably slow, fall back to the dense 32B at Q8_0.

**GGUF sources:**
- `unsloth/Qwen3-Coder-Next-GGUF` on HuggingFace (Unsloth dynamic quants)
- `Qwen/Qwen3-Coder-Next-GGUF` on HuggingFace (official)

**MoE optimization flag:** For llama.cpp, use `-ot ".ffn_.*_exps.=CPU"` to offload
inactive expert weights to CPU RAM, freeing GPU memory for KV cache.

**Fallback: Qwen2.5-Coder-32B-Instruct (dense)**

If Qwen3-Coder-Next has issues (SYCL incompatibility, tool-calling bugs, OOM):

| Model | Quant | VRAM | Speed | When to use |
|-------|-------|------|-------|-------------|
| Qwen2.5-Coder-32B | Q8_0 | ~38 GB | ~3-4 t/s | Proven stable, near-lossless quality |
| Qwen2.5-Coder-32B | Q5_0 | ~22 GB | ~5-6 t/s | If Q8_0 causes memory pressure |
| Qwen3-Coder-30B-A3B MoE | Q8_0 | ~32 GB | ~5-8 t/s | Speed-optimized MoE alternative |

**Model acquisition:**
```bash
# Option A: Ollama pull (check available tags first)
ollama search qwen3-coder
ollama pull qwen3-coder:next          # or whatever the exact tag is

# Option B: Custom Modelfile from downloaded GGUF
# Download from HuggingFace:
#   https://huggingface.co/unsloth/Qwen3-Coder-Next-GGUF
# Create Modelfile:
#   FROM ./Qwen3-Coder-Next-Q4_K_XL.gguf
#   PARAMETER num_ctx 8192
# ollama create qwen3-coder-next -f Modelfile

# Fallback: Qwen2.5-Coder-32B
ollama pull qwen2.5-coder:32b-instruct-q8_0
```

### 3.3 Agent Framework

The agent framework connects the local model to real tools (filesystem, shell, git).
Test in this order — if Tier 1 works, you may not need the others.

**Tier 1 — Claude Code with local Ollama (CONFIRMED WORKING)**

Ollama v0.14.0+ exposes an **Anthropic-compatible Messages API** at
`localhost:11434/v1/messages`. Claude Code connects directly to it.
This is confirmed working as of January 2026 with tool calling, streaming,
multi-turn, and vision support.

```bash
set ANTHROPIC_AUTH_TOKEN=ollama
set ANTHROPIC_BASE_URL=http://localhost:11434
claude
```

Same interface you already know, powered by local model. Quality is lower than
API Claude, but the workflow is identical. Recommended models for this mode:
`qwen3-coder`, `glm-4.7`, `minimax-m2.1`.

**If this works reliably, it's the only framework you need.** Test on first boot.

**Tier 2 — OpenCode (open-source Claude Code alternative, 95K+ GitHub stars)**

Provider-agnostic Go-based TUI. Supports 75+ providers including Ollama.
Full agentic capabilities: bash execution, file operations, code search.
Requires 64K+ context from the model.

```bash
# Install via Go or download binary
# See: https://github.com/opencode-ai/opencode
opencode --provider ollama --model qwen3-coder-next
```

Use if: Claude Code + local Ollama has edge-case issues, or you want a
purpose-built open-source alternative.

**Tier 3 — Aider (code-focused editing)**

Purpose-built for code editing with git integration. Handles diffs, commits,
multi-file edits. Qwen3-Coder-Next scores 66.2 on Aider's own benchmark.

```bash
pip install aider-chat
aider --model ollama_chat/qwen3-coder-next --api-base http://localhost:11434
```

Use for: autoresearch loops (edit file → run experiment → measure → keep/revert).
Aider handles the git ops natively.

**Tier 4 — Qwen-Agent (Alibaba's official framework)**

Built specifically for Qwen >= 3.0 models. Native function calling, MCP
integration, code interpreter (Docker sandbox), RAG. Supports parallel
function calls out of the box.

```bash
pip install -U "qwen-agent[gui,rag,code_interpreter,mcp]"
```

Use for: custom tool-calling pipelines, MCP server integration, structured
multi-step workflows.

**Tier 5 — Open Interpreter (general-purpose)**

Natural language interface for computers. Runs code locally.

```bash
pip install open-interpreter
interpreter --api-base http://localhost:11434/v1 --model qwen3-coder-next
```

Use for: quick ad-hoc tasks, filesystem exploration, script generation.

### 3.4 Quantization Rules (Intel SYCL)

**Use legacy quant formats ONLY on Intel Arc:**

| Format | Use? | Reason |
|--------|------|--------|
| Q8_0 | YES | Near-lossless, fast SYCL kernels |
| Q5_0 | YES | Good quality-size tradeoff |
| Q4_0 | YES | Acceptable for 70B+ models |
| Q4_K_M, Q5_K_M, Q8_K | NO | SYCL kernels not optimized — measurably slower |
| Q3_K_M, Q2_K | NO | Too much quality loss for agentic work |

This is the **opposite** of the CUDA ecosystem where K-quants are preferred. Plan accordingly when downloading GGUFs.

---

## 4. Resident AI Capabilities

### 4.1 Filesystem Navigation & Summarization

The core "always-on" capability. The model crawls the hard drive and produces structured summaries.

**Targets (repos on this machine):**

| Repo | What to summarize |
|------|-------------------|
| `grid-bot-v3` | Architecture, belief pipeline, open issues, recent changes |
| `curriculum_render` | Question bank stats, coverage gaps, grading rule inventory |
| `lrsl-driller` | Cartridge manifest, generator patterns, which units are complete |
| `Agent` | Task runner patterns, machine registry, dispatch capabilities |
| Any new repo | Auto-detect purpose, generate architecture overview |

**Output format:** Markdown files in `summaries/` directory, organized by repo. Each summary includes:
- Purpose (1-2 sentences)
- Architecture diagram (Mermaid)
- Key files and their roles
- Recent activity (from git log)
- Identified improvements or issues

**Trigger:** Manual ("summarize grid-bot-v3") or scheduled (cron/task scheduler for nightly crawls).

### 4.2 Script & Tool Generation

On-demand creation of utility scripts:
- Data extraction/transformation pipelines
- Cross-repo analysis tools
- Automation scripts (backup, sync, deploy)
- Markdown document generators

### 4.3 Improvement Discovery

The model reads code and identifies:
- Dead code / unused imports
- Stale configs referencing deleted files
- Missing or outdated documentation
- Inconsistencies between repos (e.g., shared types that diverged)
- Test gaps

Output: `improvements/` directory with actionable markdown files, one per finding.

### 4.4 Tool-Calling Requirements

The model MUST reliably handle these tool types:

| Tool | Example | Priority |
|------|---------|----------|
| File read | Read any file by path | Critical |
| File write | Create/edit files | Critical |
| Shell execution | Run commands, capture output | Critical |
| Git operations | log, diff, status, blame | Critical |
| Directory listing | Recursive glob/find | Critical |
| Web fetch | Download files, read URLs | Nice-to-have |
| Structured output | JSON responses for piping | Important |

Tool-calling quality is the **primary model selection criterion**. If Qwen2.5-Coder-32B fumbles tool calls, switch to the model that doesn't, even if it's smaller.

---

## 5. Self-Tuning Autoresearch Loop

The resident AI uses Karpathy's keep-if-better pattern to improve its own effectiveness.

### 5.1 The Pattern

```
┌──────────────────────────────────────────────────┐
│  Human writes program.md (what to improve)        │
│                                                    │
│  Agent proposes edit to system prompt / tool def   │
│       ↓                                            │
│  Run benchmark tasks (fixed set, timed)            │
│       ↓                                            │
│  Measure task completion quality                   │
│       ↓                                            │
│  Better? → git commit (keep)                       │
│  Worse?  → git revert (discard)                    │
│       ↓                                            │
│  Repeat                                            │
└──────────────────────────────────────────────────┘
```

### 5.2 Editable Surface

The "train.py" equivalent — the files the autoresearch loop is allowed to modify:

| File | What it controls |
|------|-----------------|
| `config/system_prompt.md` | The resident AI's core instructions, personality, approach |
| `config/tool_definitions.json` | Tool schemas, descriptions, parameter hints |
| `config/summarization_template.md` | How the AI structures repo summaries |
| `config/improvement_rubric.md` | What counts as an "improvement" when scanning code |

Everything else is frozen during autoresearch.

### 5.3 Benchmark Tasks

The "prepare.py" equivalent — a fixed set of tasks the AI must perform, with measurable outcomes.

**Task categories:**

1. **File navigation** — "Find the function that handles belief decay in grid-bot-v3" → measure: correct file:line returned? Time taken?
2. **Summarization** — "Summarize the consensus.py module" → measure: does the summary mention key concepts? (scored by a judge prompt or keyword checklist)
3. **Script generation** — "Write a script that counts beliefs per source from the archive" → measure: does the script run? Does it produce correct output on test data?
4. **Improvement detection** — "Find issues in this deliberately broken file" → measure: did it find the planted bugs?

**Benchmark set:** `eval/tasks.json` — frozen, version-controlled, never modified by the autoresearch loop.

### 5.4 Metric

Single scalar: **weighted task completion score** (0.0 to 1.0).

```
score = 0.3 × navigation_accuracy
      + 0.3 × summarization_quality
      + 0.2 × script_correctness
      + 0.2 × improvement_detection_recall
```

Each component is averaged across its task set. Higher is better. Keep if new score > current baseline.

### 5.5 Orchestrator

**Option A: Simple keep/revert script** (`scripts/autoresearch.py`)

A minimal Python script that:

1. Reads `program.md` (human-written research direction)
2. Asks the local model to propose an edit to one of the editable files
3. Applies the edit
4. Runs the benchmark suite
5. Computes the score
6. If improved: `git commit`
7. If not: `git revert`
8. Logs result to `runs/{timestamp}.json`
9. Repeats (with configurable experiment cap and wall-clock timeout)

**Option B: DSPy prompt optimization** (more principled)

DSPy (Stanford, 28K+ GitHub stars) works with Ollama and can automatically
optimize prompts via MIPROv2/GEPA optimizers. Instead of random prompt edits
with keep/revert, DSPy uses gradient-free optimization to systematically
improve prompts based on a training set.

```python
import dspy
lm = dspy.LM('ollama_chat/qwen3-coder-next', api_base='http://localhost:11434')
dspy.configure(lm=lm)
# Define module, metric, and let MIPROv2 optimize
```

DSPy is the better long-term approach but adds complexity. Start with Option A
for proof-of-concept, migrate to DSPy once the basic loop works.

**Safety guardrails (both options):**
- Max 100 experiments per session
- 10-minute wall-clock timeout per benchmark run
- Only the 4 editable files can change (enforced by `git diff --name-only` check)
- Score floor: if score drops below 0.2, halt and alert
- Disk quota for logs

---

## 6. Setup Procedure (Home Laptop)

Run these steps after `git pull` on the home laptop.

### Phase 0: Prerequisites

```bash
# 1. Update Intel Arc GPU driver (latest from Intel)
# Download from: https://www.intel.com/content/www/us/en/download/785597/intel-arc-iris-xe-graphics-windows.html

# 2. Verify Python 3.12
python --version

# 3. Install uv (fast Python package manager)
# PowerShell: irm https://astral.sh/uv/install.ps1 | iex
# Or: winget install astral-sh.uv
```

### Phase 1: IPEX-LLM Ollama

```bash
# 1. Download IPEX-LLM Ollama Portable Zip (Windows)
# From: https://github.com/intel/ipex-llm/blob/main/docs/mddocs/Quickstart/ollama_quickstart.md

# 2. Extract to a permanent location (e.g., D:\ipex-ollama\)

# 3. Run init script
cd D:\ipex-ollama
init-ollama.bat

# 4. Configure environment
set OLLAMA_NUM_GPU=999
set SYCL_CACHE_PERSISTENT=1
set no_proxy=localhost,127.0.0.1

# 5. Start Ollama
ollama serve

# 6. Pull model (in another terminal)
# Try Qwen3-Coder-Next first:
ollama search qwen3-coder
ollama pull qwen3-coder:next    # or exact tag from search results
# If unavailable, download GGUF from HuggingFace and use custom Modelfile (see Section 3.2)
# Fallback: ollama pull qwen2.5-coder:32b-instruct-q8_0

# 7. Verify
curl http://localhost:11434/api/tags
curl http://localhost:11434/api/generate -d '{"model":"qwen3-coder-next","prompt":"Write a Python function that lists files in a directory","stream":false}'
```

### Phase 2: Agent Framework (test in order, stop when one works)

```bash
# === Tier 1: Claude Code with local Ollama (try this FIRST) ===
set ANTHROPIC_AUTH_TOKEN=ollama
set ANTHROPIC_BASE_URL=http://localhost:11434
claude
# If this works with tool calling, you're done. Skip the rest.

# === Tier 2: OpenCode (open-source Claude Code alternative) ===
# Download from: https://github.com/opencode-ai/opencode
opencode --provider ollama --model qwen3-coder-next

# === Tier 3: Aider (code-focused) ===
pip install aider-chat
aider --model ollama_chat/qwen3-coder-next

# === Tier 4: Qwen-Agent (Alibaba's framework) ===
pip install -U "qwen-agent[gui,rag,code_interpreter,mcp]"

# === Tier 5: Open Interpreter (general-purpose) ===
pip install open-interpreter
interpreter --api-base http://localhost:11434/v1 --model qwen3-coder-next
```

### Phase 3: Benchmark

```bash
cd ~/ai_autoresearch_mirofish
python scripts/benchmark.py
```

This script (to be implemented) will:
1. Capture hardware specs (CPU, GPU, RAM, execution units)
2. Measure inference speed (prompt processing t/s, generation t/s)
3. Test tool-calling reliability (10 structured output tasks)
4. Test context window stability (4K → 8K → 16K → 32K)
5. Write results to `bench/baseline_{timestamp}.json`

**Acceptance gates:**
- Generation speed ≥ 2 t/s at 8K context
- Tool-calling success rate ≥ 80% (10/10 tasks parse correctly)
- No OOM or instability at 8K context

If any gate fails, fall back to a smaller model (see Section 3.2 fallback table).

### Phase 4: First Real Task

```bash
# Using whichever agent framework worked in Phase 2, ask it to:
# "Crawl C:\Users\ColsonR\grid-bot-v3 and write a markdown architecture
#  summary to summaries/grid-bot-v3.md"
#
# This validates: file reading, directory traversal, markdown generation,
# file writing, and code comprehension — all core capabilities.
```

---

## 7. Context Window Management

Memory is the asset; bandwidth is the bottleneck. Manage context aggressively.

| Context size | KV cache (est. Q8) | Use case |
|-------------|-------------------|----------|
| 4,096 | ~2 GB | Short tool-calling tasks |
| 8,192 | ~4 GB | Standard agent conversations |
| 16,384 | ~8 GB | Multi-file code review |
| 32,768 | ~16 GB | Full repo analysis (tight — 38 GB weights + 16 GB KV = 54 GB) |

**Strategy:**
- Default to 8K context (safe margin)
- Use KV cache quantization (`--cache-type-k q8_0 --cache-type-v q4_0` in llama-server) if pushing to 16K+
- Never go beyond 32K without benchmarking first
- For large crawls, use chunked summarization (summarize files individually, then summarize the summaries)

---

## 8. Directory Structure (New)

```
ai_autoresearch_mirofish/
├── config/
│   ├── system_prompt.md          # Resident AI core instructions (autoresearch-editable)
│   ├── tool_definitions.json     # Tool schemas (autoresearch-editable)
│   ├── summarization_template.md # Summary format (autoresearch-editable)
│   ├── improvement_rubric.md     # Code review rubric (autoresearch-editable)
│   ├── model.json                # Model name, quant, context size, temperature
│   └── runtime.json              # Ollama endpoint, timeouts, concurrency
├── eval/
│   ├── tasks.json                # Frozen benchmark tasks
│   └── fixtures/                 # Test data for benchmark tasks
├── scripts/
│   ├── setup.py                  # Automated setup (driver check, model pull, framework install)
│   ├── benchmark.py              # Hardware + inference benchmarking
│   ├── autoresearch.py           # Self-tuning orchestrator loop
│   └── crawl.py                  # Filesystem crawl + summarization driver
├── summaries/                    # Generated repo summaries (gitignored)
├── improvements/                 # Generated improvement notes (gitignored)
├── bench/                        # Benchmark results (committed)
├── runs/                         # Autoresearch experiment logs (gitignored)
├── program.md                    # Human-written autoresearch instructions
├── FOUNDATION_SPEC.md            # This file
└── .gitignore
```

---

## 9. Open Questions (Resolve on First Boot)

| # | Question | How to resolve |
|---|----------|----------------|
| 1 | Exact CPU model and Arc GPU execution units? | Run `scripts/benchmark.py` — log `wmic cpu` and Intel GPU info. If <80 EUs, iGPU may be too slow. |
| 2 | Is IPEX-LLM Ollama portable zip compatible with this iGPU? | Try it. If SYCL init fails, fall back to Vulkan llama-server |
| 3 | Does Qwen3-Coder-Next GGUF exist as an Ollama tag? | `ollama search qwen3-coder`. If not, download GGUF from unsloth/Qwen3-Coder-Next-GGUF on HuggingFace and use custom Modelfile |
| 4 | Does Claude Code work with `ANTHROPIC_BASE_URL=localhost`? | Confirmed working with Ollama v0.14.0+. Test with: `set ANTHROPIC_AUTH_TOKEN=ollama` + `set ANTHROPIC_BASE_URL=http://localhost:11434` + `claude` |
| 5 | Do K-quants (Q4_K_XL) perform OK on SYCL for MoE models? | Benchmark Q4_K_XL vs Q4_0 (if available). MoE routing may change perf characteristics vs dense models. If K-quants are slow, fall back to Qwen2.5-Coder-32B Q8_0. |
| 6 | Actual inference speed at 8K context? | Benchmark. If <2 t/s, try CPU-only inference (may be competitive on efficient cores) or drop to smaller model |
| 7 | Is the home laptop admin-capable? | Check. Affects whether IPEX-LLM portable works without elevation |
| 8 | DDR5 or DDR4? | Affects bandwidth ceiling. DDR5 = better throughput; DDR4 = may need smaller model |

---

## 10. Non-Goals

- **Not a trading bot.** Does not form beliefs, execute trades, or touch Kraken.
- **Not a curriculum optimizer.** The AP Stats synthetic student approach is abandoned.
- **Not a cloud service.** Runs entirely on the home laptop. No Railway, no API billing.
- **Not a fine-tuning pipeline.** Uses off-the-shelf GGUF models. No training, no LoRA.
- **Not a replacement for Claude Code.** Claude Code (API) handles heavy reasoning tasks, complex autoresearch on grid-bot, and anything requiring frontier intelligence. The local model handles persistent, always-on, free tasks.
