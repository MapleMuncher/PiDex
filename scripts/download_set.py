import argparse
import json
import sys

import requests

from scripts.utils import PIDEX_DATA_DIR, RAW_CARDS_DIR, SETS_FILE

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
GITHUB_BASE  = "https://raw.githubusercontent.com/PokemonTCG/pokemon-tcg-data/master"
GITHUB_SETS  = f"{GITHUB_BASE}/sets/en.json"
GITHUB_CARDS = f"{GITHUB_BASE}/cards/en/{{set_id}}.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fetch_json(url: str) -> list | dict:
    """Fetch and parse JSON from a URL, raising on failure."""
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    return response.json()


def _update_sets_file(new_sets: list[dict]) -> None:
    """Merge new set entries into PiDexData/sets/all.json."""
    if SETS_FILE.exists():
        with open(SETS_FILE) as f:
            existing: list[dict] = json.load(f)
    else:
        existing = []

    existing_ids = {s["id"] for s in existing}
    added = [s for s in new_sets if s["id"] not in existing_ids]

    if added:
        existing.extend(added)
        SETS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(SETS_FILE, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2, ensure_ascii=False)
        print(f"  ✓ Added {len(added)} new set(s) to {SETS_FILE.name}")
    else:
        print(f"  ✓ {SETS_FILE.name} already up to date")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download raw set card data from the pokemon-tcg-data GitHub repo."
    )
    parser.add_argument(
        "--set", required=True, metavar="SET_ID", dest="set_id",
        help="Set code to download, e.g. swsh12"
    )
    args = parser.parse_args()
    set_id = args.set_id

    print(f"Downloading data for set: {set_id}")

    # 1. Update sets/all.json with latest set metadata from GitHub
    print("  Fetching set metadata from GitHub...")
    all_sets = _fetch_json(GITHUB_SETS)
    _update_sets_file(all_sets)

    # Verify the requested set exists in the metadata
    set_meta = next((s for s in all_sets if s["id"] == set_id), None)
    if not set_meta:
        print(f"  [ERROR] Set '{set_id}' not found in GitHub sets data.")
        print(f"  Available sets matching prefix: {[s['id'] for s in all_sets if s['id'].startswith(set_id[:3])]}")
        sys.exit(1)

    print(f"  Found: {set_meta['name']} ({set_meta.get('total', '?')} cards)")

    # 2. Download raw card data
    dest = RAW_CARDS_DIR / f"{set_id}.json"
    if dest.exists():
        print(f"  Raw card file already exists at {dest}, skipping download.")
    else:
        print(f"  Fetching card data from GitHub...")
        cards = _fetch_json(GITHUB_CARDS.format(set_id=set_id))
        RAW_CARDS_DIR.mkdir(parents=True, exist_ok=True)
        with open(dest, "w", encoding="utf-8") as f:
            json.dump(cards, f, indent=2, ensure_ascii=False)
        print(f"  ✓ {len(cards)} cards saved to {dest}")

    print(f"\nDone. Next step:")
    print(f"  python -m scripts.curate_set --set {set_id}")


if __name__ == "__main__":
    main()