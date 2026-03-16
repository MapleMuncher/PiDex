import json
import re
import sys
from datetime import datetime
from pathlib import Path

import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

# ---------------------------------------------------------------------------
# Path setup — seed.py lives in scripts/, app/ and images/ live in the
# project root one level up. Run from the project root:
#   python scripts/seed.py
# ---------------------------------------------------------------------------
_SCRIPTS_DIR = Path(__file__).parent          # pidex/scripts/
_PROJECT_DIR = _SCRIPTS_DIR.parent            # pidex/

sys.path.insert(0, str(_SCRIPTS_DIR))         # for rarity.py
sys.path.insert(0, str(_PROJECT_DIR))         # for app/

from app import create_app, db               # noqa: E402
from app.models import (                     # noqa: E402
    Card, CardEnergyType, CardPokedexNumber, CardSubType,
    Pokemon, Series, Set,
)
from rarity import normalize_rarity          # noqa: E402

# ---------------------------------------------------------------------------
# Path constants
# ---------------------------------------------------------------------------
PIDEX_DATA_DIR = _PROJECT_DIR.parent / "PiDexData"   # sibling repo

# On the Pi, images are served from /var/pidex/images/ (outside the repo).
# When seeding on desktop, write to images/ inside the project and sync later.
IMAGE_DIR = _PROJECT_DIR / "images"

SETS_FILE    = PIDEX_DATA_DIR / "sets" / "all.json"
POKEMON_FILE = PIDEX_DATA_DIR / "pokemon" / "subset.json"
CARDS_DIR    = PIDEX_DATA_DIR / "cards_subset"

CARD_IMAGE_DIR  = IMAGE_DIR / "cards"
SET_LOGO_DIR    = IMAGE_DIR / "sets" / "logos"
SET_SYMBOL_DIR  = IMAGE_DIR / "sets" / "symbols"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

STAGE_MAP = {"Baby": -1, "Basic": 0, "Stage 1": 1, "Stage 2": 2}


def _series_id_from_set_id(set_id: str) -> str:
    """Strip trailing digits to derive a series ID, e.g. 'swsh3' → 'swsh'.
    Also strips a trailing 'p' when the set_id contains no digits at all,
    treating it as a promo suffix, e.g. 'bwp' → 'bw'.

    Series codes that naturally end in 'p' (e.g. 'pop') are preserved because
    their set IDs always include digits ('pop1', 'pop2'), so stripping digits
    yields 'pop' with no further 'p'-stripping applied.
    """
    base = re.sub(r"\d+$", "", set_id)
    # If nothing was stripped (set_id has no trailing digits) and it ends in
    # 'p', treat the 'p' as a promo suffix and remove it.
    if base == set_id and set_id.endswith("p"):
        base = base[:-1]
    return base or set_id


def _download(url: str, dest: Path) -> bool:
    """Download a remote file to dest, skipping if it already exists.
    Returns True on success."""
    if dest.exists():
        return True
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(response.content)
        return True
    except Exception as exc:
        print(f"    [WARN] Could not download {url}: {exc}")
        return False


def _download_all(targets: list[tuple[str, Path]], workers: int = 10) -> None:
    """Download a list of (url, dest) pairs concurrently, skipping existing files."""
    pending = [(url, dest) for url, dest in targets if not dest.exists()]
    if not pending:
        return
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(_download, url, dest): dest for url, dest in pending}
        for future in as_completed(futures):
            future.result()  # re-raises any exception from _download


def _parse_set_number(value: str | None) -> int | None:
    """Convert a card number string to int.
    Returns None for non-numeric values like 'TG01' or 'SWSH001'."""
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Step 1: Series and Sets
# ---------------------------------------------------------------------------

