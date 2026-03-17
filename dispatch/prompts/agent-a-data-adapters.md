# Agent A: Data Adapters

Build thin Node.js adapter modules that bridge into the existing `curriculum_render` and `lrsl-driller` repos, plus a Python orchestrator that calls them.

## Hard Constraints
- Only create/modify files under `adapters/` and `scripts/extract_items.py`
- Do NOT modify any files in the neighboring repos — read only
- All JS adapters must be ES modules (.mjs) runnable with `node --experimental-vm-modules`
- All adapters must resolve neighboring repo paths relative to the **repo root** (`C:/Users/ColsonR/ai_autoresearch_mirofish/`), not relative to the adapter file. Use `path.resolve(import.meta.dirname, '..', '..', '..', 'curriculum_render')` or equivalent to reach `C:/Users/ColsonR/curriculum_render/`. The sibling repos are at `../curriculum_render/` and `../lrsl-driller/` relative to the repo root.
- Output valid JSON to stdout so the Python orchestrator can capture it

## Neighboring Repo Locations (absolute, for reference)
- `C:/Users/ColsonR/curriculum_render/data/curriculum.js` — question bank
- `C:/Users/ColsonR/curriculum_render/data/frameworks.js` — AP framework metadata
- `C:/Users/ColsonR/curriculum_render/js/grading/frq-grading-rules.js` — FRQ rubric rules
- `C:/Users/ColsonR/curriculum_render/js/grading/grading-engine.js` — grading engine
- `C:/Users/ColsonR/lrsl-driller/cartridges/` — each cartridge has manifest.json, generator.js, grading-rules.js

Adapters should resolve these via repo-root-relative paths (e.g., `path.resolve(repoRoot, '..', 'curriculum_render', 'data', 'curriculum.js')`).

## Deliverables

### 1. `adapters/curriculum_render/extract_items.mjs`
Read `curriculum.js` and output canonical items as JSON array to stdout. Each item:
```json
{
  "item_id": "CR:U1-L2-Q01",
  "source": "curriculum_render",
  "item_type": "mcq",
  "unit": 1,
  "lesson": 2,
  "kc_tags": [],
  "prompt": "The question text...",
  "choices": [{"key": "A", "value": "..."}],
  "expected": {"answer_key": "B"},
  "seed": null,
  "difficulty_estimate": 0.5
}
```
- Parse the question ID format `U{unit}-L{lesson}-Q{number}` to extract unit/lesson
- Set `item_type` to "mcq" for `type: "multiple-choice"`, "frq" for `type: "free-response"`, "frq_multipart" if FRQ has `solution.parts` with length > 1
- For MCQ: `expected.answer_key` = the `answerKey` field
- For FRQ: `expected.rubric_rule` = best-match rule name from frq-grading-rules.js (or null if no match)
- `kc_tags` starts empty — will be filled by KC tagging script later
- `difficulty_estimate` defaults to 0.5

The curriculum.js file assigns data to a global variable. You'll need to evaluate or parse it. The simplest approach: create a minimal shim that defines `window = {}` before requiring the file, then read the exported data.

### 2. `adapters/curriculum_render/grade_mcq.mjs`
Accept JSON on stdin: `{"answer": "B", "expected": {"answer_key": "C"}}`
Output JSON to stdout: `{"score": "E" or "I", "feedback": "Correct" or "Incorrect. Expected C."}`

### 3. `adapters/curriculum_render/grade_frq.mjs`
Accept JSON on stdin:
```json
{
  "answer": "The distribution is right-skewed...",
  "ruleId": "describeDistributionShape",
  "context": {"variable": "completion time"}
}
```
Import and use the actual grading rules from the neighboring repo (resolve path from repo root: `path.resolve(repoRoot, '..', 'curriculum_render', 'js', 'grading', 'frq-grading-rules.js')`). Output JSON:
```json
{
  "score": "E",
  "feedback": "All rubric elements present.",
  "matched": ["shape", "outliers", "center"],
  "missing": []
}
```
If the grading rules file uses browser globals, create shims. The key is to reuse the actual regex patterns and scoring logic, not reimplement them.

### 4. `adapters/lrsl_driller/generate_item.mjs`
Accept JSON on stdin: `{"cartridge_id": "apstats-lsrl", "mode_id": "l01-...", "seed": 42}`
Load the cartridge's `generator.js`, call its `generateProblem()` function with the mode and a seeded random context.
Output the canonical item JSON to stdout.

### 5. `adapters/lrsl_driller/grade_answers.mjs`
Accept JSON on stdin: `{"cartridge_id": "apstats-lsrl", "field_id": "choiceAnswer", "answer": "...", "context": {...}}`
Load the cartridge's `grading-rules.js`, call `gradeField()`.
Output JSON: `{"score": "E"/"P"/"I", "feedback": "...", "correct": true/false}`

### 6. `scripts/extract_items.py`
Python script that:
1. Calls `node adapters/curriculum_render/extract_items.mjs` as a subprocess
2. Captures stdout JSON
3. Writes to `data/items/curriculum_render.json`
4. Optionally calls lrsl_driller adapters for a configurable list of cartridge IDs
5. Writes to `data/items/lrsl_driller.json`
6. Prints summary: number of items extracted per source, per unit

```python
import subprocess, json, sys
# Use subprocess.run(["node", "adapters/curriculum_render/extract_items.mjs"], capture_output=True, text=True)
```

## Testing
- Each adapter should handle missing files gracefully with a clear error message
- The Python orchestrator should validate the JSON output shape before writing
