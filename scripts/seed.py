import json
from datetime import datetime
from pathlib import Path

from app import create_app, db
from app.models import (
    Card, CardEnergyType, CardPokedexNumber, CardSubType,
    Pokemon, Set,
)
from scripts.rarity import normalize_rarity
from scripts.utils import (
    CARDS_DIR, POKEMON_FILE, SETS_FILE,
    card_image_targets, download_all, set_image_targets,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

STAGE_MAP = {"Baby": -1, "Basic": 0, "Stage 1": 1, "Stage 2": 2}


# ---------------------------------------------------------------------------
# Step 1: Sets
# ---------------------------------------------------------------------------

def seed_sets() -> None:
    print("Seeding sets...")

    with open(SETS_FILE) as f:
        sets_data: list[dict] = json.load(f)

    image_targets: list[tuple[str, Path]] = []
    for entry in sets_data:
        set_id = entry["id"]

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
                series_name=entry["series"],
                logo_url=entry.get("images", {}).get("logo"),
                symbol_url=entry.get("images", {}).get("symbol"),
            ))

        image_targets.extend(set_image_targets(set_id, entry))

    db.session.commit()
    print(f"  ✓ {len(sets_data)} sets")
    download_all(image_targets)
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
        set_id = card_file.stem

        with open(card_file) as f:
            cards_data: list[dict] = json.load(f)

        print(f"  {set_id} ({len(cards_data)} cards)...")

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

            total += 1

        db.session.commit()
        download_all(card_image_targets(set_id, cards_data))

    print(f"  ✓ {total} cards total")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def seed() -> None:
    app = create_app()
    with app.app_context():
        seed_sets()
        seed_pokemon()
        seed_cards()
    print("\nSeeding complete.")


if __name__ == "__main__":
    seed()