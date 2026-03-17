"""
One-off fix for mojibake in the local database.

When JSON files were read on Windows without encoding="utf-8", Python used
cp1252 as the default encoding, misinterpreting UTF-8 multi-byte sequences.
For example, é (UTF-8: 0xC3 0xA9) was read as Ã© in cp1252.

This script re-reads the source JSON files with the correct encoding and
updates any mismatched values in the database.

Run once from the project root:
    python -m scripts.fix_encoding
"""
import json

from app import create_app, db
from app.models import Card, Set
from scripts.utils import CARDS_DIR, SETS_FILE


def fix_sets() -> None:
    print("Fixing sets...")
    with open(SETS_FILE, encoding="utf-8") as f:
        sets_data: list[dict] = json.load(f)

    count = 0
    for entry in sets_data:
        row = db.session.get(Set, entry["id"])
        if not row:
            continue
        correct_name = entry["name"]
        correct_series = entry["series"]
        if row.name != correct_name or row.series_name != correct_series:
            row.name = correct_name
            row.series_name = correct_series
            count += 1

    db.session.commit()
    print(f"  ✓ Fixed {count} set(s)")


def fix_cards() -> None:
    print("Fixing cards...")
    count = 0

    for card_file in sorted(CARDS_DIR.glob("*.json")):
        with open(card_file, encoding="utf-8") as f:
            cards_data: list[dict] = json.load(f)

        for entry in cards_data:
            row = db.session.get(Card, entry["id"])
            if not row:
                continue
            correct_name       = entry["name"]
            correct_super_type = entry.get("supertype")
            correct_flavor     = entry.get("flavorText")
            if (row.name != correct_name
                    or row.super_type != correct_super_type
                    or row.flavor != correct_flavor):
                row.name       = correct_name
                row.super_type = correct_super_type
                row.flavor     = correct_flavor
                count += 1

        db.session.commit()

    print(f"  ✓ Fixed {count} card(s)")


def main() -> None:
    app = create_app()
    with app.app_context():
        fix_sets()
        fix_cards()
    print("\nDone.")


if __name__ == "__main__":
    main()