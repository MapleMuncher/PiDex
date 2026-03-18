from flask import Blueprint, render_template

from app import db
from app.models import Card, CardPokedexNumber, Collection, Pokemon

pokemon_bp = Blueprint("pokemon", __name__, url_prefix="/pokemon")


@pokemon_bp.route("/<int:pokedex_number>")
def detail(pokedex_number):
    """Show all cards featuring a specific Pokémon."""
    pokemon = db.get_or_404(Pokemon, pokedex_number)

    # Get all cards featuring this Pokémon
    card_ids = db.session.execute(
        db.select(CardPokedexNumber.card_id)
        .where(CardPokedexNumber.pokedex_number == pokedex_number)
    ).scalars().all()

    cards = db.session.execute(
        db.select(Card)
        .where(Card.id.in_(card_ids))
        .order_by(Card.set_code, Card.set_number)
    ).scalars().all()

    # Build collection map for badge display
    collection_rows = db.session.execute(
        db.select(Collection).where(Collection.card_id.in_(card_ids))
    ).scalars().all()
    collection_map = {c.card_id: c for c in collection_rows}

    return render_template(
        "pokemon/detail.html",
        pokemon=pokemon,
        cards=cards,
        collection_map=collection_map,
    )