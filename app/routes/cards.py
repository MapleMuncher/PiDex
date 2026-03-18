from flask import Blueprint, render_template, request
from sqlalchemy import distinct

from app import db
from app.models import Card, CardPokedexNumber, Collection, Pokemon, Set
from app.sorting import DEFAULT_SORT, SORT_OPTIONS, apply_sort, needs_set_join

cards_bp = Blueprint("cards", __name__)

CARDS_PER_PAGE = 60


def _base_query(set_id=None, series=None, rarity=None, pokemon=None):
    """Build a filtered Card query. Sorting is applied separately via apply_sort()."""
    query = db.select(Card)
    has_set_join     = False
    has_pokemon_join = False

    if pokemon:
        query = (
            query
            .join(CardPokedexNumber, Card.id == CardPokedexNumber.card_id)
            .join(Pokemon, CardPokedexNumber.pokedex_number == Pokemon.id)
            .where(Pokemon.name.ilike(f"%{pokemon}%"))
        )
        has_pokemon_join = True

    if set_id:
        query = query.where(Card.set_code == set_id)

    if series:
        query = query.join(Set, Card.set_code == Set.id)
        query = query.where(Set.series_name == series)
        has_set_join = True

    if rarity:
        query = query.where(Card.norm_rarity == rarity)

    return query, has_set_join, has_pokemon_join


@cards_bp.route("/")
def index():
    """Browse all cards with optional filtering and sorting."""
    set_id  = request.args.get("set_id", "").strip() or None
    series  = request.args.get("series", "").strip() or None
    rarity  = request.args.get("rarity", "").strip() or None
    pokemon = request.args.get("pokemon", "").strip() or None
    sort    = request.args.get("sort", DEFAULT_SORT)
    if sort not in SORT_OPTIONS:
        sort = DEFAULT_SORT
    page    = request.args.get("page", 1, type=int)

    query, has_set_join, has_pokemon_join = _base_query(set_id=set_id, series=series, rarity=rarity, pokemon=pokemon)
    query               = apply_sort(query, sort, has_set_join=has_set_join, has_pokemon_join=has_pokemon_join)
    pagination          = db.paginate(query, page=page, per_page=CARDS_PER_PAGE, error_out=False)
    cards               = pagination.items

    # Build collection map for badge display
    card_ids        = [c.id for c in cards]
    collection_rows = db.session.execute(
        db.select(Collection).where(Collection.card_id.in_(card_ids))
    ).scalars().all()
    collection_map  = {c.card_id: c for c in collection_rows}

    # Filter options
    all_sets     = db.session.execute(
        db.select(Set).order_by(Set.release_date)
    ).scalars().all()
    all_series   = db.session.execute(
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
        sort_options=[(k, v[0]) for k, v in SORT_OPTIONS.items()],
        current_set_id=set_id,
        current_series=series,
        current_rarity=rarity,
        current_pokemon=pokemon,
        current_sort=sort,
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