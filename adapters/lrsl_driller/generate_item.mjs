/**
 * generate_item.mjs — Load a cartridge generator from lrsl-driller and
 * produce a canonical item.
 *
 * Reads JSON from stdin:
 *   { "cartridge_id": "lsrl-calculations", "mode_id": "calc-zscore", "seed": 42 }
 *
 * Writes canonical item JSON to stdout.
 *
 * Usage:
 *   echo '{"cartridge_id":"lsrl-calculations","mode_id":"calc-zscore","seed":42}' \
 *     | node adapters/lrsl_driller/generate_item.mjs
 */

import { readFileSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname  = dirname(__filename);

const NEIGHBOR_ROOT  = resolve(__dirname, '..', '..', '..');
const CARTRIDGES_DIR = resolve(NEIGHBOR_ROOT, 'lrsl-driller/cartridges');

// ────────────────────────────────────────────────────────────────
//  Seeded PRNG (mulberry32) — deterministic random for given seed
// ────────────────────────────────────────────────────────────────

function mulberry32(seed) {
  let s = seed | 0;
  return function () {
    s = (s + 0x6D2B79F5) | 0;
    let t = Math.imul(s ^ (s >>> 15), 1 | s);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// ────────────────────────────────────────────────────────────────
//  Load manifest to get cartridge metadata
// ────────────────────────────────────────────────────────────────

function loadManifest(cartridgeId) {
  const manifestPath = resolve(CARTRIDGES_DIR, cartridgeId, 'manifest.json');
  try {
    return JSON.parse(readFileSync(manifestPath, 'utf-8'));
  } catch (err) {
    process.stderr.write(`ERROR: Cannot read manifest.json for cartridge "${cartridgeId}"\n  Path: ${manifestPath}\n  ${err.message}\n`);
    process.exit(1);
  }
}

// ────────────────────────────────────────────────────────────────
//  Dynamically import the generator (ES module)
// ────────────────────────────────────────────────────────────────

async function loadGenerator(cartridgeId) {
  const genPath = resolve(CARTRIDGES_DIR, cartridgeId, 'generator.js');

  // Convert to file:// URL for dynamic import on Windows
  const fileUrl = new URL(`file:///${genPath.replace(/\\/g, '/')}`);

  try {
    const mod = await import(fileUrl.href);
    return mod;
  } catch (err) {
    process.stderr.write(`ERROR: Cannot import generator.js for cartridge "${cartridgeId}"\n  Path: ${genPath}\n  ${err.message}\n`);
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

  const { cartridge_id, mode_id, seed } = input;

  if (!cartridge_id) {
    process.stderr.write('ERROR: Missing cartridge_id in input.\n');
    process.exit(1);
  }
  if (!mode_id) {
    process.stderr.write('ERROR: Missing mode_id in input.\n');
    process.exit(1);
  }

  // Load manifest for metadata
  const manifest = loadManifest(cartridge_id);

  // Seed the PRNG and replace Math.random temporarily
  const effectiveSeed = (seed != null) ? seed : Date.now();
  const rng = mulberry32(effectiveSeed);
  const originalRandom = Math.random;
  Math.random = rng;

  try {
    // Load and call the generator
    const genModule = await loadGenerator(cartridge_id);
    const generateProblem = genModule.generateProblem || genModule.default?.generateProblem;

    if (typeof generateProblem !== 'function') {
      process.stderr.write(`ERROR: generator.js for "${cartridge_id}" does not export generateProblem()\n`);
      process.exit(1);
    }

    // The generator signature: generateProblem(modeId, context, config)
    // context comes from the cartridge's contexts.json (optional)
    let context = {};
    try {
      const ctxPath = resolve(CARTRIDGES_DIR, cartridge_id, 'contexts.json');
      const contexts = JSON.parse(readFileSync(ctxPath, 'utf-8'));
      // Pick a random context from the array
      if (Array.isArray(contexts) && contexts.length > 0) {
        const idx = Math.floor(rng() * contexts.length);
        context = contexts[idx];
      }
    } catch {
      // No contexts file — that's fine
    }

    const problem = generateProblem(mode_id, context, {});

    // Build canonical item
    const canonicalItem = {
      item_id:             `DR:${cartridge_id}:${mode_id}:${effectiveSeed}`,
      source:              'lrsl_driller',
      item_type:           classifyMode(mode_id, manifest),
      unit:                parseUnit(manifest.meta?.unit),
      lesson:              parseLesson(manifest.meta?.lesson),
      kc_tags:             [],
      prompt:              problem.scenario || '',
      choices:             extractChoices(problem),
      expected:            extractExpected(problem),
      seed:                effectiveSeed,
      difficulty_estimate: 0.5,
      _raw: {
        given:        problem.given || null,
        answers:      problem.answers || null,
        validation:   problem.validation || null,
        graphConfig:  problem.graphConfig || null,
      },
    };

    process.stdout.write(JSON.stringify(canonicalItem, null, 2) + '\n');
  } finally {
    // Restore Math.random
    Math.random = originalRandom;
  }
}

// ────────────────────────────────────────────────────────────────
//  Helpers
// ────────────────────────────────────────────────────────────────

function classifyMode(modeId, manifest) {
  // Check manifest modes for type hints
  const modes = manifest.modes || [];
  const mode = modes.find(m => m.id === modeId);
  if (mode) {
    const layout = mode.layout;
    if (layout?.inputs) {
      const hasMultipleChoice = layout.inputs.some(
        inp => inp.type === 'multiple-choice' || inp.type === 'select'
      );
      const hasNumeric = layout.inputs.some(inp => inp.type === 'number');
      if (hasMultipleChoice && !hasNumeric) return 'mcq';
      if (hasNumeric) return 'numeric';
    }
  }
  return 'numeric';
}

function parseUnit(unitStr) {
  if (!unitStr) return null;
  const m = String(unitStr).match(/(\d+)/);
  return m ? parseInt(m[1], 10) : null;
}

function parseLesson(lessonStr) {
  if (!lessonStr) return null;
  const m = String(lessonStr).match(/(\d+)/);
  return m ? parseInt(m[1], 10) : null;
}

function extractChoices(problem) {
  // Some modes have multiple-choice or select inputs
  const ctx = problem.context || {};
  const answers = problem.answers || {};

  // Look for select/multiple-choice fields
  for (const [fieldId, ansData] of Object.entries(answers)) {
    if (ansData && typeof ansData === 'object' && ansData.value) {
      // If the answer is a string like "A", "B", "positive", etc., it may be an MC
      if (typeof ansData.value === 'string' && !ansData.formula) {
        // This is likely an MC-style answer, but we don't always have choices listed
        // in the problem output. Return empty; the mode layout in manifest has options.
      }
    }
  }
  return [];
}

function extractExpected(problem) {
  const expected = {};
  const answers = problem.answers || {};
  const validation = problem.validation || {};

  // Merge answers and validation
  for (const [fieldId, data] of Object.entries(answers)) {
    if (data && typeof data === 'object' && data.value !== undefined) {
      expected[fieldId] = data.value;
    }
  }
  for (const [fieldId, data] of Object.entries(validation)) {
    if (data && typeof data === 'object' && data.expected !== undefined) {
      if (!expected[fieldId]) {
        expected[fieldId] = data.expected;
      }
    }
  }

  return expected;
}

main();
