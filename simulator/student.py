"""Synthetic student class.

Encapsulates a persona, KC memory state, and the ability to answer
assessment items by calling a local LLM (Ollama) endpoint.
"""

from __future__ import annotations

import asyncio
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from .memory import StudentMemory
from .prompts import build_item_prompt, build_student_system_prompt


# ---------------------------------------------------------------------------
# Student persona
# ---------------------------------------------------------------------------

@dataclass
class StudentPersona:
    """Configurable parameters that define a synthetic student's profile."""

    persona_id: str
    ability_tier: int                       # 1-5
    kc_acquisition_rate: float              # 0.05-0.30
    carelessness: float                     # 0.0-0.15
    guess_strategy: str                     # "random" | "misconception_driven" | "partial_knowledge"
    misconception_persistence: float        # 0.5-0.95
    reading_comprehension: float            # 0.6-1.0
    working_memory_slots: int               # 3-7


# ---------------------------------------------------------------------------
# Synchronous HTTP helper (wrapped in asyncio.to_thread for concurrency)
# ---------------------------------------------------------------------------

def _post_json_sync(url: str, payload: dict, timeout: float = 120.0) -> dict:
    """Blocking POST of JSON to *url*, returning the parsed response dict.

    Uses only stdlib ``urllib.request`` -- no external dependencies.
    """
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body)
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        raise RuntimeError(
            f"Ollama HTTP {exc.code}: {error_body}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Ollama connection error: {exc.reason}"
        ) from exc


# ---------------------------------------------------------------------------
# Synthetic student
# ---------------------------------------------------------------------------

