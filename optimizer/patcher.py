"""Patch generation and application for curriculum artifacts.

Writes improvement patches as JSON overlays into curriculum_patches/,
and can convert LLM-proposed improvements into structured parameters
for the Agent pipeline.
"""

from __future__ import annotations

import json
import os
import subprocess


class CurriculumPatcher:
    """Apply improvement patches to curriculum artifacts."""

    def apply_patch(
        self,
        patch: dict,
        base_dir: str = "curriculum_patches",
    ) -> str:
        """Write a patch to the curriculum_patches directory as a JSON overlay.

        The overlay structure follows FOUNDATION_SPEC section 10.1::

            curriculum_patches/{unit}/{lesson}/{field}.json

        If an overlay file already exists, the patch is merged into it
        (keyed by ``section``).

        Args:
            patch: dict with keys:
                - target: "worksheet" | "driller_cartridge" | "blooket"
                - unit: int
                - lesson: int
                - field: str  (e.g. "exposition", "hint", "blooket")
                - section: str  (default "main")
                - content / new_text / new_value: the replacement text
            base_dir: root directory for patch files

        Returns:
            Absolute path to the written overlay file.
        """
        unit = patch.get("unit", 0)
        lesson = patch.get("lesson", 0)
        field = patch.get("field", self._infer_field(patch))
        section = patch.get("section", "main")

        # Determine the content value (accept multiple key names)
        content = (
            patch.get("content")
            or patch.get("new_text")
            or patch.get("new_value")
            or ""
        )

        # Build directory
        dir_path = os.path.join(base_dir, str(unit), str(lesson))
        os.makedirs(dir_path, exist_ok=True)

        file_path = os.path.join(dir_path, f"{field}.json")

        # Load existing overlay or start fresh
        overlay: dict = {}
        if os.path.exists(file_path):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    overlay = json.load(f)
            except (json.JSONDecodeError, OSError):
                overlay = {}

        # Apply the edit (keyed by section)
        overlay[section] = content

        # Write back
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(overlay, f, indent=2, ensure_ascii=False)

        return os.path.abspath(file_path)

    def generate_improvement_params(
        self,
        improvements: list[dict],
    ) -> dict:
        """Convert LLM-proposed improvements into structured parameters.

        These parameters can be passed to the Agent pipeline for artifact
        regeneration in the next iteration.

        Args:
            improvements: list of improvement dicts from
                FailureAnalyzer.analyze_with_llm()

        Returns:
            Dict with three lists::

                {
                    "worksheet_improvements": [
                        {"unit": int, "lesson": int, "section": str, "new_text": str}
                    ],
                    "driller_improvements": [
                        {"cartridge_id": str, "field": str, "new_value": str}
                    ],
                    "blooket_improvements": [
                        {"unit": int, "lesson": int, "question_changes": list}
                    ],
                }
        """
        worksheet_imps: list[dict] = []
        driller_imps: list[dict] = []
        blooket_imps: list[dict] = []

        for imp in improvements:
            target = imp.get("target", "")
            patch = imp.get("patch", {})

            if target == "worksheet":
                worksheet_imps.append({
                    "unit": imp.get("unit", patch.get("unit", 0)),
                    "lesson": imp.get("lesson", patch.get("lesson", 0)),
                    "section": patch.get("section", "main"),
                    "new_text": (
                        patch.get("new_text")
                        or patch.get("content")
                        or imp.get("improvement", "")
                    ),
                })

            elif target == "driller_cartridge":
                driller_imps.append({
                    "cartridge_id": patch.get("cartridge_id", ""),
                    "field": patch.get("field", "hint"),
                    "new_value": (
                        patch.get("new_value")
                        or patch.get("content")
                        or imp.get("improvement", "")
                    ),
                })

            elif target == "blooket":
                blooket_imps.append({
                    "unit": imp.get("unit", patch.get("unit", 0)),
                    "lesson": imp.get("lesson", patch.get("lesson", 0)),
                    "question_changes": patch.get("question_changes", []),
                })

        return {
            "worksheet_improvements": worksheet_imps,
            "driller_improvements": driller_imps,
            "blooket_improvements": blooket_imps,
        }

    def revert_patches(self, commit_hash: str) -> None:
        """Revert curriculum_patches/ to state at a given git commit.

        Uses ``git checkout <commit> -- curriculum_patches/`` to restore the
        directory.  This is a targeted checkout; it does NOT move HEAD.

        Args:
            commit_hash: the git commit to restore from.

        Raises:
            RuntimeError: if the git command fails.
        """
        try:
            result = subprocess.run(
                ["git", "checkout", commit_hash, "--", "curriculum_patches/"],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"git checkout failed (rc={result.returncode}): {result.stderr.strip()}"
                )
        except FileNotFoundError:
            raise RuntimeError(
                "git executable not found; ensure git is installed and on PATH"
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _infer_field(patch: dict) -> str:
        """Infer the overlay field name from the patch target."""
        target = patch.get("target", "worksheet")
        field_map = {
            "worksheet": "exposition",
            "driller_cartridge": "hints",
            "blooket": "blooket",
        }
        return patch.get("field", field_map.get(target, "exposition"))
