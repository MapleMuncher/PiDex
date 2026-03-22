from collections import defaultdict

from flask import Blueprint, jsonify, render_template, request
from sqlalchemy import case, distinct, func
from sqlalchemy.orm import aliased

from app import db
from app.models import Card, CardPokedexNumber, CardStatus, Pokemon, Set
from app.sorting import DEFAULT_SORT, SORT_OPTIONS, VALID_GROUP_BY, apply_sort


pokemon_bp = Blueprint("pokemon", __name__, url_prefix="/pokemon")


@pokemon_bp.route("/")
def index():
    """Browse all Pokémon with card counts."""
    count = request.args.get("count", "tracked")
    if count not in ("all", "tracked"):
        count = "tracked"

    owned_expr = func.sum(
        case((CardStatus.owned == True, 1), else_=0)
    ).label("owned_count")

    wanted_only_expr = func.sum(
        case(
            (db.and_(CardStatus.wanted == True, CardStatus.owned != True), 1),
            else_=0,
        )
    ).label("wanted_only_count")

    total_expr = func.count(distinct(Card.id)).label("total_cards")

    rows = db.session.execute(
        db.select(
            Pokemon.id,
            Pokemon.name,
            Pokemon.type_1,
            Pokemon.type_2,
            Pokemon.generation,
            Pokemon.evo_line,
            owned_expr,
            wanted_only_expr,
            total_expr,
        )
        .join(CardPokedexNumber, Pokemon.id == CardPokedexNumber.pokedex_number)
        .join(Card, Card.id == CardPokedexNumber.card_id)
        .outerjoin(CardStatus, CardStatus.card_id == Card.id)
        .group_by(Pokemon.id)
        .order_by(Pokemon.id)
    ).all()

    pokemon_data = []
    for row in rows:
        owned = row.owned_count or 0
        wanted_only = row.wanted_only_count or 0
        total = row.total_cards or 0

        if count == "tracked" and owned == 0 and wanted_only == 0:
            continue

        pokemon_data.append({
            "id": row.id,
            "name": row.name,
            "type_1": row.type_1,
            "type_2": row.type_2,
            "generation": row.generation,
            "owned": owned,
            "wanted_only": wanted_only,
            "total": total,
        })

    return render_template(
        "pokemon/index.html",
        count=count,
        pokemon_data=pokemon_data,
    )


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
    """Show all cards featuring a specific Pokémon, with filtering and sorting."""
    from app.routes.cards import _compute_groups, _parse_multi, _parse_multi_int, _all_pokemon_options

    pokemon = db.get_or_404(Pokemon, pokedex_number)

    # Filter/sort params (multi-value)
    set_ids      = _parse_multi(request.args.get("set_id", ""))
    series_list  = _parse_multi(request.args.get("series", ""))
    rarities     = _parse_multi(request.args.get("rarity", ""))
    evo_lines    = _parse_multi_int(request.args.get("evo_line", ""))
    owned        = "owned" in request.args
    wanted       = "wanted" in request.args
    status_match = request.args.get("status_match", "any")
    if status_match not in ("any", "all"):
        status_match = "any"
    untracked    = "untracked" in request.args

    group_by = request.args.get("group_by", "").strip() or None
    if group_by not in VALID_GROUP_BY:
        group_by = None

    sort = request.args.get("sort", DEFAULT_SORT)
    if sort not in SORT_OPTIONS:
        sort = DEFAULT_SORT

    # Base query: all cards for this pokemon
    query = (
        db.select(Card)
        .join(CardPokedexNumber, Card.id == CardPokedexNumber.card_id)
        .where(CardPokedexNumber.pokedex_number == pokedex_number)
    )
    has_set_join = False

    if evo_lines:
        evo_line_card_ids = (
            db.select(CardPokedexNumber.card_id)
            .join(Pokemon, CardPokedexNumber.pokedex_number == Pokemon.id)
            .where(Pokemon.evo_line.in_(evo_lines))
        )
        query = query.where(Card.id.in_(evo_line_card_ids))

    if set_ids:
        query = query.where(Card.set_code.in_(set_ids))

    if series_list:
        query = query.join(Set, Card.set_code == Set.id)
        query = query.where(Set.series_name.in_(series_list))
        has_set_join = True

    if rarities:
        query = query.where(Card.norm_rarity.in_(rarities))

    if owned and wanted:
        condition = (
            db.and_(CardStatus.owned == True, CardStatus.wanted == True)
            if status_match == "all"
            else db.or_(CardStatus.owned == True, CardStatus.wanted == True)
        )
        query = query.join(CardStatus, Card.id == CardStatus.card_id).where(condition)
    elif owned:
        query = query.join(CardStatus, Card.id == CardStatus.card_id).where(CardStatus.owned == True)
    elif wanted:
        query = query.join(CardStatus, Card.id == CardStatus.card_id).where(CardStatus.wanted == True)

    if untracked:
        tracked_pokemon = (
            db.select(CardPokedexNumber.pokedex_number).distinct()
            .join(CardStatus, CardPokedexNumber.card_id == CardStatus.card_id)
            .where(db.or_(CardStatus.owned == True, CardStatus.wanted == True))
        )
        tracked_cards = (
            db.select(CardPokedexNumber.card_id)
            .where(CardPokedexNumber.pokedex_number.in_(tracked_pokemon))
        )
        query = query.where(Card.id.not_in(tracked_cards))

    query = apply_sort(query, sort, has_set_join=has_set_join, has_pokemon_join=False, group_by=group_by)
    cards = db.session.execute(query).scalars().all()

    # Status map
    card_ids = [c.id for c in cards]
    status_rows = db.session.execute(
        db.select(CardStatus).where(CardStatus.card_id.in_(card_ids))
    ).scalars().all()
    status_map = {s.card_id: s for s in status_rows}

    # Compute groups
    card_groups = _compute_groups(cards, group_by, status_map)

    # Filter options — scoped to this pokemon's cards only
    pokemon_set_codes = db.select(Card.set_code).distinct().join(
        CardPokedexNumber, Card.id == CardPokedexNumber.card_id
    ).where(CardPokedexNumber.pokedex_number == pokedex_number)

    sets_query = (
        db.select(Set)
        .where(Set.id.in_(pokemon_set_codes))
        .order_by(Set.release_date.desc())
    )
    if series_list:
        sets_query = sets_query.where(Set.series_name.in_(series_list))
    all_sets = db.session.execute(sets_query).scalars().all()

    series_rows = db.session.execute(
        db.select(Set.series_name, func.min(Set.release_date).label("first_release"))
        .where(Set.id.in_(pokemon_set_codes))
        .group_by(Set.series_name)
        .order_by(func.min(Set.release_date).desc())
    ).all()
    all_series = [
        (row.series_name, row.first_release.year if row.first_release else None)
        for row in series_rows
    ]

    pokemon_card_ids = db.select(Card.id).join(
        CardPokedexNumber, Card.id == CardPokedexNumber.card_id
    ).where(CardPokedexNumber.pokedex_number == pokedex_number)

    all_rarities = db.session.execute(
        db.select(distinct(Card.norm_rarity))
        .where(Card.id.in_(pokemon_card_ids))
        .where(Card.norm_rarity.is_not(None))
        .order_by(Card.norm_rarity_code)
    ).scalars().all()

    return render_template(
        "pokemon/detail.html",
        pokemon=pokemon,
        cards=cards,
        card_groups=card_groups,
        status_map=status_map,
        all_sets=all_sets,
        all_series=all_series,
        all_rarities=all_rarities,
        all_evo_lines=[],
        all_pokemon=[],
        sort_options=[(k, v[0]) for k, v in SORT_OPTIONS.items()],
        group_by_options=[("", "No grouping"), ("evo_line", "Evolution line"), ("generation", "Generation"), ("rarity", "Rarity")],
        current_set_ids=set_ids,
        current_series=series_list,
        current_rarities=rarities,
        current_pokemon_ids=[],
        current_evo_lines=evo_lines,
        current_owned=owned,
        current_wanted=wanted,
        current_status_match=status_match,
        current_untracked=untracked,
        current_group_by=group_by,
        current_sort=sort,
    )