def seed_series_and_sets() -> None:
    print("Seeding series and sets...")

    with open(SETS_FILE) as f:
        sets_data: list[dict] = json.load(f)

    # Build a series_name → series_id mapping using the first set encountered
    # for each series name. This ensures all sets with the same series name
    # (including promos like 'swshp') share a single consistent series ID.
    series_name_to_id: dict[str, str] = {}
    for entry in sets_data:
        series_name = entry["series"]
        if series_name not in series_name_to_id:
            series_name_to_id[series_name] = _series_id_from_set_id(entry["id"])

    # Upsert Series rows
    for series_name, series_id in series_name_to_id.items():
        if not db.session.get(Series, series_id):
            db.session.add(Series(id=series_id, name=series_name))

    # Upsert Set rows and collect image download targets
    image_targets: list[tuple[str, Path]] = []
    for entry in sets_data:
        set_id     = entry["id"]
        series_id  = series_name_to_id[entry["series"]]
        logo_url   = entry.get("images", {}).get("logo")
        symbol_url = entry.get("images", {}).get("symbol")

        release_date = None
        if raw_date := entry.get("releaseDate"):
            release_date = datetime.strptime(raw_date, "%Y/%m/%d").date()

        if not db.session.get(Set, set_id):
            db.session.add(Set(
                id=set_id,
                code=entry.get("ptcgoCode", ""),
                name=entry["name"],
                release_date=release_date,
                nr_official_cards=entry.get("printedTotal"),
                nr_total_cards=entry.get("total"),
                series_id=series_id,
                logo_url=logo_url,
                symbol_url=symbol_url,
            ))

        if logo_url:
            image_targets.append((logo_url,   SET_LOGO_DIR   / f"{set_id}.png"))
        if symbol_url:
            image_targets.append((symbol_url, SET_SYMBOL_DIR / f"{set_id}.png"))

    db.session.commit()
    print(f"  ✓ {len(series_name_to_id)} series, {len(sets_data)} sets")
    print(f"  Downloading {len(image_targets)} set images...")
    _download_all(image_targets)
    print("  ✓ Set images done")


# ---------------------------------------------------------------------------
# Step 2: Pokémon
# ---------------------------------------------------------------------------

def seed_pokemon() -> None:
    print("Seeding Pokémon...")

    with open(POKEMON_FILE) as f:
        pokemon_data: list[dict] = json.load(f)

    count = 0
    for entry in pokemon_data:
        if db.session.get(Pokemon, entry["id"]):
            continue

        types = entry.get("type", [])
        db.session.add(Pokemon(
            id=entry["id"],
            name=entry["name"],
            type_1=types[0] if len(types) > 0 else None,
            type_2=types[1] if len(types) > 1 else None,
            stage=STAGE_MAP.get(entry.get("stage")),
            generation=entry.get("generation"),
            evo_line=entry.get("evolution_line"),
            category=entry.get("category"),
        ))
        count += 1

    db.session.commit()
    print(f"  ✓ {count} Pokémon")


# ---------------------------------------------------------------------------
# Step 3: Cards
# ---------------------------------------------------------------------------

def seed_cards() -> None:
    print("Seeding cards...")
    total = 0

    for card_file in sorted(CARDS_DIR.glob("*.json")):
        set_id = card_file.stem  # filename without extension, e.g. "base1"

        with open(card_file) as f:
            cards_data: list[dict] = json.load(f)

        print(f"  {set_id} ({len(cards_data)} cards)...")
        image_targets: list[tuple[str, Path]] = []

        for entry in cards_data:
            card_id = entry["id"]
            if db.session.get(Card, card_id):
                continue

            rarity_raw = entry.get("rarity") or ""
            norm       = normalize_rarity(rarity_raw) if rarity_raw else None
            img_small  = entry.get("images", {}).get("small")
            img_large  = entry.get("images", {}).get("large")

            db.session.add(Card(
                id=card_id,
                super_type=entry.get("supertype"),
                name=entry["name"],
                set_code=set_id,
                set_number=entry.get("number"),
                rarity=rarity_raw or None,
                norm_rarity=norm.name if norm else None,
                norm_rarity_code=norm.code if norm else None,
                image_url=img_small,
                hd_image_url=img_large,
                flavor=entry.get("flavorText"),
            ))

            for sub in entry.get("subtypes", []):
                db.session.add(CardSubType(card_id=card_id, sub_type=sub))

            for energy in entry.get("types", []):
                db.session.add(CardEnergyType(card_id=card_id, energy_type=energy))

            for dex_num in entry.get("nationalPokedexNumbers", []):
                db.session.add(CardPokedexNumber(
                    card_id=card_id, pokedex_number=dex_num
                ))

            # Collect image target for concurrent download after DB inserts.
            # Use the raw card number as the filename (e.g. "1.png") to match
            # the images/cards/<set_code>/ directory structure.
            if img_small:
                raw_number = entry.get("number", card_id)
                image_targets.append((img_small, CARD_IMAGE_DIR / set_id / f"{raw_number}.png"))

            total += 1

        db.session.commit()
        _download_all(image_targets)

    print(f"  ✓ {total} cards total")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def seed() -> None:
    app = create_app()
    with app.app_context():
        seed_series_and_sets()
        seed_pokemon()
        seed_cards()
    print("\nSeeding complete.")


if __name__ == "__main__":
    seed()