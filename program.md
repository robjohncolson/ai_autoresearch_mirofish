# Program — Resident AI Self-Tuning

## Goal

Improve the resident AI's ability to navigate filesystems, summarize codebases,
and identify actionable improvements in code repositories.

## Current focus

Tune `config/system_prompt.md` to maximize tool-calling success rate and
summarization quality on the benchmark tasks in `eval/tasks.json`.

## Constraints

- Only modify files in `config/` (system_prompt.md, tool_definitions.json,
  summarization_template.md, improvement_rubric.md)
- Do not modify eval tasks or fixtures
- Keep changes small — one idea per iteration
- Do not add capabilities the model can't reliably execute at 3-4 t/s
- Prioritize reliability over cleverness

## Research directions to explore

1. Does giving the model explicit step-by-step navigation instructions improve
   file-finding accuracy?
2. Does a structured summarization template (with mandatory sections) produce
   better summaries than freeform instructions?
3. Does specifying output format (JSON vs markdown) in tool definitions improve
   structured output reliability?
4. Does limiting context per file (first 100 lines only) speed up crawls without
   hurting summary quality?
