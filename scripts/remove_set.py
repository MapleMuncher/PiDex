"""
Testing utility — removes a set and all its cards from the local database.
Use this to reset state before testing the download/curate/insert pipeline.

Run from the project root:
    python -m scripts.remove_set --set base1
    python -m scripts.remove_set --set base1 --yes   # skip confirmation prompt
"""
import argparse

from app import create_app, db
from app.models import (
    Card, CardEnergyType, CardPokedexNumber, CardStatus, CardSubType,
    CollectionCard, Set, Slot,
)


def remove_set(set_id: str, skip_confirm: bool = False) -> None:
    app = create_app()
    with app.app_context():

        # Verify the set exists
        s = db.session.get(Set, set_id)
        if not s:
            print(f"  [ERROR] Set '{set_id}' not found in database.")
            return

        # Query card IDs directly — avoids loading card objects into the
        # session, which would cause a StaleDataError after bulk deletes
        card_ids = [row[0] for row in db.session.execute(
            db.select(Card.id).where(Card.set_code == set_id)
        ).all()]
        print(f"  Set:   {s.name} ({set_id})")
        print(f"  Cards: {len(card_ids)}")

        if not card_ids:
            print("  No cards to remove.")
        else:
            sub_count  = CardSubType.query.filter(CardSubType.card_id.in_(card_ids)).count()
            ene_count  = CardEnergyType.query.filter(CardEnergyType.card_id.in_(card_ids)).count()
            dex_count  = CardPokedexNumber.query.filter(CardPokedexNumber.card_id.in_(card_ids)).count()
            col_count  = CardStatus.query.filter(CardStatus.card_id.in_(card_ids)).count()
            slot_count = (
                Slot.query.filter(Slot.card_id.in_(card_ids)).count()
                + Slot.query.filter(Slot.reserved_card_id.in_(card_ids)).count()
            )
            print(f"  Also removing: {sub_count} subtypes, {ene_count} energy types, "
                  f"{dex_count} pokédex links, {col_count} card status entries, "
                  f"{slot_count} slot references")

        if not skip_confirm:
            confirm = input(f"\n  Remove set '{set_id}' and all its cards? [y/N] ").strip().lower()
            if confirm != "y":
                print("  Aborted.")
                return

        if card_ids:
            # Delete join tables and dependent rows first
            CardSubType.query.filter(CardSubType.card_id.in_(card_ids)).delete(synchronize_session=False)
            CardEnergyType.query.filter(CardEnergyType.card_id.in_(card_ids)).delete(synchronize_session=False)
            CardPokedexNumber.query.filter(CardPokedexNumber.card_id.in_(card_ids)).delete(synchronize_session=False)
            CardStatus.query.filter(CardStatus.card_id.in_(card_ids)).delete(synchronize_session=False)
            CollectionCard.query.filter(CollectionCard.card_id.in_(card_ids)).delete(synchronize_session=False)
            Slot.query.filter(Slot.card_id.in_(card_ids)).delete(synchronize_session=False)
            Slot.query.filter(Slot.reserved_card_id.in_(card_ids)).delete(synchronize_session=False)

            # Delete cards
            Card.query.filter(Card.set_code == set_id).delete(synchronize_session=False)

        # Delete the set
        db.session.delete(s)
        db.session.commit()

        print(f"  ✓ Set '{set_id}' removed.")
        print(f"\nYou can now re-test the pipeline:")
        print(f"  python -m scripts.download_set --set {set_id}")
        print(f"  python -m scripts.curate_set --set {set_id}")
        print(f"  python -m scripts.insert_set --set {set_id}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Remove a set and all its cards from the local database (for testing)."
    )
    parser.add_argument(
        "--set", required=True, metavar="SET_ID",
        help="Set code to remove, e.g. base1"
    )
    parser.add_argument(
        "--yes", action="store_true",
        help="Skip confirmation prompt."
    )
    args = parser.parse_args()
    remove_set(args.set, skip_confirm=args.yes)


if __name__ == "__main__":
    main()