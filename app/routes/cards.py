from flask import Blueprint, render_template, request
from sqlalchemy import distinct

from app import db
from app.models import Card, CardPokedexNumber, Collection, Pokemon, Set

cards_bp = Blueprint("cards", __name__)

CARDS_PER_PAGE = 60


def _base_query(set_id=None, series=None, rarity=None, pokemon=None):
    """Build a filtered Card query from the given parameters."""
    query = db.select(Card)

    if pokemon:
        # Join through CardPokedexNumber to Pokemon and filter by name
        query = (
            query
            .join(CardPokedexNumber, Card.id == CardPokedexNumber.card_id)
            .join(Pokemon, CardPokedexNumber.pokedex_number == Pokemon.id)
            .where(Pokemon.name.ilike(f"%{pokemon}%"))
        )

    if set_id:
        query = query.where(Card.set_code == set_id)

    if series:
        query = (
            query
            .join(Set, Card.set_code == Set.id)
            .where(Set.series_name == series)
        )

    if rarity:
        query = query.where(Card.norm_rarity == rarity)

    return query.order_by(Card.set_code, Card.set_number)


@cards_bp.route("/")
def index():
    """Browse all cards with optional filtering."""
    set_id  = request.args.get("set_id", "").strip() or None
    series  = request.args.get("series", "").strip() or None
    rarity  = request.args.get("rarity", "").strip() or None
    pokemon = request.args.get("pokemon", "").strip() or None
    page    = request.args.get("page", 1, type=int)

    query      = _base_query(set_id=set_id, series=series, rarity=rarity, pokemon=pokemon)
    pagination = db.paginate(query, page=page, per_page=CARDS_PER_PAGE, error_out=False)
    cards      = pagination.items

    # Build collection map for badge display
    card_ids        = [c.id for c in cards]
    collection_rows = db.session.execute(
        db.select(Collection).where(Collection.card_id.in_(card_ids))
    ).scalars().all()
    collection_map  = {c.card_id: c for c in collection_rows}

    # Filter options
    all_sets    = db.session.execute(
        db.select(Set).order_by(Set.release_date)
    ).scalars().all()
    all_series  = db.session.execute(
        db.select(distinct(Set.series_name)).order_by(Set.series_name)
    ).scalars().all()
    all_rarities = db.session.execute(
        db.select(distinct(Card.norm_rarity))
        .where(Card.norm_rarity.is_not(None))
        .order_by(Card.norm_rarity_code)
    ).scalars().all()

    return render_template(
        "cards/index.html",
        cards_pagination=pagination,
        cards=cards,
        collection_map=collection_map,
        all_sets=all_sets,
        all_series=all_series,
        all_rarities=all_rarities,
        # Pass current filter values back to the template
        current_set_id=set_id,
        current_series=series,
        current_rarity=rarity,
        current_pokemon=pokemon,
    )


@cards_bp.route("/<card_id>")
def detail(card_id):
    """Show a single card's details."""
    card             = db.get_or_404(Card, card_id)
    collection_entry = db.session.get(Collection, card_id)

    return render_template(
        "cards/detail.html",
        card=card,
        collection_entry=collection_entry,
    )