/**
 * extract_items.mjs — Read curriculum_render's curriculum.js and output
 * canonical item JSON to stdout.
 *
 * curriculum.js is a browser-targeted file that assigns to a bare const
 * (EMBEDDED_CURRICULUM). We evaluate it inside a VM sandbox so we never
 * need to touch the original file.
 *
 * Usage:
 *   node adapters/curriculum_render/extract_items.mjs
 */

import { readFileSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';
import vm from 'vm';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// Paths to neighboring repo files
// __dirname = .../ai_autoresearch_mirofish/adapters/curriculum_render
// Three levels up reaches the user home where curriculum_render/ lives
const NEIGHBOR_ROOT = resolve(__dirname, '..', '..', '..');
const CURRICULUM_JS = resolve(NEIGHBOR_ROOT, 'curriculum_render/data/curriculum.js');
const FRQ_RULES_JS  = resolve(NEIGHBOR_ROOT, 'curriculum_render/js/grading/frq-grading-rules.js');

// ────────────────────────────────────────────────────────────────
//  Load curriculum.js
// ────────────────────────────────────────────────────────────────

function loadCurriculum() {
  let src;
  try {
    src = readFileSync(CURRICULUM_JS, 'utf-8');
  } catch (err) {
    process.stderr.write(`ERROR: Cannot read curriculum.js at ${CURRICULUM_JS}\n  ${err.message}\n`);
    process.exit(1);
  }

  // curriculum.js declares `const EMBEDDED_CURRICULUM = [...]`
  // We wrap it so the sandbox can capture the value.
  const sandbox = {};
  const wrappedSrc = src + '\n;__result = EMBEDDED_CURRICULUM;\n';
  const context = vm.createContext({ __result: null });
  try {
    vm.runInContext(wrappedSrc, context, { filename: 'curriculum.js' });
  } catch (err) {
    process.stderr.write(`ERROR: Failed to evaluate curriculum.js\n  ${err.message}\n`);
    process.exit(1);
  }
  return context.__result;
}

// ────────────────────────────────────────────────────────────────
//  Load FRQ grading-rule names (so we can map FRQ items to rules)
// ────────────────────────────────────────────────────────────────

function loadFRQRuleNames() {
  let src;
  try {
    src = readFileSync(FRQ_RULES_JS, 'utf-8');
  } catch {
    // Not fatal — we just won't tag rubric rules
    return [];
  }

  // Extract the top-level keys of FRQGradingRules = { key: ..., key: ... }
  // They appear as un-quoted identifiers followed by a colon at the top indent level
  // inside `const FRQGradingRules = { ... }`.
  // We also load the getGradingRule function by evaluating the file in a sandbox.
  const sandbox = {
    window: {},
    console: { log() {}, warn() {}, error() {} },
    fetch: () => Promise.resolve(),
    setTimeout: () => {},
    __ruleNames: null,
    __getGradingRule: null,
  };
  const context = vm.createContext(sandbox);
  try {
    vm.runInContext(src, context, { filename: 'frq-grading-rules.js' });
    const rules = context.window.FRQGradingRules;
    const getGradingRule = context.window.getGradingRule;
    return { rules, getGradingRule, ruleNames: rules ? Object.keys(rules) : [] };
  } catch {
    return { rules: null, getGradingRule: null, ruleNames: [] };
  }
}

// ────────────────────────────────────────────────────────────────
//  Parse a question ID like "U1-L2-Q01"
// ────────────────────────────────────────────────────────────────

function parseQuestionId(id) {
  // Standard format: U1-L2-Q01
  const m = id.match(/^U(\d+)-L(\d+)-Q(\d+)$/i);
  if (m) {
    return {
      unit:   parseInt(m[1], 10),
      lesson: parseInt(m[2], 10),
      number: parseInt(m[3], 10),
    };
  }

  // Practice/exam format: U1-PC-FRQ-Q01, U2-PC-MCQ-A-Q03, U5-EX-Q01, etc.
  const m2 = id.match(/^U(\d+)-/i);
  const unit = m2 ? parseInt(m2[1], 10) : null;

  const m3 = id.match(/Q(\d+)$/i);
  const number = m3 ? parseInt(m3[1], 10) : null;

  return { unit, lesson: null, number };
}

// ────────────────────────────────────────────────────────────────
//  Determine item_type
// ────────────────────────────────────────────────────────────────

function classifyType(raw) {
  if (raw.type === 'multiple-choice') return 'mcq';
  if (raw.type === 'free-response') {
    // Check for multipart FRQ
    const parts = raw.solution?.parts;
    if (Array.isArray(parts) && parts.length > 1) return 'frq_multipart';
    return 'frq';
  }
  return raw.type || 'unknown';
}

// ────────────────────────────────────────────────────────────────
//  Build choices array for MCQ
// ────────────────────────────────────────────────────────────────

function extractChoices(raw) {
  // Choices may be in attachments.choices
  const choices = raw.attachments?.choices;
  if (!Array.isArray(choices)) return [];
  return choices.map(c => ({ key: c.key, value: c.value }));
}

// ────────────────────────────────────────────────────────────────
//  Match FRQ to a rubric rule name
// ────────────────────────────────────────────────────────────────

function matchRubricRule(raw, frqInfo) {
  if (!frqInfo || !frqInfo.getGradingRule) return null;
  try {
    // getGradingRule(questionId, partId, question) returns a rule object.
    // We'll find the first part for single-part FRQs, or use the whole question.
    const partId = raw.solution?.parts?.[0]?.partId || null;
    const ruleObj = frqInfo.getGradingRule(raw.id, partId, raw);
    if (!ruleObj) return null;

    // Find the key name in FRQGradingRules that matches this object
    const rules = frqInfo.rules;
    for (const [name, obj] of Object.entries(rules)) {
      if (obj === ruleObj) return name;
    }
    return null;
  } catch {
    return null;
  }
}

// ────────────────────────────────────────────────────────────────
//  Build canonical item
// ────────────────────────────────────────────────────────────────

function buildCanonicalItem(raw, frqInfo) {
  const { unit, lesson } = parseQuestionId(raw.id);
  const itemType = classifyType(raw);

  const item = {
    item_id:             `CR:${raw.id}`,
    source:              'curriculum_render',
    item_type:           itemType,
    unit:                unit,
    lesson:              lesson,
    kc_tags:             [],
    prompt:              raw.prompt || '',
    choices:             itemType === 'mcq' ? extractChoices(raw) : [],
    expected:            {},
    seed:                null,
    difficulty_estimate: 0.5,
  };

  if (itemType === 'mcq') {
    item.expected = { answer_key: raw.answerKey || null };
  } else {
    // FRQ — try to find a matching rubric rule
    const ruleName = matchRubricRule(raw, frqInfo);
    item.expected = { rubric_rule: ruleName };
  }

  return item;
}

// ────────────────────────────────────────────────────────────────
//  Main
// ────────────────────────────────────────────────────────────────

function main() {
  const rawItems = loadCurriculum();
  if (!Array.isArray(rawItems) || rawItems.length === 0) {
    process.stderr.write('ERROR: curriculum.js did not produce an array of items.\n');
    process.exit(1);
  }

  const frqInfo = loadFRQRuleNames();

  const canonicalItems = rawItems.map(raw => buildCanonicalItem(raw, frqInfo));

  // Output JSON to stdout
  process.stdout.write(JSON.stringify(canonicalItems, null, 2) + '\n');

  // Summary to stderr (so it doesn't pollute the JSON on stdout)
  const byType = {};
  const byUnit = {};
  for (const it of canonicalItems) {
    byType[it.item_type] = (byType[it.item_type] || 0) + 1;
    const uKey = `Unit ${it.unit}`;
    byUnit[uKey] = (byUnit[uKey] || 0) + 1;
  }
  process.stderr.write(`\nExtracted ${canonicalItems.length} items from curriculum_render\n`);
  process.stderr.write(`  By type: ${JSON.stringify(byType)}\n`);
  process.stderr.write(`  By unit: ${JSON.stringify(byUnit)}\n`);
}

main();
