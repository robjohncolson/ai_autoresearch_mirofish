/**
 * grade_answers.mjs — Grade an answer using a cartridge's grading-rules.js.
 *
 * Reads JSON from stdin:
 *   {
 *     "cartridge_id": "lsrl-calculations",
 *     "field_id": "zscore",
 *     "answer": "1.5",
 *     "context": { "zscore": { "value": 1.5 }, ... }
 *   }
 *
 * Writes JSON to stdout:
 *   { "score": "E", "feedback": "Correct!", "correct": true }
 *
 * Usage:
 *   echo '{"cartridge_id":"lsrl-calculations","field_id":"zscore","answer":"1.5","context":{...}}' \
 *     | node adapters/lrsl_driller/grade_answers.mjs
 */

import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname  = dirname(__filename);

const NEIGHBOR_ROOT  = resolve(__dirname, '..', '..', '..');
const CARTRIDGES_DIR = resolve(NEIGHBOR_ROOT, 'lrsl-driller/cartridges');

// ────────────────────────────────────────────────────────────────
//  Dynamically import the grading rules (ES module)
// ────────────────────────────────────────────────────────────────

async function loadGradingRules(cartridgeId) {
  const rulesPath = resolve(CARTRIDGES_DIR, cartridgeId, 'grading-rules.js');

  // Convert to file:// URL for dynamic import on Windows
  const fileUrl = new URL(`file:///${rulesPath.replace(/\\/g, '/')}`);

  try {
    const mod = await import(fileUrl.href);
    return mod;
  } catch (err) {
    process.stderr.write(`ERROR: Cannot import grading-rules.js for cartridge "${cartridgeId}"\n  Path: ${rulesPath}\n  ${err.message}\n`);
    process.exit(1);
  }
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

  const { cartridge_id, field_id, answer, context } = input;

  if (!cartridge_id) {
    process.stderr.write('ERROR: Missing cartridge_id in input.\n');
    process.exit(1);
  }
  if (!field_id) {
    process.stderr.write('ERROR: Missing field_id in input.\n');
    process.exit(1);
  }

  // Load grading rules module
  const rulesModule = await loadGradingRules(cartridge_id);

  // The module exports gradeField(fieldId, answer, context)
  const gradeField = rulesModule.gradeField || rulesModule.default?.gradeField;

  if (typeof gradeField !== 'function') {
    // Fallback: try gradeNumeric or gradeProblem
    const gradeNumeric = rulesModule.gradeNumeric || rulesModule.default?.gradeNumeric;
    if (typeof gradeNumeric === 'function' && context) {
      // Find expected value from context
      let expected = null;
      if (context[field_id]) {
        expected = typeof context[field_id] === 'object'
          ? context[field_id].value ?? context[field_id].expected
          : context[field_id];
      }
      if (context.answers?.[field_id]) {
        const ad = context.answers[field_id];
        expected = typeof ad === 'object' ? ad.value ?? ad.expected : ad;
      }
      if (context.validation?.[field_id]) {
        const vd = context.validation[field_id];
        expected = typeof vd === 'object' ? vd.expected ?? vd.value : vd;
      }

      if (expected != null) {
        const result = gradeNumeric(answer, expected, 'standard');
        const output = {
          score:    result.score,
          feedback: result.feedback,
          correct:  result.score === 'E',
        };
        process.stdout.write(JSON.stringify(output, null, 2) + '\n');
        return;
      }
    }

    process.stderr.write(`ERROR: grading-rules.js for "${cartridge_id}" does not export gradeField()\n`);
    process.exit(1);
  }

  // Call gradeField
  const result = gradeField(field_id, answer, context || {});

  // Normalize output
  const output = {
    score:    result.score || 'I',
    feedback: result.feedback || '',
    correct:  result.score === 'E',
  };

  // Include any extra detail from the result
  if (result.details)  output.details  = result.details;
  if (result.matched)  output.matched  = result.matched;
  if (result.missing)  output.missing  = result.missing;

  process.stdout.write(JSON.stringify(output, null, 2) + '\n');
}

main();
