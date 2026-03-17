"""Promote converged curriculum patches to a target production repo.

Usage:
    python scripts/promote.py [--unit 1] [--target-repo ../curriculum_render] [--dry-run]

Copies converged curriculum patches from curriculum_patches/{unit}/ to
the target production repo. Dry-run mode by default -- shows what would
change without writing.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def collect_patches(unit: int) -> list[dict]:
    """Collect all patch overlay files for a given unit.

    Returns a list of dicts with keys:
        - source_path: absolute path to the overlay file
        - rel_path: relative path within curriculum_patches/
        - unit, lesson, field: parsed from path
        - content: the parsed JSON overlay
    """
    patches_dir = PROJECT_ROOT / "curriculum_patches" / str(unit)
    if not patches_dir.exists():
        return []

    results: list[dict] = []
    for root, _dirs, files in os.walk(patches_dir):
        for fname in files:
            if not fname.endswith(".json"):
                continue
            fpath = Path(root) / fname
            rel = fpath.relative_to(PROJECT_ROOT / "curriculum_patches")

            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    content = json.load(f)
            except (json.JSONDecodeError, OSError) as exc:
                print(f"  WARNING: Could not read {fpath}: {exc}", file=sys.stderr)
                continue

            # Parse unit/lesson/field from path parts
            parts = rel.parts  # e.g. ("1", "2", "exposition.json")
            parsed_unit = int(parts[0]) if len(parts) > 0 else unit
            parsed_lesson = int(parts[1]) if len(parts) > 1 else 0
            field = fname.replace(".json", "")

            results.append({
                "source_path": str(fpath),
                "rel_path": str(rel),
                "unit": parsed_unit,
                "lesson": parsed_lesson,
                "field": field,
                "content": content,
            })

    return results


def promote_patches(
    patches: list[dict],
    target_repo: str,
    dry_run: bool = True,
) -> int:
    """Copy patches to the target repository.

    Returns the number of patches promoted.
    """
    target = Path(target_repo)
    if not target.exists():
        print(f"ERROR: Target repo not found at {target}", file=sys.stderr)
        return 0

    promoted = 0
    for patch in patches:
        # Determine destination path within target repo
        # Convention: target_repo/patches/{unit}/{lesson}/{field}.json
        dest_dir = target / "patches" / str(patch["unit"]) / str(patch["lesson"])
        dest_file = dest_dir / f"{patch['field']}.json"

        if dry_run:
            print(f"  [DRY RUN] Would write: {dest_file}")
            print(f"            From: {patch['source_path']}")
            sections = list(patch["content"].keys())
            print(f"            Sections: {sections}")
        else:
            dest_dir.mkdir(parents=True, exist_ok=True)

            # Merge with existing if present
            existing: dict = {}
            if dest_file.exists():
                try:
                    with open(dest_file, "r", encoding="utf-8") as f:
                        existing = json.load(f)
                except (json.JSONDecodeError, OSError):
                    existing = {}

            merged = {**existing, **patch["content"]}
            with open(dest_file, "w", encoding="utf-8") as f:
                json.dump(merged, f, indent=2, ensure_ascii=False)
            print(f"  Promoted: {dest_file}")

        promoted += 1

    return promoted


def main():
    parser = argparse.ArgumentParser(
        description="Promote converged curriculum patches to a production repo."
    )
    parser.add_argument("--unit", type=int, default=1,
                        help="Unit number to promote (default: 1)")
    parser.add_argument("--target-repo", type=str, default="../curriculum_render",
                        help="Path to the target production repo")
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="Show what would change without writing (default: True)")
    parser.add_argument("--write", action="store_true",
                        help="Actually write changes (overrides --dry-run)")
    args = parser.parse_args()

    dry_run = not args.write

    print(f"Collecting patches for unit {args.unit}...")
    patches = collect_patches(args.unit)

    if not patches:
        print(f"No patches found for unit {args.unit} in curriculum_patches/")
        return

    print(f"Found {len(patches)} patch file(s)")
    target = Path(args.target_repo)
    if not target.is_absolute():
        target = PROJECT_ROOT / target

    mode = "DRY RUN" if dry_run else "WRITE"
    print(f"\nPromoting to {target} [{mode}]")
    print("-" * 60)

    promoted = promote_patches(patches, str(target), dry_run=dry_run)

    print("-" * 60)
    print(f"Total: {promoted} patch(es) {'would be ' if dry_run else ''}promoted")

    if dry_run:
        print("\nRe-run with --write to apply changes.")


if __name__ == "__main__":
    main()
