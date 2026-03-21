# Local Resident AI — Project Instructions

## What this is

Setup and configuration for a local AI assistant running on Intel Arc iGPU
(~54 GB unified VRAM, 96 GB RAM). Uses Qwen2.5-Coder-32B via IPEX-LLM Ollama
with SYCL acceleration. Includes a self-tuning autoresearch loop.

See `FOUNDATION_SPEC.md` for the full spec.

## Key paths

| Path | Purpose |
|------|---------|
| `config/system_prompt.md` | Resident AI instructions (autoresearch-editable) |
| `config/tool_definitions.json` | Tool schemas (autoresearch-editable) |
| `config/model.json` | Model name, quant, context settings |
| `config/runtime.json` | Ollama endpoint, autoresearch limits |
| `eval/tasks.json` | Frozen benchmark tasks (never edit during autoresearch) |
| `program.md` | Human-written autoresearch research direction |
| `scripts/autoresearch.py` | Self-tuning orchestrator (TODO) |
| `scripts/benchmark.py` | Hardware + inference benchmarking (TODO) |
| `scripts/crawl.py` | Filesystem crawl driver (TODO) |

## Rules

- **Autoresearch editable surface:** Only these 4 files may be modified during
  autoresearch runs: `config/system_prompt.md`, `config/tool_definitions.json`,
  `config/summarization_template.md`, `config/improvement_rubric.md`.
- **Quantization:** Use legacy quants only (Q8_0, Q5_0, Q4_0) — not K-quants.
  SYCL kernels for K-quants are slower on Intel Arc.
- **Context default:** 8192 tokens. Push to 16K/32K only after benchmarking.
