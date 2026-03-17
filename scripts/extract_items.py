"""
extract_items.py — Python orchestrator that calls the Node.js adapters
to extract canonical items from curriculum_render and lrsl-driller,
then writes the results to data/items/.

Usage:
    python scripts/extract_items.py
    python scripts/extract_items.py --cartridges lsrl-calculations,residuals
"""

import subprocess
import json
import sys
import os
from pathlib import Path
from collections import Counter

# Project root (parent of scripts/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Output directory
ITEMS_DIR = PROJECT_ROOT / "data" / "items"

# Adapter scripts
CR_EXTRACT   = PROJECT_ROOT / "adapters" / "curriculum_render" / "extract_items.mjs"
DR_GENERATE  = PROJECT_ROOT / "adapters" / "lrsl_driller" / "generate_item.mjs"

# Default cartridges + modes to generate items from
DEFAULT_CARTRIDGES = {
    "lsrl-calculations": [
        "calc-zscore",
        "find-raw",
        "compare-zscores",
        "find-b",
        "find-a",
        "full-lsrl",
        "std-dev",
        "sign-check",
        "ratio-check",
    ],
}

# Number of items to generate per mode (with different seeds)
ITEMS_PER_MODE = 5


def run_node(script_path: Path, stdin_data: str = None, critical: bool = True) -> str | None:
    """Run a Node.js script and return its stdout.

    If critical=True (default), exits the process on failure.
    If critical=False, returns None on failure.
    """
    cmd = ["node", str(script_path)]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            input=stdin_data,
            timeout=60,
            cwd=str(PROJECT_ROOT),
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError:
        msg = "ERROR: 'node' not found. Please install Node.js."
        if critical:
            print(msg, file=sys.stderr)
            sys.exit(1)
        return None
    except subprocess.TimeoutExpired:
        msg = f"ERROR: Script timed out: {script_path}"
        if critical:
            print(msg, file=sys.stderr)
            sys.exit(1)
        return None

    if result.returncode != 0:
        msg = f"ERROR: Script failed (exit {result.returncode}): {script_path}"
        if critical:
            print(msg, file=sys.stderr)
            if result.stderr:
                print(result.stderr, file=sys.stderr)
            sys.exit(1)
        return None

    # Log any stderr (informational messages from the adapter)
    if result.stderr:
        print(result.stderr, file=sys.stderr, end="")

    return result.stdout


def validate_items(items: list, source: str) -> bool:
    """Validate that items have the expected shape."""
    if not isinstance(items, list):
        print(f"ERROR: Expected a JSON array from {source}, got {type(items).__name__}",
              file=sys.stderr)
        return False

    required_keys = {"item_id", "source", "item_type", "prompt", "expected"}

    for i, item in enumerate(items):
        if not isinstance(item, dict):
            print(f"ERROR: Item {i} from {source} is not an object", file=sys.stderr)
            return False

        missing = required_keys - set(item.keys())
        if missing:
            print(f"WARNING: Item {i} ({item.get('item_id', '?')}) from {source} "
                  f"missing keys: {missing}", file=sys.stderr)
            # Don't fail — just warn

    return True


def extract_curriculum_render() -> list:
    """Extract items from curriculum_render via Node adapter."""
    print("Extracting items from curriculum_render...")

    stdout = run_node(CR_EXTRACT)
    try:
        items = json.loads(stdout)
    except json.JSONDecodeError as e:
        print(f"ERROR: curriculum_render adapter returned invalid JSON: {e}",
              file=sys.stderr)
        sys.exit(1)

    validate_items(items, "curriculum_render")
    return items


