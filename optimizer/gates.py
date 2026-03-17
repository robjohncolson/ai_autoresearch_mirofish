"""Patch quality gates — every curriculum patch must pass before acceptance.

Gate pipeline (from FOUNDATION_SPEC section 9.3):
  1. correctness_gate  — no factual errors vs AP framework
  2. readability_gate  — Flesch-Kincaid grade level 10-12
  3. length_gate       — content growth <= max_growth_pct
  4. framework_gate    — AP learning objectives still covered
  5. regression_gate   — no unit score regressions beyond threshold
"""

from __future__ import annotations

import math
import re


# ---------------------------------------------------------------------------
# Flesch-Kincaid readability (pure Python)
# ---------------------------------------------------------------------------

_VOWELS = set("aeiouyAEIOUY")

# Common silent-e and special endings that reduce syllable count
_SUB_SYLLABLE = re.compile(
    r"(cial|tia|cius|cious|giu|ion|iou|sia$|[^aeiou]ely$|[aeiou]ed$)", re.IGNORECASE
)
# Patterns that add a syllable
_ADD_SYLLABLE = re.compile(
    r"(ia|riet|dien|iu|io|ii|[aeiouym]bl$|[aeiou]{3}|^mc|ism$"
    r"|([^aeiouy])\2l$|[^l]lien|^coa[dglx].|[^gq]ua[^auieo]|dnt$"
    r"|uity$|[^aeiouy]ie(r|st|t)$)",
    re.IGNORECASE,
)


def count_syllables_word(word: str) -> int:
    """Count syllables in a single English word.

    Uses a heuristic vowel-group approach with adjustments for common
    English patterns (silent-e, compound vowels, etc.).
    """
    word = word.strip()
    if not word:
        return 0

    # Normalise
    word = word.lower().strip(".,;:!?\"'()-")
    if not word:
        return 0

    # Short words
    if len(word) <= 3:
        return 1

    # Remove trailing silent-e (but not -le endings)
    if word.endswith("e") and not word.endswith("le"):
        word = word[:-1]

    # Count vowel groups
    count = 0
    prev_vowel = False
    for ch in word:
        is_vowel = ch in _VOWELS
        if is_vowel and not prev_vowel:
            count += 1
        prev_vowel = is_vowel

    # Adjust for special patterns
    count -= len(_SUB_SYLLABLE.findall(word))
    count += len(_ADD_SYLLABLE.findall(word))

    return max(count, 1)


def count_syllables(text: str) -> int:
    """Count total syllables in a text."""
    words = _split_words(text)
    return sum(count_syllables_word(w) for w in words)


def count_words(text: str) -> int:
    """Count words in a text."""
    return len(_split_words(text))


def count_sentences(text: str) -> int:
    """Count sentences in a text.

    Uses sentence-ending punctuation (.!?) as delimiters, with handling
    for abbreviations, decimals, and ellipses.
    """
    if not text or not text.strip():
        return 0

    # Replace common abbreviations to avoid false sentence breaks
    cleaned = text
    for abbr in ("Mr.", "Mrs.", "Ms.", "Dr.", "Prof.", "Sr.", "Jr.",
                  "vs.", "etc.", "i.e.", "e.g.", "U.S.", "U.K."):
        cleaned = cleaned.replace(abbr, abbr.replace(".", ""))

    # Replace decimal numbers (e.g., "3.14") to avoid false breaks
    cleaned = re.sub(r"(\d)\.(\d)", r"\1\2", cleaned)

    # Replace ellipses
    cleaned = cleaned.replace("...", " ")

    # Count sentence terminators
    count = len(re.findall(r"[.!?]+", cleaned))
    return max(count, 1)  # at least 1 sentence if text is non-empty


def flesch_kincaid_grade(text: str) -> float:
    """Compute Flesch-Kincaid Grade Level for the given text.

    Formula: 0.39 * (words/sentences) + 11.8 * (syllables/words) - 15.59

    Returns 0.0 for empty or trivial text.
    """
    sentences = count_sentences(text)
    words = count_words(text)
    syllables = count_syllables(text)

    if words == 0 or sentences == 0:
        return 0.0

    grade = 0.39 * (words / sentences) + 11.8 * (syllables / words) - 15.59
    # Floor at 0: negative grades are meaningless
    return max(grade, 0.0)


def _split_words(text: str) -> list[str]:
    """Split text into word tokens, filtering non-word fragments."""
    raw = re.findall(r"[A-Za-z']+", text)
    return [w for w in raw if len(w) > 0]


# ---------------------------------------------------------------------------
# PatchGates
# ---------------------------------------------------------------------------

