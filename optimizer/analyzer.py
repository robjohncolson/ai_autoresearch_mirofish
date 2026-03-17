"""Failure pattern analysis and source classification for curriculum optimization.

This is the most critical optimizer module: the quality of failure analysis
determines the quality of all downstream improvements.
"""

from __future__ import annotations

import json
import os
import re
import ssl
import urllib.request
from collections import defaultdict
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Internal LLM helper
# ---------------------------------------------------------------------------

def _build_ssl_context() -> ssl.SSLContext:
    """Permissive SSL context for urllib calls (avoids cert issues on Windows)."""
    ctx = ssl.create_default_context()
    # Fall back to unverified if default certs unavailable
    try:
        ctx.load_default_certs()
    except Exception:
        ctx = ssl._create_unverified_context()
    return ctx


def _call_llm(config: dict, messages: list[dict]) -> str:
    """Send a chat completion request to a configured LLM provider.

    Supports:
      - Anthropic Messages API  (provider == "anthropic")
      - OpenAI-compatible /v1/chat/completions  (everything else)

    Returns the assistant text on success, or an error string prefixed with
    "ERROR:" on failure.
    """
    api_key_env = config.get("api_key_env", "")
    api_key = os.environ.get(api_key_env, "")
    model = config.get("model", "")
    provider = config.get("provider", "openai")

    if not api_key:
        return f"ERROR: environment variable {api_key_env!r} is not set"

    try:
        if provider == "anthropic":
            return _call_anthropic(api_key, model, messages)
        else:
            endpoint = config.get("endpoint", "https://api.openai.com")
            return _call_openai_compat(endpoint, api_key, model, messages)
    except Exception as exc:
        return f"ERROR: LLM call failed — {exc}"


def _call_anthropic(api_key: str, model: str, messages: list[dict]) -> str:
    """POST to Anthropic Messages API."""
    url = "https://api.anthropic.com/v1/messages"

    # Anthropic requires a separate `system` field; pull it from messages if
    # the first message has role=="system".
    system_text = ""
    chat_messages = []
    for msg in messages:
        if msg["role"] == "system":
            system_text = msg["content"]
        else:
            chat_messages.append({"role": msg["role"], "content": msg["content"]})

    body: dict = {
        "model": model,
        "max_tokens": 4096,
        "messages": chat_messages,
    }
    if system_text:
        body["system"] = system_text

    data = json.dumps(body).encode()
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
    )
    ctx = _build_ssl_context()
    with urllib.request.urlopen(req, context=ctx, timeout=120) as resp:
        result = json.loads(resp.read().decode())

    # Extract text from content blocks
    content_blocks = result.get("content", [])
    texts = [b["text"] for b in content_blocks if b.get("type") == "text"]
    return "\n".join(texts)


def _call_openai_compat(
    endpoint: str,
    api_key: str,
    model: str,
    messages: list[dict],
) -> str:
    """POST to an OpenAI-compatible /v1/chat/completions endpoint."""
    url = f"{endpoint.rstrip('/')}/v1/chat/completions"
    body = {
        "model": model,
        "messages": [{"role": m["role"], "content": m["content"]} for m in messages],
        "max_tokens": 4096,
        "temperature": 0.3,
    }
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    ctx = _build_ssl_context()
    with urllib.request.urlopen(req, context=ctx, timeout=120) as resp:
        result = json.loads(resp.read().decode())

    choices = result.get("choices", [])
    if choices:
        return choices[0].get("message", {}).get("content", "")
    return "ERROR: empty choices in response"


# ---------------------------------------------------------------------------
# FailureAnalyzer
# ---------------------------------------------------------------------------

