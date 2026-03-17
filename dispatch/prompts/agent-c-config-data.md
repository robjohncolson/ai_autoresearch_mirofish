# Agent C: Configuration & Data Pipeline

Create all configuration files and extract framework data from neighboring repos.

## Hard Constraints
- Only create/modify files under `config/` and `data/`
- Config files are valid JSON (no comments — JSON does not support comments). Use descriptive field names and a top-level `"description"` string field instead of inline comments.
- Data files are extracted from neighboring repos (read-only access)
- All paths in config must be relative to repo root

## Deliverables

### 1. `config/personas.json`
Define the student persona distribution matching the spec:

```json
{
  "description": "Student persona definitions calibrated to AP Statistics score distribution",
  "default_cohort_size": 100,
  "personas": [
    {
      "persona_id": "tier1_001",
      "ability_tier": 1,
      "kc_acquisition_rate": 0.05,
      "carelessness": 0.10,
      "guess_strategy": "random",
      "misconception_persistence": 0.95,
      "reading_comprehension": 0.60,
      "working_memory_slots": 3
    }
  ],
  "tier_distribution": {
    "1": {"target_ap_score": 1, "population_pct": 0.15, "count": 15, "acquisition_rate": 0.05, "carelessness": 0.10},
    "2": {"target_ap_score": 2, "population_pct": 0.20, "count": 20, "acquisition_rate": 0.10, "carelessness": 0.08},
    "3": {"target_ap_score": 3, "population_pct": 0.25, "count": 25, "acquisition_rate": 0.15, "carelessness": 0.06},
    "4": {"target_ap_score": 4, "population_pct": 0.25, "count": 25, "acquisition_rate": 0.22, "carelessness": 0.04},
    "5": {"target_ap_score": 5, "population_pct": 0.15, "count": 15, "acquisition_rate": 0.30, "carelessness": 0.02}
  }
}
```

Generate all 100 persona entries. For each tier, create the specified count with:
- `persona_id`: `"tier{N}_{index:03d}"` (e.g., "tier1_001" through "tier1_015")
- Vary `guess_strategy` across personas: tier 1-2 mostly "random", tier 3 mix, tier 4-5 mostly "partial_knowledge"
- Vary `misconception_persistence`: tier 1 = 0.90-0.95, tier 5 = 0.50-0.60
- Vary `reading_comprehension`: tier 1 = 0.60-0.70, tier 5 = 0.95-1.0
- Vary `working_memory_slots`: tier 1 = 3-4, tier 5 = 6-7
- Use deterministic variation (spread evenly within tier ranges, not random)

### 2. `config/provider.json`
```json
{
  "description": "LLM endpoint configuration for student simulation and optimization",
  "student": {
    "provider": "ollama",
    "endpoint": "http://localhost:11434",
    "model": "qwen3:8b",
    "options": {
      "temperature": 0.8,
      "num_predict_mcq": 5,
      "num_predict_frq": 200
    },
    "think": false,
    "max_concurrent_requests": 5,
    "timeout_seconds": 60
  },
  "optimizer": {
    "provider": "anthropic",
    "model": "claude-sonnet-4-6",
    "api_key_env": "ANTHROPIC_API_KEY",
    "max_tokens": 4096,
    "temperature": 0.3
  },
  "grading_fallback": {
    "provider": "ollama",
    "endpoint": "http://localhost:11434",
    "model": "qwen3:8b",
    "think": false
  }
}
```

### 3. `config/experiment.json`
```json
{
  "experiment_id": "apstats-phase1-mvp",
  "description": "Phase 1 MVP: 10 students, Unit 1, single iteration",
  "branch_prefix": "autoresearch",
  "current_unit": 1,
  "n_students": 10,
  "eval_set": "unit_1_dev_v1",
  "max_iterations": 50,
  "holdout_interval": 10,
  "convergence": {
    "min_iterations": 5,
    "no_improvement_streak": 5,
    "min_mean_score": null
  },
  "inter_unit_gap_hours": 336,
  "scoring_weights": {
    "E": 3,
    "P": 2,
    "I": 1
  },
  "improvement_guards": {
    "max_unit_regression": 0.1,
    "max_holdout_divergence": 0.05
  }
}
```

### 4. `data/frameworks.json`
Extract from `../../curriculum_render/data/frameworks.js`. This file exports AP framework data.

Read the JS file, parse out the framework data structure. Output a clean JSON file with this shape:
```json
{
  "units": {
    "1": {
      "title": "Exploring One-Variable Data",
      "examWeight": "15-23%",
      "lessons": {
        "1": {
          "topic": "Introducing Statistics...",
          "learningObjectives": [
            {"id": "VAR-1.A", "text": "Identify questions..."}
          ],
          "keyConcepts": ["Data analysis requires context..."]
        }
      }
    }
  }
}
```

Write a small Node.js helper script `data/extract_frameworks.mjs` that reads the JS file and outputs JSON to stdout, then call it and save the result. Use the same shim approach as the adapters (define `window = {}` or whatever global the file assigns to).

### 5. `data/kc_tags.json`
Extract the complete KC vocabulary from frameworks.json:
```json
{
  "description": "Knowledge Component tag vocabulary from AP Statistics framework",
  "tags": [
    {"id": "VAR-1.A", "unit": 1, "lesson": 1, "text": "Identify questions to be answered..."},
    {"id": "VAR-1.B", "unit": 1, "lesson": 2, "text": "..."}
  ],
  "skills": [
    {"id": "1.A", "text": "Identify the question to be answered..."},
    {"id": "2.A", "text": "Describe patterns, trends, associations..."}
  ]
}
```

This can be derived programmatically from the frameworks.json output.

### 6. `data/items/` directory
Create empty placeholder files:
- `data/items/.gitkeep`

These will be populated by the extract_items.py script (Agent A).

## File Structure
```
config/
├── personas.json
├── provider.json
└── experiment.json
data/
├── frameworks.json
├── kc_tags.json
├── extract_frameworks.mjs
└── items/
    └── .gitkeep
```
