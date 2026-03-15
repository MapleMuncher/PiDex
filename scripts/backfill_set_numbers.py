import json
import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).parent
_PROJECT_DIR = _SCRIPTS_DIR.parent
sys.path.insert(0, str(_PROJECT_DIR))

from app import create_app, db
from app.models import Card

CARDS_DIR = _PROJECT_DIR.parent / "PiDexData" / "cards_subset"

def backfill_set_numbers() -> None:
    app = create_app()
    with app.app_context():
        count = 0
        for card_file in sorted(CARDS_DIR.glob("*.json")):
            with open(card_file) as f:
                cards_data = json.load(f)
            for entry in cards_data:
                card = db.session.get(Card, entry["id"])
                if card and card.set_number is None:
                    card.set_number = entry.get("number")
                    count += 1
            db.session.commit()
        print(f"Backfilled {count} cards.")

if __name__ == "__main__":
    backfill_set_numbers()