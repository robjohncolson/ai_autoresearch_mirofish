/**
 * grade_frq.mjs — Grade a free-response answer using the actual rubric
 * rules from curriculum_render's frq-grading-rules.js.
 *
 * Reads JSON from stdin:
 *   {
 *     "answer": "The distribution is right-skewed...",
 *     "ruleId": "describeDistributionShape",
 *     "context": { "variable": "completion time" }
 *   }
 *
 * Writes JSON to stdout:
 *   {
 *     "score": "E",
 *     "feedback": "All rubric elements present.",
 *     "matched": ["shape", "outliers", "center"],
 *     "missing": []
 *   }
 *
 * Usage:
 *   echo '{"answer":"...","ruleId":"describeDistributionShape","context":{}}' \
 *     | node adapters/curriculum_render/grade_frq.mjs
 */

import { readFileSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';
import vm from 'vm';

const __filename = fileURLToPath(import.meta.url);
const __dirname  = dirname(__filename);

const NEIGHBOR_ROOT  = resolve(__dirname, '..', '..', '..');
const FRQ_RULES_JS   = resolve(NEIGHBOR_ROOT, 'curriculum_render/js/grading/frq-grading-rules.js');
const GRADING_ENGINE  = resolve(NEIGHBOR_ROOT, 'curriculum_render/js/grading/grading-engine.js');

// ────────────────────────────────────────────────────────────────
//  Load FRQ grading rules into a sandbox
// ────────────────────────────────────────────────────────────────

function loadFRQRules() {
  let src;
  try {
    src = readFileSync(FRQ_RULES_JS, 'utf-8');
  } catch (err) {
    process.stderr.write(`ERROR: Cannot read frq-grading-rules.js at ${FRQ_RULES_JS}\n  ${err.message}\n`);
    process.exit(1);
  }

  // The file assigns to window.FRQGradingRules and window.getGradingRule.
  // We provide a window shim so the code runs without a browser.
  const sandbox = {
    window: {},
    console: { log() {}, warn() {}, error() {} },
    fetch: () => Promise.resolve({ ok: false, json: () => ({}) }),
    setTimeout: () => 0,
    clearTimeout: () => {},
    AbortController: class { constructor() { this.signal = {}; } abort() {} },
  };
  const context = vm.createContext(sandbox);

  try {
    vm.runInContext(src, context, { filename: 'frq-grading-rules.js' });
  } catch (err) {
    process.stderr.write(`ERROR: Failed to evaluate frq-grading-rules.js\n  ${err.message}\n`);
    process.exit(1);
  }

  return {
    FRQGradingRules: context.window.FRQGradingRules,
    getGradingRule:  context.window.getGradingRule,
  };
}

// ────────────────────────────────────────────────────────────────
//  Load GradingEngine into a sandbox
// ────────────────────────────────────────────────────────────────

function loadGradingEngine() {
  let src;
  try {
    src = readFileSync(GRADING_ENGINE, 'utf-8');
  } catch {
    // Grading engine is optional — we can do regex-only grading without it
    return null;
  }

  const sandbox = {
    window: {},
    console: { log() {}, warn() {}, error() {} },
    fetch: () => Promise.resolve({ ok: false, json: () => ({}) }),
    setTimeout: () => 0,
    clearTimeout: () => {},
    AbortController: class { constructor() { this.signal = {}; } abort() {} },
    __GradingEngine: null,
  };
  const context = vm.createContext(sandbox);

  try {
    vm.runInContext(src + '\n; __GradingEngine = GradingEngine;\n', context, {
      filename: 'grading-engine.js',
    });
    return context.__GradingEngine;
  } catch {
    return null;
  }
}

// ────────────────────────────────────────────────────────────────
//  Regex-based grading (mirrors GradingEngine.gradeRegex)
//  We reimplement the core loop so we do not depend on
//  the GradingEngine class loading successfully.
// ────────────────────────────────────────────────────────────────

function gradeWithRegex(answer, rule, ctx) {
  const text = answer.toString();
  const matched = [];
  const missing = [];
  let matchedCount = 0;
  let totalRequired = 0;

  const rubric = rule.rubric || [];

  for (const item of rubric) {
    // Skip items whose context condition is not met
    if (typeof item.contextCondition === 'function') {
      try {
        if (!item.contextCondition(ctx)) continue;
      } catch { continue; }
    }

    // We count all items (required or not) that we actually test
    const isRequired = item.required !== false;
    if (isRequired) totalRequired++;

    const patterns = Array.isArray(item.patterns) ? item.patterns : (item.pattern ? [item.pattern] : []);
    let hit = false;

    for (const p of patterns) {
      const regex = (typeof p === 'string') ? new RegExp(p, 'i') : p;
      const m = regex.exec(text);
      if (m) {
        // Run optional validate()
        if (typeof item.validate === 'function') {
          try {
            hit = item.validate(m, ctx);
          } catch { hit = false; }
        } else {
          hit = true;
        }
        if (hit) break;
      }
    }

    if (hit) {
      matchedCount++;
      matched.push(item.id);
    } else if (isRequired) {
      missing.push(item.id);
    }
  }

  // Determine score using rule.scoring thresholds
  const scoring = rule.scoring || {
    E: { minRequired: totalRequired },
    P: { minRequired: Math.ceil(totalRequired * 0.5) },
    I: { minRequired: 0 },
  };

  let score;
  if (matchedCount >= (scoring.E?.minRequired ?? totalRequired)) {
    score = 'E';
  } else if (matchedCount >= (scoring.P?.minRequired ?? Math.ceil(totalRequired * 0.5))) {
    score = 'P';
  } else {
    score = 'I';
  }

  // Check forbidden patterns
  const forbidden = rule.forbidden || [];
  for (const word of forbidden) {
    const pat = (typeof word === 'string') ? new RegExp(word, 'i') : word;
    if (pat.test(text)) {
      score = 'I';
      break;
    }
  }

  // Build feedback
  let feedback;
  if (score === 'E') {
    feedback = 'All rubric elements present.';
  } else if (score === 'P') {
    feedback = `Partial credit. Missing: ${missing.join(', ')}.`;
  } else {
    feedback = `Incorrect. Missing: ${missing.join(', ')}.`;
  }

  return { score, feedback, matched, missing };
}

// ────────────────────────────────────────────────────────────────
//  Main
// ────────────────────────────────────────────────────────────────

async function main() {
  // Read stdin
  const chunks = [];
  for await (const chunk of process.stdin) {
    chunks.push(chunk);
  }
  const inputStr = Buffer.concat(chunks).toString('utf-8').trim();

  if (!inputStr) {
    process.stderr.write('ERROR: No input provided on stdin.\n');
    process.exit(1);
  }

  let input;
  try {
    input = JSON.parse(inputStr);
  } catch (err) {
    process.stderr.write(`ERROR: Invalid JSON on stdin: ${err.message}\n`);
    process.exit(1);
  }

  const { answer, ruleId, context: ctx } = input;

  if (!answer) {
    const result = { score: 'I', feedback: 'No answer provided.', matched: [], missing: [] };
    process.stdout.write(JSON.stringify(result, null, 2) + '\n');
    return;
  }

  if (!ruleId) {
    process.stderr.write('ERROR: Missing ruleId in input.\n');
    process.exit(1);
  }

  // Load rules
  const { FRQGradingRules } = loadFRQRules();
  if (!FRQGradingRules) {
    process.stderr.write('ERROR: FRQGradingRules not found after evaluating frq-grading-rules.js\n');
    process.exit(1);
  }

  const rule = FRQGradingRules[ruleId];
  if (!rule) {
    process.stderr.write(`ERROR: Unknown ruleId "${ruleId}". Available: ${Object.keys(FRQGradingRules).join(', ')}\n`);
    process.exit(1);
  }

  // Grade using regex patterns (we skip AI grading — this is offline batch mode)
  const result = gradeWithRegex(answer, rule, ctx || {});

  process.stdout.write(JSON.stringify(result, null, 2) + '\n');
}

main();
