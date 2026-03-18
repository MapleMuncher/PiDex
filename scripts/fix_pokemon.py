"""
One-off fix for Baby Pokémon data issues in the local database.

Reads the corrected PiDexData/pokemon/subset.json and updates any Pokémon
rows where stage, evo_line, or category differ from the source data.

Run once from the project root:
    python -m scripts.fix_pokemon
"""
import json

from app import create_app, db
from app.models import Pokemon
from scripts.utils import POKEMON_FILE

STAGE_MAP = {"Baby": -1, "Basic": 0, "Stage 1": 1, "Stage 2": 2}


def main() -> None:
    with open(POKEMON_FILE, encoding="utf-8") as f:
        pokemon_data: list[dict] = json.load(f)

    app = create_app()
    with app.app_context():
        count = 0
        for entry in pokemon_data:
            row = db.session.get(Pokemon, entry["id"])
            if not row:
                continue

            correct_stage    = STAGE_MAP.get(entry.get("stage"))
            correct_evo_line = entry.get("evolution_line")
            correct_category = entry.get("category")

            if (row.stage    != correct_stage
                    or row.evo_line != correct_evo_line
                    or row.category != correct_category):
                row.stage    = correct_stage
                row.evo_line = correct_evo_line
                row.category = correct_category
                print(f"  Updated {row.name} (#{row.id}): "
                      f"stage={correct_stage}, evo_line={correct_evo_line}, category={correct_category}")
                count += 1

        db.session.commit()
        print(f"\n✓ Updated {count} Pokémon.")


if __name__ == "__main__":
    main()