class PatchGates:
    """Quality gates that patches must pass before being accepted."""

    def __init__(self, provider_config: dict | None = None):
        self.provider_config = provider_config

    # ------------------------------------------------------------------
    # Run all gates
    # ------------------------------------------------------------------

    def check_all(
        self,
        patch: dict,
        metrics_before: dict,
        metrics_after: dict,
        framework: dict | None = None,
        guards: dict | None = None,
    ) -> dict:
        """Run all quality gates and return aggregate result.

        Args:
            patch: the patch dict (must include text content)
            metrics_before: IterationMetrics dict before the patch
            metrics_after: IterationMetrics dict after the patch
            framework: AP framework data (for framework_gate)
            guards: regression threshold overrides

        Returns:
            {"passed": bool, "results": {gate_name: {passed, reason, ...}}}
        """
        results: dict[str, dict] = {}

        results["correctness"] = self.correctness_gate(patch)
        results["readability"] = self.readability_gate(patch)
        results["length"] = self.length_gate(patch)
        results["framework"] = self.framework_gate(patch, framework or {})
        results["regression"] = self.regression_gate(
            metrics_before, metrics_after, guards or {}
        )

        all_passed = all(r["passed"] for r in results.values())
        return {"passed": all_passed, "results": results}

    # ------------------------------------------------------------------
    # Individual gates
    # ------------------------------------------------------------------

    def correctness_gate(self, patch: dict) -> dict:
        """Check whether new text contains factual errors.

        MVP implementation: basic checks against AP framework keywords.
        Future: LLM-based fact checking via provider_config.

        Returns:
            {"passed": bool, "reason": str}
        """
        new_text = self._extract_text(patch)
        if not new_text:
            return {"passed": True, "reason": "No text content to check"}

        # Basic contradiction checks — flag known statistical misstatements
        contradictions = [
            (r"\bcorrelation\b.*\bcausation\b.*\bimplies\b",
             "Appears to conflate correlation with causation"),
            (r"\bstandard deviation\b.*\bnegative\b",
             "Standard deviation cannot be negative"),
            (r"\bprobability\b.*\b(greater than 1|more than 100%)\b",
             "Probability cannot exceed 1 / 100%"),
            (r"\bvariance\b.*\bnegative\b",
             "Variance cannot be negative"),
        ]

        for pattern, message in contradictions:
            if re.search(pattern, new_text, re.IGNORECASE):
                return {"passed": False, "reason": message}

        return {"passed": True, "reason": "No basic factual errors detected"}

    def readability_gate(self, patch: dict) -> dict:
        """Check if reading level is appropriate for HS students.

        Target: Flesch-Kincaid grade level 10-12 (inclusive).
        Allows a tolerance band of 8-14 for edge cases.

        Returns:
            {"passed": bool, "reason": str, "grade_level": float}
        """
        new_text = self._extract_text(patch)
        if not new_text or count_words(new_text) < 10:
            return {
                "passed": True,
                "reason": "Text too short for meaningful readability analysis",
                "grade_level": 0.0,
            }

        grade = flesch_kincaid_grade(new_text)

        # Ideal: 10-12.  Acceptable: 8-14.
        if 8.0 <= grade <= 14.0:
            return {
                "passed": True,
                "reason": f"Grade level {grade:.1f} is within acceptable range (8-14)",
                "grade_level": round(grade, 2),
            }
        elif grade < 8.0:
            return {
                "passed": False,
                "reason": (
                    f"Grade level {grade:.1f} is too low for HS AP students "
                    f"(minimum 8.0)"
                ),
                "grade_level": round(grade, 2),
            }
        else:
            return {
                "passed": False,
                "reason": (
                    f"Grade level {grade:.1f} is too high for HS students "
                    f"(maximum 14.0)"
                ),
                "grade_level": round(grade, 2),
            }

    def length_gate(
        self,
        patch: dict,
        max_growth_pct: float = 0.30,
    ) -> dict:
        """Check if the patch doesn't bloat content excessively.

        Compares new_text length to old_text length (if available).

        Args:
            patch: must contain "new_text" or "content"; optionally "old_text"
            max_growth_pct: maximum allowed growth (0.30 = 30%)

        Returns:
            {"passed": bool, "reason": str, "growth_pct": float}
        """
        new_text = self._extract_text(patch)
        old_text = patch.get("old_text", "")

        if not old_text:
            # Can't compare without a baseline; pass by default
            return {
                "passed": True,
                "reason": "No old_text baseline provided; skipping length check",
                "growth_pct": 0.0,
            }

        old_len = len(old_text)
        new_len = len(new_text) if new_text else 0

        if old_len == 0:
            growth_pct = 0.0 if new_len == 0 else 1.0
        else:
            growth_pct = (new_len - old_len) / old_len

        passed = growth_pct <= max_growth_pct

        if passed:
            reason = f"Content growth {growth_pct:.1%} is within limit ({max_growth_pct:.0%})"
        else:
            reason = (
                f"Content grew by {growth_pct:.1%}, exceeding the "
                f"{max_growth_pct:.0%} limit ({old_len} -> {new_len} chars)"
            )

        return {
            "passed": passed,
            "reason": reason,
            "growth_pct": round(growth_pct, 4),
        }

    def framework_gate(self, patch: dict, framework: dict) -> dict:
        """Check if the patch still addresses AP learning objectives.

        Verifies that key terms from the framework's learningObjectives
        appear in the patched text.

        Args:
            patch: the patch dict
            framework: AP framework data with "learningObjectives" and
                optionally "keyTerms"

        Returns:
            {"passed": bool, "reason": str, "coverage": float}
        """
        new_text = self._extract_text(patch)
        if not new_text:
            return {
                "passed": True,
                "reason": "No text content to check against framework",
                "coverage": 1.0,
            }

        # Collect key terms from framework
        key_terms: list[str] = []

        # From keyTerms list
        terms_list = framework.get("keyTerms", [])
        if isinstance(terms_list, list):
            key_terms.extend(str(t).lower() for t in terms_list)

        # From learning objectives descriptions
        objectives = framework.get("learningObjectives", [])
        if isinstance(objectives, list):
            for obj in objectives:
                if isinstance(obj, dict):
                    desc = obj.get("description", "")
                else:
                    desc = str(obj)
                # Extract multi-word terms (2-3 word phrases)
                words = desc.lower().split()
                for w in words:
                    cleaned = re.sub(r"[^a-z]", "", w)
                    if len(cleaned) >= 4:  # skip short function words
                        key_terms.append(cleaned)
        elif isinstance(objectives, dict):
            for _oid, desc in objectives.items():
                words = str(desc).lower().split()
                for w in words:
                    cleaned = re.sub(r"[^a-z]", "", w)
                    if len(cleaned) >= 4:
                        key_terms.append(cleaned)

        if not key_terms:
            return {
                "passed": True,
                "reason": "No framework terms to check; passing by default",
                "coverage": 1.0,
            }

        # De-duplicate
        unique_terms = list(set(key_terms))

        # Check coverage
        text_lower = new_text.lower()
        found = sum(1 for term in unique_terms if term in text_lower)
        coverage = found / len(unique_terms) if unique_terms else 1.0

        # Require at least 20% of framework terms to appear
        # (patches are targeted, so they won't cover everything)
        threshold = 0.20
        passed = coverage >= threshold

        if passed:
            reason = (
                f"Framework coverage {coverage:.0%} "
                f"({found}/{len(unique_terms)} terms) meets threshold"
            )
        else:
            reason = (
                f"Framework coverage {coverage:.0%} "
                f"({found}/{len(unique_terms)} terms) is below "
                f"{threshold:.0%} threshold"
            )

        return {
            "passed": passed,
            "reason": reason,
            "coverage": round(coverage, 4),
        }

    def regression_gate(
        self,
        metrics_before: dict,
        metrics_after: dict,
        guards: dict,
    ) -> dict:
        """Check if any unit score regressed beyond a threshold.

        Args:
            metrics_before: IterationMetrics before patch application
            metrics_after: IterationMetrics after patch application
            guards: {"max_unit_regression": float, "max_mean_regression": float}
                Defaults: max_unit_regression=0.05, max_mean_regression=0.03

        Returns:
            {"passed": bool, "reason": str, "regressions": list}
        """
        max_unit_drop = guards.get("max_unit_regression", 0.05)
        max_mean_drop = guards.get("max_mean_regression", 0.03)

        regressions: list[dict] = []

        # Check overall mean score regression
        mean_before = metrics_before.get("mean_score", 0.0)
        mean_after = metrics_after.get("mean_score", 0.0)
        mean_delta = mean_before - mean_after  # positive = regression

        if mean_delta > max_mean_drop:
            regressions.append({
                "scope": "mean_score",
                "before": round(mean_before, 4),
                "after": round(mean_after, 4),
                "delta": round(-mean_delta, 4),
            })

        # Check per-unit score regressions
        units_before = metrics_before.get("unit_scores", {})
        units_after = metrics_after.get("unit_scores", {})

        for unit_key, score_before in units_before.items():
            score_after = units_after.get(unit_key, score_before)
            unit_delta = score_before - score_after  # positive = regression

            if unit_delta > max_unit_drop:
                regressions.append({
                    "scope": f"unit_{unit_key}",
                    "before": round(score_before, 4),
                    "after": round(score_after, 4),
                    "delta": round(-unit_delta, 4),
                })

        # Check MCQ accuracy regression
        mcq_before = metrics_before.get("mcq_accuracy", 0.0)
        mcq_after = metrics_after.get("mcq_accuracy", 0.0)
        mcq_delta = mcq_before - mcq_after

        if mcq_delta > max_unit_drop:
            regressions.append({
                "scope": "mcq_accuracy",
                "before": round(mcq_before, 4),
                "after": round(mcq_after, 4),
                "delta": round(-mcq_delta, 4),
            })

        passed = len(regressions) == 0

        if passed:
            reason = "No regressions detected"
        else:
            scope_list = ", ".join(r["scope"] for r in regressions)
            reason = f"Regressions detected in: {scope_list}"

        return {
            "passed": passed,
            "reason": reason,
            "regressions": regressions,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_text(patch: dict) -> str:
        """Extract the text content from a patch dict."""
        return (
            patch.get("new_text")
            or patch.get("content")
            or patch.get("new_value")
            or ""
        )