class SyntheticStudent:
    """A single synthetic AP Statistics student.

    Holds a *persona* (fixed behavioural parameters) and a *memory*
    (mutable KC state machine).  Can answer canonical assessment items
    by delegating to a local LLM via the Ollama ``/api/chat`` endpoint.
    """

    def __init__(
        self,
        persona: StudentPersona,
        memory: StudentMemory | None = None,
    ) -> None:
        self.persona = persona
        self.memory = memory or StudentMemory()
        self.response_log: list[dict] = []

    # -- answering items ------------------------------------------------

    async def answer_item(
        self,
        item: dict,
        endpoint: str,
        model: str = "qwen3:8b",
        lesson_text: str | None = None,
        now: float | None = None,
    ) -> dict:
        """Send the item to the LLM and return a structured response dict.

        Parameters
        ----------
        item : dict
            Canonical item dict.  Must include ``item_id``, ``prompt``,
            ``item_type``, and (for MCQ) ``choices``.
        endpoint : str
            Base URL for the Ollama API, e.g. ``"http://localhost:11434"``.
        model : str
            Ollama model tag to use.
        lesson_text : str | None
            Optional exposition text the student just read.
        now : float | None
            Simulated unix timestamp.  Defaults to ``time.time()``.

        Returns
        -------
        dict
            ``{"item_id": str, "response": str, "raw_output": str, "timestamp": float}``
        """
        if now is None:
            now = time.time()

        system_prompt = build_student_system_prompt(self.persona, self.memory, now)
        user_prompt = build_item_prompt(item, lesson_text)

        item_type = item.get("item_type", "mcq")
        num_predict = 5 if item_type == "mcq" else 200

        url = endpoint.rstrip("/") + "/api/chat"
        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "options": {
                "temperature": 0.8,
                "num_predict": num_predict,
            },
            "think": False,
            "stream": False,
        }

        # Run the blocking HTTP call on a thread so we don't block the
        # asyncio event loop.
        response_data = await asyncio.to_thread(_post_json_sync, url, payload)

        # Ollama /api/chat returns {"message": {"role": "assistant", "content": "..."}, ...}
        raw_output = ""
        if "message" in response_data:
            raw_output = response_data["message"].get("content", "")
        elif "response" in response_data:
            # Fallback for /api/generate style responses
            raw_output = response_data.get("response", "")

        # Parse a clean response from the raw output
        response = self._parse_response(raw_output, item_type)

        result = {
            "item_id": item.get("item_id", ""),
            "response": response,
            "raw_output": raw_output,
            "timestamp": now,
        }

        self.response_log.append(result)
        return result

    # -- memory updates from grading ------------------------------------

    def update_memory_from_grade(
        self,
        item: dict,
        grade: dict,
        now: float,
    ) -> None:
        """Update KC states based on grading result.

        Parameters
        ----------
        item : dict
            Canonical item.  Must include ``kc_tags`` (list[str]).
        grade : dict
            Grading result.  Must include ``score`` with value
            ``"E"`` (correct), ``"P"`` (partial), or ``"I"`` (incorrect).
            May include ``matched_kcs`` and ``missing_kcs`` for partial
            credit differentiation.
        now : float
            Current simulated timestamp.
        """
        kc_tags: list[str] = item.get("kc_tags", [])
        score = grade.get("score", "I")
        error_mode = grade.get("error_mode", "none")

        if score == "E":
            # Fully correct -- boost all tagged KCs
            for kc_id in kc_tags:
                self.memory.update(
                    kc_id=kc_id,
                    correct=True,
                    now=now,
                    acquisition_rate=self.persona.kc_acquisition_rate,
                    misconception_persistence=self.persona.misconception_persistence,
                )
        elif score == "P":
            # Partial credit -- correct for matched, incorrect for missing
            matched = set(grade.get("matched_kcs", []))
            missing = set(grade.get("missing_kcs", []))
            for kc_id in kc_tags:
                if kc_id in matched:
                    self.memory.update(
                        kc_id=kc_id,
                        correct=True,
                        now=now,
                        acquisition_rate=self.persona.kc_acquisition_rate,
                        misconception_persistence=self.persona.misconception_persistence,
                    )
                elif kc_id in missing:
                    self.memory.update(
                        kc_id=kc_id,
                        correct=False,
                        now=now,
                        error_mode=error_mode,
                        misconception_persistence=self.persona.misconception_persistence,
                    )
                else:
                    # KC was tagged but not classified as matched or missing.
                    # Treat as a weak positive (half acquisition rate).
                    self.memory.update(
                        kc_id=kc_id,
                        correct=True,
                        now=now,
                        acquisition_rate=self.persona.kc_acquisition_rate * 0.5,
                        misconception_persistence=self.persona.misconception_persistence,
                    )
        else:
            # Incorrect (I) -- penalize all tagged KCs
            for kc_id in kc_tags:
                self.memory.update(
                    kc_id=kc_id,
                    correct=False,
                    now=now,
                    error_mode=error_mode,
                    misconception_persistence=self.persona.misconception_persistence,
                )

    # -- serialization --------------------------------------------------

    def snapshot(self) -> dict:
        """Full student state for persistence."""
        return {
            "persona": {
                "persona_id": self.persona.persona_id,
                "ability_tier": self.persona.ability_tier,
                "kc_acquisition_rate": self.persona.kc_acquisition_rate,
                "carelessness": self.persona.carelessness,
                "guess_strategy": self.persona.guess_strategy,
                "misconception_persistence": self.persona.misconception_persistence,
                "reading_comprehension": self.persona.reading_comprehension,
                "working_memory_slots": self.persona.working_memory_slots,
            },
            "memory": self.memory.snapshot(),
            "response_log_count": len(self.response_log),
        }

    @classmethod
    def from_snapshot(cls, data: dict) -> SyntheticStudent:
        """Restore from snapshot."""
        persona_data = data["persona"]
        persona = StudentPersona(
            persona_id=persona_data["persona_id"],
            ability_tier=persona_data["ability_tier"],
            kc_acquisition_rate=persona_data["kc_acquisition_rate"],
            carelessness=persona_data["carelessness"],
            guess_strategy=persona_data["guess_strategy"],
            misconception_persistence=persona_data["misconception_persistence"],
            reading_comprehension=persona_data["reading_comprehension"],
            working_memory_slots=persona_data["working_memory_slots"],
        )
        memory = StudentMemory.from_snapshot(data["memory"])
        student = cls(persona=persona, memory=memory)
        return student

    # -- internal helpers -----------------------------------------------

    @staticmethod
    def _parse_response(raw: str, item_type: str) -> str:
        """Extract a clean response from raw LLM output.

        For MCQ: uses a multi-pass strategy to find the answer letter:
          1. If the entire output is a single letter A-E, return it.
          2. Look for common patterns like "(B)", "B.", "B)", "answer is B".
          3. Fall back to the last standalone A-E letter in the output.
        For FRQ: return the trimmed output as-is.
        """
        import re

        raw = raw.strip()
        if item_type == "mcq":
            # Pass 1: entire output is a single letter
            if len(raw) == 1 and raw.upper() in "ABCDE":
                return raw.upper()

            # Pass 2: look for common answer patterns
            # Patterns: "(B)", "B.", "B)", "answer is B", "answer: B"
            patterns = [
                r"\b([A-Ea-e])\s*[.)\]]",       # "B." or "B)" or "B]"
                r"\(([A-Ea-e])\)",                # "(B)"
                r"(?:answer|choice)\s*(?:is|:)\s*([A-Ea-e])\b",  # "answer is B"
            ]
            for pat in patterns:
                m = re.search(pat, raw, re.IGNORECASE)
                if m:
                    return m.group(1).upper()

            # Pass 3: last standalone A-E letter (word boundary on both sides)
            standalone = re.findall(r"\b([A-Ea-e])\b", raw)
            if standalone:
                return standalone[-1].upper()

            # Pass 4: any A-E character at all
            for char in raw:
                if char.upper() in "ABCDE":
                    return char.upper()

            # Fallback: return the whole thing (grader can handle it)
            return raw
        else:
            return raw