class FailureAnalyzer:
    """Analyze grading results to identify pedagogical root causes."""

    def __init__(self, provider_config: dict):
        """
        Args:
            provider_config: from config/provider.json["optimizer"], e.g.
                {"provider": "anthropic", "model": "claude-sonnet-4-6",
                 "api_key_env": "ANTHROPIC_API_KEY"}
        """
        self.config = provider_config

    # ------------------------------------------------------------------
    # cluster_failures  (pure computation, no LLM)
    # ------------------------------------------------------------------

    def cluster_failures(
        self,
        grades: list[dict],
        metrics: dict,
    ) -> list[dict]:
        """Group failures by KC, compute error rates, identify top problem areas.

        Args:
            grades: list of grade dicts with keys
                {student_id, item_id, score, kc_tags, unit}
            metrics: IterationMetrics as a dict (mean_score, kc_mastery, etc.)

        Returns:
            Sorted list (worst first) of::

                {"kc_id": str,
                 "error_rate": float,
                 "n_errors": int,
                 "n_total": int,
                 "common_wrong_answers": list,
                 "unit": int | None}
        """
        kc_totals: dict[str, int] = defaultdict(int)
        kc_errors: dict[str, int] = defaultdict(int)
        kc_units: dict[str, int | None] = {}
        # Track wrong-answer items per KC for pattern detection
        kc_wrong_items: dict[str, list[str]] = defaultdict(list)

        for grade in grades:
            kc_tags = grade.get("kc_tags") or []
            score = grade.get("score", "")
            item_id = grade.get("item_id", "")
            unit = grade.get("unit")

            for kc in kc_tags:
                kc_totals[kc] += 1
                if kc not in kc_units and unit is not None:
                    kc_units[kc] = unit
                if score == "I":
                    kc_errors[kc] += 1
                    kc_wrong_items[kc].append(item_id)

        clusters: list[dict] = []
        for kc in kc_totals:
            total = kc_totals[kc]
            errors = kc_errors.get(kc, 0)
            error_rate = errors / total if total > 0 else 0.0

            # Compute most common wrong-answer items (top 5)
            wrong_items = kc_wrong_items.get(kc, [])
            item_counts: dict[str, int] = defaultdict(int)
            for item in wrong_items:
                item_counts[item] += 1
            common_wrong = sorted(item_counts.keys(), key=lambda k: item_counts[k], reverse=True)[:5]

            clusters.append({
                "kc_id": kc,
                "error_rate": round(error_rate, 4),
                "n_errors": errors,
                "n_total": total,
                "common_wrong_answers": common_wrong,
                "unit": kc_units.get(kc),
            })

        # Sort by error_rate descending, then by n_errors descending
        clusters.sort(key=lambda c: (-c["error_rate"], -c["n_errors"]))
        return clusters

    # ------------------------------------------------------------------
    # classify_failure_sources  (pure computation)
    # ------------------------------------------------------------------

    def classify_failure_sources(
        self,
        failure_clusters: list[dict],
        student_memories: list[dict],
        current_unit: int,
    ) -> list[dict]:
        """Classify the root cause for each failure cluster.

        Source categories:
          - "new_material":       KC belongs to current unit, strength is low
          - "prerequisite_decay": KC belongs to a prior unit, strength has decayed
          - "misconception":      KC has an active error_mode in student memories
          - "question_wording":   high error rate even among strong students (tier 4-5)

        Args:
            failure_clusters: output from cluster_failures()
            student_memories: list of snapshot dicts, each with at least
                {"student_id", "tier", "kc_states": {kc_id: {"strength": float,
                 "error_mode": str|None, "unit_learned": int}}}
            current_unit: the unit being tested

        Returns:
            Sorted list (highest priority first) of::

                {"kc_id": str, "source": str, "evidence": str, "priority": float}
        """
        # Pre-index student memories by KC
        # kc -> list of (tier, strength, error_mode)
        kc_student_data: dict[str, list[tuple]] = defaultdict(list)
        for mem in student_memories:
            tier = mem.get("tier", 3)
            kc_states = mem.get("kc_states", {})
            for kc_id, state in kc_states.items():
                strength = state.get("strength", 0.0) if isinstance(state, dict) else 0.0
                error_mode = state.get("error_mode") if isinstance(state, dict) else None
                unit_learned = state.get("unit_learned", current_unit) if isinstance(state, dict) else current_unit
                kc_student_data[kc_id].append((tier, strength, error_mode, unit_learned))

        classifications: list[dict] = []

        for cluster in failure_clusters:
            kc_id = cluster["kc_id"]
            error_rate = cluster["error_rate"]
            cluster_unit = cluster.get("unit") or current_unit

            student_entries = kc_student_data.get(kc_id, [])

            # Compute averages
            avg_strength = 0.0
            has_misconception = False
            misconception_mode = None
            high_tier_error_count = 0
            high_tier_total = 0

            if student_entries:
                strengths = [s[1] for s in student_entries]
                avg_strength = sum(strengths) / len(strengths)

                for tier, strength, error_mode, unit_learned in student_entries:
                    if error_mode:
                        has_misconception = True
                        misconception_mode = error_mode
                    if tier >= 4:
                        high_tier_total += 1
                        if strength < 0.5:
                            high_tier_error_count += 1

            # Classification logic (order matters: most specific first)

            # 1) Question wording: strong students (tier 4-5) also fail
            if high_tier_total >= 2 and error_rate > 0.3:
                high_tier_fail_rate = high_tier_error_count / high_tier_total if high_tier_total else 0
                if high_tier_fail_rate > 0.3:
                    classifications.append({
                        "kc_id": kc_id,
                        "source": "question_wording",
                        "evidence": (
                            f"Tier 4-5 students fail at {high_tier_fail_rate:.0%} "
                            f"({high_tier_error_count}/{high_tier_total}); "
                            f"overall error rate {error_rate:.0%}"
                        ),
                        "priority": error_rate * 1.2,  # boost priority for wording issues
                    })
                    continue

            # 2) Misconception: active error_mode exists
            if has_misconception:
                classifications.append({
                    "kc_id": kc_id,
                    "source": "misconception",
                    "evidence": (
                        f"Active error mode '{misconception_mode}' detected; "
                        f"avg strength {avg_strength:.2f}"
                    ),
                    "priority": error_rate * 1.1,
                })
                continue

            # 3) Prerequisite decay: KC is from a prior unit and strength decayed
            if cluster_unit < current_unit and avg_strength < 0.6:
                classifications.append({
                    "kc_id": kc_id,
                    "source": "prerequisite_decay",
                    "evidence": (
                        f"KC from unit {cluster_unit} (current is {current_unit}); "
                        f"avg strength decayed to {avg_strength:.2f}"
                    ),
                    "priority": error_rate * 0.9,
                })
                continue

            # 4) New material: KC belongs to current unit, strength is low
            classifications.append({
                "kc_id": kc_id,
                "source": "new_material",
                "evidence": (
                    f"KC in unit {cluster_unit} (current unit {current_unit}); "
                    f"avg strength {avg_strength:.2f}, error rate {error_rate:.0%}"
                ),
                "priority": error_rate,
            })

        # Sort by priority descending
        classifications.sort(key=lambda c: -c["priority"])
        return classifications

    # ------------------------------------------------------------------
    # analyze_with_llm  (calls external LLM)
    # ------------------------------------------------------------------

    def analyze_with_llm(
        self,
        failure_clusters: list[dict],
        source_classifications: list[dict],
        curriculum_text: dict,
        framework_context: dict,
    ) -> list[dict]:
        """Call the optimizer LLM to propose concrete improvement patches.

        Builds the analysis prompt from FOUNDATION_SPEC section 8.1, sends it
        to the configured LLM provider, and parses the JSON response.

        Args:
            failure_clusters: from cluster_failures()
            source_classifications: from classify_failure_sources()
            curriculum_text: {kc_id: exposition_text} for failing KCs
            framework_context: AP framework data (learning objectives, etc.)

        Returns:
            List of improvement dicts, each containing::

                {"target": "worksheet"|"driller_cartridge"|"blooket",
                 "unit": int, "lesson": int, "kc_id": str,
                 "source": str, "improvement": str, "patch": dict,
                 "priority": float}

            Returns an empty list if the LLM call fails.
        """
        prompt = self._build_analysis_prompt(
            failure_clusters,
            source_classifications,
            curriculum_text,
            framework_context,
        )

        messages = [
            {"role": "system", "content": (
                "You are an AP Statistics curriculum expert analyzing synthetic "
                "student test results. Respond ONLY with a JSON array of "
                "improvement patches. No markdown fences, no commentary."
            )},
            {"role": "user", "content": prompt},
        ]

        raw = _call_llm(self.config, messages)
        if raw.startswith("ERROR:"):
            return []

        return self._parse_llm_response(raw, source_classifications)

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    def _build_analysis_prompt(
        self,
        failure_clusters: list[dict],
        source_classifications: list[dict],
        curriculum_text: dict,
        framework_context: dict,
    ) -> str:
        """Construct the analysis prompt per FOUNDATION_SPEC section 8.1."""
        parts: list[str] = []

        # -- Iteration results --
        parts.append("## ITERATION RESULTS")
        top_kcs = failure_clusters[:10]
        parts.append("Top failure KCs:")
        for cluster in top_kcs:
            parts.append(
                f"  - {cluster['kc_id']}: {cluster['error_rate'] * 100:.1f}% error rate "
                f"({cluster['n_errors']}/{cluster['n_total']})"
            )

        # -- Source classifications --
        parts.append("\n## FAILURE SOURCE ANALYSIS")
        for cls in source_classifications:
            parts.append(
                f"  - {cls['kc_id']}: source={cls['source']}  "
                f"evidence: {cls['evidence']}"
            )

        # -- Curriculum text for worst KCs --
        parts.append("\n## CURRENT CURRICULUM TEXT (for worst-performing KCs)")
        for cluster in top_kcs:
            kc = cluster["kc_id"]
            text = curriculum_text.get(kc, "(no text available)")
            # Truncate to keep prompt reasonable
            if len(text) > 800:
                text = text[:800] + "..."
            parts.append(f"\n### {kc}\n{text}")

        # -- AP framework requirements --
        parts.append("\n## AP FRAMEWORK REQUIREMENTS")
        if isinstance(framework_context, dict):
            objectives = framework_context.get("learningObjectives", [])
            if isinstance(objectives, list):
                for obj in objectives[:20]:
                    if isinstance(obj, dict):
                        parts.append(
                            f"  - {obj.get('id', '?')}: {obj.get('description', '')}"
                        )
                    else:
                        parts.append(f"  - {obj}")
            elif isinstance(objectives, dict):
                for oid, desc in list(objectives.items())[:20]:
                    parts.append(f"  - {oid}: {desc}")
            # Also include key terms if available
            terms = framework_context.get("keyTerms", [])
            if terms:
                parts.append(f"Key terms: {', '.join(str(t) for t in terms[:30])}")

        # -- Task instructions --
        parts.append("\n## TASK")
        parts.append(
            "1. Diagnose WHY students are failing on these KCs (pedagogical root cause + source)\n"
            "2. Propose SPECIFIC edits to the appropriate artifact:\n"
            '   - Worksheet exposition: {"target": "worksheet", "unit": N, "lesson": N, "field": "exposition", "section": "main", "new_text": "..."}\n'
            '   - Drill hint/scaffolding: {"target": "driller_cartridge", "cartridge_id": "...", "field": "hint", "new_value": "..."}\n'
            '   - Blooket question text: {"target": "blooket", "unit": N, "lesson": N, "question_changes": [...]}\n'
            '   - Prerequisite review insert: {"target": "worksheet", "unit": N, "section": "prereq_review", "new_text": "..."}\n'
            "3. Keep changes minimal and targeted -- one concept fix per patch\n"
            "4. Do NOT change the grading rules or evaluation items\n"
            "5. Respond with a JSON array of patch objects. Each object must include:\n"
            '   "target", "unit", "lesson", "kc_id", "source", "improvement" (description), "patch" (the structured data), "priority" (float 0-1)'
        )

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    def _parse_llm_response(
        self,
        raw: str,
        source_classifications: list[dict],
    ) -> list[dict]:
        """Parse the LLM response into a list of improvement dicts.

        Handles both clean JSON and markdown-fenced JSON.
        """
        text = raw.strip()

        # Strip markdown code fences if present
        if text.startswith("```"):
            # Remove opening fence (possibly ```json)
            text = re.sub(r"^```\w*\s*\n?", "", text)
            text = re.sub(r"\n?```\s*$", "", text)

        # Try to parse as JSON array
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            # Try to find a JSON array within the text
            match = re.search(r"\[.*\]", text, re.DOTALL)
            if match:
                try:
                    parsed = json.loads(match.group())
                except json.JSONDecodeError:
                    return []
            else:
                return []

        if not isinstance(parsed, list):
            parsed = [parsed]

        # Build source lookup for enrichment
        source_lookup = {c["kc_id"]: c for c in source_classifications}

        improvements: list[dict] = []
        for item in parsed:
            if not isinstance(item, dict):
                continue

            kc_id = item.get("kc_id", "")
            source_info = source_lookup.get(kc_id, {})

            improvement = {
                "target": item.get("target", "worksheet"),
                "unit": item.get("unit", 0),
                "lesson": item.get("lesson", 0),
                "kc_id": kc_id,
                "source": item.get("source", source_info.get("source", "unknown")),
                "improvement": item.get("improvement", ""),
                "patch": item.get("patch", item),
                "priority": float(item.get("priority", source_info.get("priority", 0.5))),
            }
            improvements.append(improvement)

        # Sort by priority descending
        improvements.sort(key=lambda x: -x["priority"])
        return improvements
