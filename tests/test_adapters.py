"""Test the Node.js adapter subprocess calls."""

import pytest
import subprocess
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Skip all tests in this module if Node.js is not available
pytestmark = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="Node.js not available"
)

# Also skip if adapter scripts don't exist
_MCQ_SCRIPT = PROJECT_ROOT / "adapters" / "curriculum_render" / "grade_mcq.mjs"
_FRQ_SCRIPT = PROJECT_ROOT / "adapters" / "curriculum_render" / "grade_frq.mjs"


@pytest.mark.skipif(not _MCQ_SCRIPT.exists(), reason="grade_mcq.mjs not found")
class TestGradeMCQ:

    def test_grade_mcq_correct(self):
        input_data = json.dumps({"answer": "B", "expected": {"answer_key": "B"}})
        result = subprocess.run(
            ["node", str(_MCQ_SCRIPT)],
            input=input_data, capture_output=True, text=True, timeout=10,
            cwd=str(PROJECT_ROOT),
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["score"] == "E"

    def test_grade_mcq_incorrect(self):
        input_data = json.dumps({"answer": "A", "expected": {"answer_key": "C"}})
        result = subprocess.run(
            ["node", str(_MCQ_SCRIPT)],
            input=input_data, capture_output=True, text=True, timeout=10,
            cwd=str(PROJECT_ROOT),
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["score"] == "I"

    def test_grade_mcq_case_insensitive(self):
        input_data = json.dumps({"answer": "b", "expected": {"answer_key": "B"}})
        result = subprocess.run(
            ["node", str(_MCQ_SCRIPT)],
            input=input_data, capture_output=True, text=True, timeout=10,
            cwd=str(PROJECT_ROOT),
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        # Should be correct regardless of case
        assert output["score"] == "E"


@pytest.mark.skipif(not _FRQ_SCRIPT.exists(), reason="grade_frq.mjs not found")
class TestGradeFRQ:

    def test_grade_frq_runs(self):
        """Basic smoke test: the FRQ grader should run without crashing."""
        input_data = json.dumps({
            "answer": "The distribution is skewed right with a center around 50.",
            "ruleId": "describeDistributionShape",
            "context": {},
        })
        result = subprocess.run(
            ["node", str(_FRQ_SCRIPT)],
            input=input_data, capture_output=True, text=True, timeout=10,
            cwd=str(PROJECT_ROOT),
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert "score" in output
        assert output["score"] in ("E", "P", "I")
