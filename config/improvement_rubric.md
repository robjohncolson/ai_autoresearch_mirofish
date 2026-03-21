# Improvement Rubric

When scanning code for improvements, categorize findings as follows:

## Categories

### Bug (severity: high)
Code that will produce incorrect results under normal conditions.
Must cite: file, line, expected vs actual behavior.

### Dead Code (severity: medium)
Functions, imports, or variables that are never referenced.
Must cite: file, line, the unused symbol.

### Missing Documentation (severity: low)
Public functions or modules with no docstring or README.
Must cite: file, function/class name.

### Stale Config (severity: medium)
Config values referencing files, endpoints, or features that no longer exist.
Must cite: config file, the stale key, what it references.

### Inconsistency (severity: medium)
Same concept implemented differently in two places (diverged types, naming, patterns).
Must cite: both locations.

### Test Gap (severity: low)
Public functions with no test coverage.
Must cite: untested function, suggested test.

## Output Format

Each finding should be a markdown section with:
- **Category** and **severity**
- **Location** (file:line)
- **Description** (1-2 sentences)
- **Suggested fix** (1-2 sentences)
