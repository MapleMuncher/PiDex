from collections import defaultdict

from flask import Blueprint, render_template, request
from sqlalchemy import distinct, func
from sqlalchemy.orm import aliased

from app import db
from app.models import Card, CardPokedexNumber, CardStatus, Pokemon, Set
from app.sorting import DEFAULT_SORT, SORT_OPTIONS, apply_sort, needs_set_join

cards_bp = Blueprint("cards", __name__, url_prefix="/cards")

CARDS_PER_PAGE = 30


def _base_query(set_id=None, series=None, rarity=None, pokemon=None, evo_line=None, owned=False, wanted=False, status_match="any"):
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

    if evo_line:
        evo_line_card_ids = (
            db.select(CardPokedexNumber.card_id)
            .join(Pokemon, CardPokedexNumber.pokedex_number == Pokemon.id)
            .where(Pokemon.evo_line == evo_line)
        )
        query = query.where(Card.id.in_(evo_line_card_ids))

    if set_id:
        query = query.where(Card.set_code == set_id)

    if series:
        query = query.join(Set, Card.set_code == Set.id)
        query = query.where(Set.series_name == series)
        has_set_join = True

    if rarity:
        query = query.where(Card.norm_rarity == rarity)

    if owned and wanted:
        condition = (
            db.and_(CardStatus.owned == True, CardStatus.wanted == True)
            if status_match == "all"
            else db.or_(CardStatus.owned == True, CardStatus.wanted == True)
        )
        query = (
            query
            .join(CardStatus, Card.id == CardStatus.card_id)
            .where(condition)
        )
    elif owned:
        query = (
            query
            .join(CardStatus, Card.id == CardStatus.card_id)
            .where(CardStatus.owned == True)
        )
    elif wanted:
        query = (
            query
            .join(CardStatus, Card.id == CardStatus.card_id)
            .where(CardStatus.wanted == True)
        )

    return query, has_set_join, has_pokemon_join


@cards_bp.route("/")
def index():
    """Browse all cards with optional filtering and sorting."""
    set_id   = request.args.get("set_id", "").strip() or None
    series   = request.args.get("series", "").strip() or None
    rarity   = request.args.get("rarity", "").strip() or None
    pokemon  = request.args.get("pokemon", "").strip() or None
    evo_line_raw = request.args.get("evo_line", "").strip()
    evo_line = int(evo_line_raw) if evo_line_raw.isdigit() else None
    owned        = "owned" in request.args
    wanted       = "wanted" in request.args
    status_match = request.args.get("status_match", "any")
    if status_match not in ("any", "all"):
        status_match = "any"
    sort    = request.args.get("sort", DEFAULT_SORT)
    if sort not in SORT_OPTIONS:
        sort = DEFAULT_SORT
    page    = request.args.get("page", 1, type=int)

    query, has_set_join, has_pokemon_join = _base_query(set_id=set_id, series=series, rarity=rarity, pokemon=pokemon, evo_line=evo_line, owned=owned, wanted=wanted, status_match=status_match)
    query               = apply_sort(query, sort, has_set_join=has_set_join, has_pokemon_join=has_pokemon_join)
    pagination          = db.paginate(query, page=page, per_page=CARDS_PER_PAGE, error_out=False)
    cards               = pagination.items

    # Build status map for badge display
    card_ids    = [c.id for c in cards]
    status_rows = db.session.execute(
        db.select(CardStatus).where(CardStatus.card_id.in_(card_ids))
    ).scalars().all()
    status_map  = {s.card_id: s for s in status_rows}

    # Filter options
    sets_query = (
        db.select(Set)
        .where(Set.id.in_(db.select(Card.set_code).distinct()))
        .order_by(Set.release_date.desc())
    )
    if series:
        sets_query = sets_query.where(Set.series_name == series)
    all_sets = db.session.execute(sets_query).scalars().all()

    series_rows = db.session.execute(
        db.select(Set.series_name, func.min(Set.release_date).label("first_release"))
        .group_by(Set.series_name)
        .order_by(func.min(Set.release_date).desc())
    ).all()
    all_series = [
        (row.series_name, row.first_release.year if row.first_release else None)
        for row in series_rows
    ]

    all_rarities = db.session.execute(
        db.select(distinct(Card.norm_rarity))
        .where(Card.norm_rarity.is_not(None))
        .order_by(Card.norm_rarity_code)
    ).scalars().all()

    # evo_lines that have at least one card
    active_evo_lines = (
        db.select(Pokemon.evo_line).distinct()
        .where(Pokemon.evo_line.isnot(None))
        .where(Pokemon.id.in_(db.select(CardPokedexNumber.pokedex_number).distinct()))
    )
    BasePokemon = aliased(Pokemon)
    evo_line_rows = db.session.execute(
        db.select(Pokemon.evo_line, BasePokemon.name)
        .join(BasePokemon, Pokemon.evo_line == BasePokemon.id)
        .where(Pokemon.evo_line.in_(active_evo_lines))
        .distinct()
        .order_by(Pokemon.evo_line)
    ).all()
    # All member names per evo_line (for search — includes members not on cards)
    member_rows = db.session.execute(
        db.select(Pokemon.evo_line, Pokemon.name)
        .where(Pokemon.evo_line.in_(active_evo_lines))
        .order_by(Pokemon.evo_line, Pokemon.id)
    ).all()
    evo_members: dict[int, list[str]] = defaultdict(list)
    for row in member_rows:
        evo_members[row.evo_line].append(row.name)
    all_evo_lines = [
        (row.evo_line, row.name, ' '.join(evo_members[row.evo_line]))
        for row in evo_line_rows
    ]

    return render_template(
        "cards/index.html",
        cards_pagination=pagination,
        cards=cards,
        status_map=status_map,
        all_sets=all_sets,
        all_series=all_series,
        all_rarities=all_rarities,
        all_evo_lines=all_evo_lines,
        sort_options=[(k, v[0]) for k, v in SORT_OPTIONS.items()],
        current_set_id=set_id,
        current_series=series,
        current_rarity=rarity,
        current_pokemon=pokemon,
        current_evo_line=evo_line,
        current_owned=owned,
        current_wanted=wanted,
        current_status_match=status_match,
        current_sort=sort,
    )


@cards_bp.route("/<card_id>")
def detail(card_id):
    """Show a single card's details."""
    card             = db.get_or_404(Card, card_id)
    card_status = db.session.get(CardStatus, card_id)

    return render_template(
        "cards/detail.html",
        card=card,
        card_status=card_status,
    )