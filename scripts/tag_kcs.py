"""KC tagging script: assign kc_tags to items that lack them.

Usage:
    python scripts/tag_kcs.py [--items data/items/curriculum_render.json] [--frameworks data/frameworks.json]

Strategy:
1. Load items and frameworks
2. For each item without kc_tags:
   a. Match unit/lesson to framework learning objectives
   b. Use keyword matching to find the best KC tags
   c. Optionally call LLM for ambiguous items (Phase 3)
3. Write updated items back
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# KC vocabulary loading
# ---------------------------------------------------------------------------

def load_kc_tags(path: str | None = None) -> list[dict]:
    """Load the KC tag vocabulary from data/kc_tags.json."""
    kc_path = Path(path) if path else PROJECT_ROOT / "data" / "kc_tags.json"
    with open(kc_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("tags", [])


def load_frameworks(path: str) -> dict:
    """Load the AP framework data."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Keyword matching
# ---------------------------------------------------------------------------

def _extract_keywords(text: str) -> set[str]:
    """Extract lowercase words from a text for matching."""
    return set(re.findall(r"[a-z]{3,}", text.lower()))


def _build_kc_keyword_index(
    kc_tags: list[dict],
    frameworks: dict,
) -> dict[str, set[str]]:
    """Build a keyword index for each KC from its text + framework essential knowledge."""
    index: dict[str, set[str]] = {}

    for kc in kc_tags:
        kc_id = kc["id"]
        keywords = _extract_keywords(kc.get("text", ""))

        # Also pull essential knowledge from framework
        unit_key = str(kc.get("unit", ""))
        lesson_key = str(kc.get("lesson", ""))
        unit_data = frameworks.get("units", {}).get(unit_key, {})
        lesson_data = unit_data.get("lessons", {}).get(lesson_key, {})

        for lo in lesson_data.get("learningObjectives", []):
            if isinstance(lo, dict) and lo.get("id") == kc_id:
                for ek in lo.get("essentialKnowledge", []):
                    keywords.update(_extract_keywords(str(ek)))

        index[kc_id] = keywords

    return index


def match_kcs_for_item(
    item: dict,
    kc_tags: list[dict],
    kc_keyword_index: dict[str, set[str]],
) -> list[str]:
    """Find the best matching KC tags for an item using keyword overlap.

    Returns a list of KC IDs sorted by relevance (best first).
    """
    item_unit = item.get("unit")
    item_lesson = item.get("lesson")
    prompt_text = item.get("prompt", "")
    prompt_keywords = _extract_keywords(prompt_text)

    # Also include choice text for MCQ
    if item.get("choices"):
        for choice in item["choices"]:
            prompt_keywords.update(_extract_keywords(str(choice.get("value", ""))))

    if not prompt_keywords:
        return []

    candidates: list[tuple[str, float]] = []

    for kc in kc_tags:
        kc_id = kc["id"]
        kc_unit = kc.get("unit")
        kc_lesson = kc.get("lesson")

        kc_keywords = kc_keyword_index.get(kc_id, set())
        if not kc_keywords:
            continue

        # Compute overlap score
        overlap = prompt_keywords & kc_keywords
        if not overlap:
            continue

        # Jaccard-like score with unit/lesson boosting
        score = len(overlap) / len(prompt_keywords | kc_keywords)

        # Boost if unit matches
        if item_unit is not None and kc_unit == item_unit:
            score *= 2.0

        # Boost more if lesson also matches
        if item_lesson is not None and kc_lesson == item_lesson:
            score *= 1.5

        candidates.append((kc_id, score))

    # Sort by score descending, take top 3
    candidates.sort(key=lambda x: -x[1])
    return [kc_id for kc_id, _ in candidates[:3]]


# ---------------------------------------------------------------------------
# Main tagging logic
# ---------------------------------------------------------------------------

def tag_items(items: list[dict], kc_tags: list[dict], frameworks: dict) -> int:
    """Tag items that lack kc_tags. Returns count of items tagged."""
    kc_keyword_index = _build_kc_keyword_index(kc_tags, frameworks)

    tagged_count = 0
    for item in items:
        existing = item.get("kc_tags", [])
        if existing:
            continue  # already tagged

        matched = match_kcs_for_item(item, kc_tags, kc_keyword_index)
        if matched:
            item["kc_tags"] = matched
            tagged_count += 1

    return tagged_count


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Assign KC tags to items that don't have them."
    )
    parser.add_argument("--items", type=str,
                        default="data/items/curriculum_render.json",
                        help="Path to items JSON file")
    parser.add_argument("--frameworks", type=str,
                        default="data/frameworks.json",
                        help="Path to AP frameworks JSON")
    parser.add_argument("--kc-tags", type=str,
                        default="data/kc_tags.json",
                        help="Path to KC tags vocabulary JSON")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be tagged without writing")
    args = parser.parse_args()

    # Resolve paths relative to project root
    items_path = Path(args.items)
    if not items_path.is_absolute():
        items_path = PROJECT_ROOT / items_path

    frameworks_path = Path(args.frameworks)
    if not frameworks_path.is_absolute():
        frameworks_path = PROJECT_ROOT / frameworks_path

    kc_tags_path = Path(args.kc_tags)
    if not kc_tags_path.is_absolute():
        kc_tags_path = PROJECT_ROOT / kc_tags_path

    # Load data
    print(f"Loading items from {items_path}")
    with open(items_path, "r", encoding="utf-8") as f:
        items = json.load(f)

    print(f"Loading frameworks from {frameworks_path}")
    frameworks = load_frameworks(str(frameworks_path))

    print(f"Loading KC vocabulary from {kc_tags_path}")
    kc_tags = load_kc_tags(str(kc_tags_path))

    # Count untagged
    untagged = sum(1 for it in items if not it.get("kc_tags"))
    print(f"Total items: {len(items)}, untagged: {untagged}")

    if untagged == 0:
        print("All items already tagged. Nothing to do.")
        return

    # Tag
    tagged_count = tag_items(items, kc_tags, frameworks)
    print(f"Tagged {tagged_count} items")

    # Report
    still_untagged = sum(1 for it in items if not it.get("kc_tags"))
    print(f"Remaining untagged: {still_untagged}")

    # Show a sample of tagged items
    newly_tagged = [it for it in items if it.get("kc_tags")][:5]
    for it in newly_tagged:
        print(f"  {it['item_id']}: {it['kc_tags']}")

    if args.dry_run:
        print("\n[DRY RUN] No files written.")
        return

    # Write back
    with open(items_path, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2, ensure_ascii=False)
    print(f"Updated items written to {items_path}")


if __name__ == "__main__":
    main()
