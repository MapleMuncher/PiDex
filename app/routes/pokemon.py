from flask import Blueprint, jsonify, render_template, request

from app import db
from app.models import Card, CardPokedexNumber, CardStatus, Pokemon

pokemon_bp = Blueprint("pokemon", __name__, url_prefix="/pokemon")


@pokemon_bp.route("/search")
def search():
    """Return matching Pokémon for autocomplete. Returns JSON list of {id, name}."""
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify([])
    results = db.session.execute(
        db.select(Pokemon.id, Pokemon.name)
        .where(Pokemon.name.ilike(f"%{q}%"))
        .order_by(Pokemon.id)
        .limit(10)
    ).all()
    return jsonify([{"id": r.id, "name": r.name} for r in results])


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