def generate_driller_items(cartridges: dict) -> list:
    """Generate items from lrsl-driller cartridges."""
    items = []
    total_generated = 0

    for cartridge_id, modes in cartridges.items():
        print(f"Generating items from lrsl-driller cartridge: {cartridge_id}")

        for mode_id in modes:
            for seed in range(1, ITEMS_PER_MODE + 1):
                input_data = json.dumps({
                    "cartridge_id": cartridge_id,
                    "mode_id": mode_id,
                    "seed": seed * 1000 + hash(mode_id) % 1000,
                })

                try:
                    stdout = run_node(DR_GENERATE, stdin_data=input_data, critical=False)
                    if stdout is None:
                        print(f"  WARNING: Failed to generate {cartridge_id}/{mode_id} "
                              f"seed={seed}", file=sys.stderr)
                        continue
                    item = json.loads(stdout)
                    items.append(item)
                    total_generated += 1
                except (json.JSONDecodeError, ValueError) as e:
                    print(f"  WARNING: Failed to parse output for {cartridge_id}/{mode_id} "
                          f"seed={seed}: {e}", file=sys.stderr)
                    continue

    print(f"  Generated {total_generated} items from lrsl-driller")
    validate_items(items, "lrsl_driller")
    return items


def print_summary(cr_items: list, dr_items: list):
    """Print extraction summary."""
    print("\n" + "=" * 60)
    print("EXTRACTION SUMMARY")
    print("=" * 60)

    # Curriculum Render summary
    cr_by_type = Counter(it.get("item_type") for it in cr_items)
    cr_by_unit = Counter(f"Unit {it.get('unit')}" for it in cr_items)

    print(f"\ncurriculum_render: {len(cr_items)} items")
    print(f"  By type: {dict(cr_by_type)}")
    print(f"  By unit: {dict(sorted(cr_by_unit.items()))}")

    # Driller summary
    if dr_items:
        dr_by_type = Counter(it.get("item_type") for it in dr_items)
        dr_by_cart = Counter(
            it.get("item_id", "").split(":")[1] if ":" in it.get("item_id", "") else "?"
            for it in dr_items
        )

        print(f"\nlrsl_driller: {len(dr_items)} items")
        print(f"  By type: {dict(dr_by_type)}")
        print(f"  By cartridge: {dict(dr_by_cart)}")

    print(f"\nTotal items: {len(cr_items) + len(dr_items)}")
    print("=" * 60)


def parse_cartridge_args() -> dict:
    """Parse --cartridges CLI argument."""
    cartridges = dict(DEFAULT_CARTRIDGES)

    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--cartridges" and i < len(sys.argv):
            cart_ids = sys.argv[i + 1].split(",") if i + 1 <= len(sys.argv) else []
            # Load manifests to find available modes
            for cid in cart_ids:
                cid = cid.strip()
                if not cid:
                    continue
                manifest_path = (PROJECT_ROOT / "adapters" / ".." / ".."
                                 / "lrsl-driller" / "cartridges" / cid / "manifest.json")
                # Resolve to absolute
                manifest_path = (PROJECT_ROOT.parent / "lrsl-driller" / "cartridges"
                                 / cid / "manifest.json")
                try:
                    manifest = json.loads(manifest_path.read_text())
                    modes = [m["id"] for m in manifest.get("modes", [])]
                    cartridges[cid] = modes
                except (FileNotFoundError, json.JSONDecodeError, KeyError):
                    print(f"WARNING: Could not load manifest for cartridge '{cid}'",
                          file=sys.stderr)
        elif arg == "--no-driller":
            return {}
        elif arg == "--help":
            print("Usage: python scripts/extract_items.py [--cartridges id1,id2] [--no-driller]")
            sys.exit(0)

    return cartridges


def main():
    # Ensure output directory exists
    ITEMS_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Extract curriculum_render items
    cr_items = extract_curriculum_render()

    cr_output = ITEMS_DIR / "curriculum_render.json"
    cr_output.write_text(json.dumps(cr_items, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  Wrote {len(cr_items)} items to {cr_output}")

    # 2. Generate lrsl-driller items
    cartridges = parse_cartridge_args()
    dr_items = []
    if cartridges:
        dr_items = generate_driller_items(cartridges)

        dr_output = ITEMS_DIR / "lrsl_driller.json"
        dr_output.write_text(json.dumps(dr_items, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  Wrote {len(dr_items)} items to {dr_output}")

    # 3. Print summary
    print_summary(cr_items, dr_items)


if __name__ == "__main__":
    main()
