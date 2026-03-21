# Continuation Prompt — ai_autoresearch_mirofish

**Session date:** 2026-03-21
**Last commit:** `bbe1acc` on `master` (+ amendment coming with this file)
**Reason for handoff:** Moving to home laptop (96 GB RAM, Intel Arc iGPU) for actual setup

---

## What this project IS

A **local resident AI** — a persistent, always-on coding assistant running
entirely on the home laptop via a local LLM. It navigates the filesystem,
summarizes repos, writes scripts, identifies improvements, and tunes its own
prompts via Karpathy's autoresearch pattern. Zero API cost.

**This is NOT** the old AP Stats synthetic student project (that code was
deleted; recoverable from git at commit `67b0121`).

---

## What to do NOW

### Step 1: Hardware check (2 minutes)

```bash
# Document your hardware — we need to know EU count and RAM type
wmic cpu get Name,NumberOfCores,NumberOfLogicalProcessors
wmic path win32_videocontroller get Name,AdapterRAM,DriverVersion
wmic memorychip get Capacity,Speed,MemoryType
```

If the Arc iGPU has **fewer than 80 execution units**, inference will be
very slow. This changes the model choice (may need smaller model or CPU-only).

### Step 2: Install IPEX-LLM Ollama (10-15 minutes)

1. Update Intel Arc GPU driver: https://www.intel.com/content/www/us/en/download/785597/intel-arc-iris-xe-graphics-windows.html
2. Download IPEX-LLM Ollama Portable Zip (Windows): https://github.com/intel/ipex-llm/blob/main/docs/mddocs/Quickstart/ollama_quickstart.md
3. Extract to a permanent location (e.g., `D:\ipex-ollama\`)
4. Run:
   ```bash
   cd D:\ipex-ollama
   init-ollama.bat

   # In a new terminal:
   set OLLAMA_NUM_GPU=999
   set SYCL_CACHE_PERSISTENT=1
   set no_proxy=localhost,127.0.0.1
   ollama serve
   ```
5. **First SYCL load takes several minutes** (kernel compilation). Be patient.

### Step 3: Pull the model (5-30 minutes depending on download speed)

**Primary model: Qwen3-Coder-Next** (80B MoE, only 3B active per token)

```bash
# Check what's available
ollama search qwen3-coder

# Pull the model (exact tag may vary)
ollama pull qwen3-coder:next

# If not available as Ollama tag, download GGUF manually:
# https://huggingface.co/unsloth/Qwen3-Coder-Next-GGUF
# Then create a Modelfile:
#   FROM ./Qwen3-Coder-Next-Q4_K_XL.gguf
#   PARAMETER num_ctx 8192
# ollama create qwen3-coder-next -f Modelfile
```

**Fallback if Qwen3-Coder-Next has issues:**
```bash
ollama pull qwen2.5-coder:32b-instruct-q8_0
```

### Step 4: Verify inference works (2 minutes)

```bash
curl http://localhost:11434/api/tags
curl http://localhost:11434/api/generate -d '{"model":"qwen3-coder-next","prompt":"Write a Python function that recursively lists all .py files in a directory tree","stream":false}'
```

Note the response time. If it took >60 seconds for a short response, you may
need a smaller model.

### Step 5: Test Claude Code with local Ollama (THE BIG TEST)

```bash
set ANTHROPIC_AUTH_TOKEN=ollama
set ANTHROPIC_BASE_URL=http://localhost:11434
claude
```

This connects Claude Code's full agent framework (file editing, shell access,
git ops, tool calling) to your local model. **If this works, you're done with
framework selection.**

Test with: "Read the FOUNDATION_SPEC.md in this repo and summarize it."

If it fails or tool-calling is unreliable, try the fallback frameworks in order:
1. OpenCode: https://github.com/opencode-ai/opencode
2. Aider: `pip install aider-chat && aider --model ollama_chat/qwen3-coder-next`
3. Open Interpreter: `pip install open-interpreter && interpreter --api-base http://localhost:11434/v1`

### Step 6: First real task

Ask the resident AI (whichever framework worked) to:
> "Crawl C:\Users\ColsonR\grid-bot-v3 and write a markdown architecture
> summary to summaries/grid-bot-v3.md using the template in
> config/summarization_template.md"

This validates all core capabilities at once.

---

## What was done in this session (2026-03-21)

1. **Pivoted the project** from AP Stats synthetic student simulation to local resident AI
2. **Deleted all old code** (adapters, simulator, optimizer, loop, tests, eval sets, dispatch)
3. **Wrote FOUNDATION_SPEC.md** — full spec covering hardware, model, runtime, framework, autoresearch
4. **Created config files** — system_prompt.md, tool_definitions.json, summarization_template.md, improvement_rubric.md, model.json, runtime.json
5. **Created program.md** — autoresearch instructions for self-tuning
6. **Updated spec with research findings** — Qwen3-Coder-Next as primary model (80B MoE, 3B active), Claude Code + local Ollama as Tier 1 framework, DSPy for principled prompt optimization

---

## Key decisions made

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Primary model | Qwen3-Coder-Next (80B MoE, 3B active) | Best agentic coding quality per VRAM; only 3B active = fast inference |
| Fallback model | Qwen2.5-Coder-32B Q8_0 | Proven stable, battle-tested |
| Runtime | IPEX-LLM Ollama (SYCL) | Intel-optimized, portable zip, familiar Ollama UX |
| Agent framework | Claude Code via Ollama Anthropic API | Confirmed working Ollama v0.14.0+; same UX you already know |
| Quantization | Try Q4_K_XL first; benchmark vs Q4_0 | K-quants are slower on SYCL for dense models, but MoE may differ |
| Autoresearch | Simple keep/revert loop first; DSPy later | Start simple, add sophistication once basics work |
| Grid-bot tuning | Separate effort, Claude Code API | Frontier reasoning needed for trading hypothesis generation |

---

## Scripts still TODO (implement on home laptop)

| Script | Purpose | Priority |
|--------|---------|----------|
| `scripts/benchmark.py` | Capture hardware specs + inference speed + tool-calling reliability | P0 — do first |
| `scripts/crawl.py` | Filesystem crawl + summarization using the agent | P1 |
| `scripts/autoresearch.py` | Self-tuning orchestrator (Karpathy keep/revert loop) | P2 |
| `scripts/setup.py` | Automated setup (driver check, model pull, framework install) | P3 — nice to have |

---

## Key paths

| Path | Purpose |
|------|---------|
| `FOUNDATION_SPEC.md` | Full spec — read this first |
| `config/model.json` | Model selection and acceptance gates |
| `config/runtime.json` | Ollama endpoint, autoresearch limits, crawl targets |
| `config/system_prompt.md` | Resident AI instructions (autoresearch-editable) |
| `config/tool_definitions.json` | Tool schemas (autoresearch-editable) |
| `config/summarization_template.md` | Summary format (autoresearch-editable) |
| `config/improvement_rubric.md` | Code review rubric (autoresearch-editable) |
| `program.md` | Human-written autoresearch direction |

---

## Environment

- **Python:** 3.12
- **Node:** v22.19.0
- **Ollama endpoint:** http://localhost:11434
- **Primary model:** Qwen3-Coder-Next (download on home laptop)
- **Fallback model:** Qwen2.5-Coder-32B Q8_0
- **Agent framework:** Claude Code with `ANTHROPIC_BASE_URL=http://localhost:11434`

---

## If something goes wrong

| Problem | Fix |
|---------|-----|
| SYCL init fails | Fall back to Vulkan llama-server (download from llama.cpp releases) |
| Model OOM at 8K context | Drop to Q4_0, reduce context to 4K, or try smaller model |
| Claude Code doesn't connect to Ollama | Check Ollama version ≥ 0.14.0; try `ANTHROPIC_AUTH_TOKEN=ollama` |
| Tool calling unreliable | Switch to Aider or Open Interpreter; some frameworks handle tool parsing better |
| <2 t/s generation speed | Try CPU-only inference (may be competitive on efficient cores); or use smaller model |
| iGPU has <80 EUs | Stick with Qwen2.5-Coder-32B Q5_0 (~22 GB) or Qwen3-Coder-30B-A3B |
