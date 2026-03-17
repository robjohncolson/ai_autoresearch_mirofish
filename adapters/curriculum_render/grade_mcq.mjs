/**
 * grade_mcq.mjs — Grade a multiple-choice answer.
 *
 * Reads JSON from stdin:
 *   { "answer": "B", "expected": { "answer_key": "C" } }
 *
 * Writes JSON to stdout:
 *   { "score": "E" or "I", "feedback": "Correct" or "Incorrect. Expected C." }
 *
 * Usage:
 *   echo '{"answer":"B","expected":{"answer_key":"B"}}' | node adapters/curriculum_render/grade_mcq.mjs
 */

async function main() {
  // Read all of stdin
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

  const { answer, expected } = input;

  if (!expected || !expected.answer_key) {
    process.stderr.write('ERROR: Missing expected.answer_key in input.\n');
    process.exit(1);
  }

  const studentAnswer  = (answer || '').toString().trim().toUpperCase();
  const correctAnswer  = expected.answer_key.toString().trim().toUpperCase();

  const correct = studentAnswer === correctAnswer;

  const result = {
    score:    correct ? 'E' : 'I',
    feedback: correct ? 'Correct' : `Incorrect. Expected ${correctAnswer}.`,
  };

  process.stdout.write(JSON.stringify(result, null, 2) + '\n');
}

main();
