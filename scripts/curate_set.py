import argparse
import json
import sys

from scripts.rarity import normalize_rarity
from scripts.utils import (
    CARDS_DIR, RAW_CARDS_DIR,
    passes_pokedex_filter, passes_rarity_filter,
)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Apply rarity and Pokédex filters to a raw set file and write to cards_subset/."
    )
    parser.add_argument(
        "--set", required=True, metavar="SET_ID", dest="set_id",
        help="Set code to curate, e.g. swsh12"
    )
    args = parser.parse_args()
    set_id = args.set_id

    print(f"Curating set: {set_id}")

    # Load raw card data
    raw_file = RAW_CARDS_DIR / f"{set_id}.json"
    if not raw_file.exists():
        print(f"  [ERROR] Raw card file not found at {raw_file}.")
        print(f"  Run: python -m scripts.download_set --set {set_id}")
        sys.exit(1)

    with open(raw_file) as f:
        raw_cards: list[dict] = json.load(f)

    print(f"  {len(raw_cards)} cards in raw set")

    # Check if output file already exists
    dest = CARDS_DIR / f"{set_id}.json"
    if dest.exists():
        print(f"  [WARN] {dest} already exists and will be overwritten.")

    # Apply filters
    passed: list[dict] = []
    skipped_rarity = 0
    skipped_pokedex = 0

    for entry in raw_cards:
        rarity_raw  = entry.get("rarity") or ""
        norm        = normalize_rarity(rarity_raw) if rarity_raw else None
        norm_rarity = norm.name if norm else None
        dex_numbers = entry.get("nationalPokedexNumbers", [])

        if not passes_rarity_filter(norm_rarity):
            skipped_rarity += 1
            continue

        if not passes_pokedex_filter(dex_numbers):
            skipped_pokedex += 1
            continue

        passed.append(entry)

    # Write curated output
    CARDS_DIR.mkdir(parents=True, exist_ok=True)
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(passed, f, indent=2, ensure_ascii=False)

    print(f"  ✓ {len(passed)} cards passed filters")
    print(f"  Skipped: {skipped_rarity} rarity, {skipped_pokedex} Pokédex")
    print(f"  Written to {dest}")
    print(f"\nReview the output file and make any manual adjustments, then run:")
    print(f"  python -m scripts.insert_set --set {set_id}")


if __name__ == "__main__":
    main()