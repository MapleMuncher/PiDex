from flask import Blueprint, render_template

from app import db
from app.models import Card, CardPokedexNumber, CardStatus, Pokemon

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

    # Build status map for badge display
    status_rows = db.session.execute(
        db.select(CardStatus).where(CardStatus.card_id.in_(card_ids))
    ).scalars().all()
    status_map = {s.card_id: s for s in status_rows}

    return render_template(
        "pokemon/detail.html",
        pokemon=pokemon,
        cards=cards,
        status_map=status_map,
    )