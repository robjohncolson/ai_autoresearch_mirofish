#!/usr/bin/env node
/**
 * extract_frameworks.mjs
 *
 * Reads the AP Statistics framework data from curriculum_render/data/frameworks.js
 * and outputs a clean JSON structure to stdout.
 *
 * Usage:
 *   node data/extract_frameworks.mjs > data/frameworks.json
 *
 * The source file uses a dual-export pattern (module.exports + window).
 * We evaluate it in a sandboxed context to extract UNIT_FRAMEWORKS.
 */

import { readFileSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const __dirname = dirname(fileURLToPath(import.meta.url));
const frameworksPath = resolve(__dirname, '../../curriculum_render/data/frameworks.js');
const src = readFileSync(frameworksPath, 'utf-8');

// Create a sandbox with module/exports shims so the file's export block works
const sandbox = {
  module: { exports: {} },
  window: {}
};
sandbox.exports = sandbox.module.exports;

vm.runInNewContext(src, sandbox, { filename: frameworksPath });

// The file assigns to module.exports as an object with UNIT_FRAMEWORKS key
const UNIT_FRAMEWORKS =
  sandbox.module.exports.UNIT_FRAMEWORKS ||
  sandbox.window.UNIT_FRAMEWORKS;

if (!UNIT_FRAMEWORKS) {
  console.error('ERROR: Could not extract UNIT_FRAMEWORKS from', frameworksPath);
  process.exit(1);
}

// Transform into the target shape
const output = { units: {} };

for (const [unitNum, unitData] of Object.entries(UNIT_FRAMEWORKS)) {
  const unit = {
    title: unitData.title,
    examWeight: unitData.examWeight,
    bigIdeas: unitData.bigIdeas || [],
    lessons: {}
  };

  for (const [lessonNum, lessonData] of Object.entries(unitData.lessons)) {
    const lesson = {
      topic: lessonData.topic,
      skills: lessonData.skills || [],
      learningObjectives: (lessonData.learningObjectives || []).map(lo => ({
        id: lo.id,
        text: lo.text,
        essentialKnowledge: lo.essentialKnowledge || []
      })),
      keyConcepts: lessonData.keyConcepts || []
    };

    // Include optional fields only if present
    if (lessonData.keyFormulas && lessonData.keyFormulas.length > 0) {
      lesson.keyFormulas = lessonData.keyFormulas;
    }
    if (lessonData.commonMisconceptions && lessonData.commonMisconceptions.length > 0) {
      lesson.commonMisconceptions = lessonData.commonMisconceptions;
    }

    unit.lessons[lessonNum] = lesson;
  }

  output.units[unitNum] = unit;
}

// Write to stdout as pretty JSON
process.stdout.write(JSON.stringify(output, null, 2) + '\n');
