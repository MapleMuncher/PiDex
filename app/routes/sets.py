from collections import defaultdict

from flask import Blueprint, render_template, request
from sqlalchemy import distinct
from sqlalchemy.orm import aliased

from app import db
from app.models import Card, CardPokedexNumber, CardStatus, Pokemon, Set
from app.sorting import DEFAULT_SORT, SORT_OPTIONS, apply_sort

sets_bp = Blueprint("sets", __name__, url_prefix="/sets")


@sets_bp.route("/")
def index():
    return render_template("sets/index.html")


@sets_bp.route("/<set_id>")
def detail(set_id):
    """Show all cards in a set with filtering and sorting."""
    set_obj = db.get_or_404(Set, set_id)

    # Filter/sort params
    rarity       = request.args.get("rarity", "").strip() or None
    pokemon      = request.args.get("pokemon", "").strip() or None
    evo_line_raw = request.args.get("evo_line", "").strip()
    evo_line     = int(evo_line_raw) if evo_line_raw.isdigit() else None
    owned        = "owned" in request.args
    wanted       = "wanted" in request.args
    status_match = request.args.get("status_match", "any")
    if status_match not in ("any", "all"):
        status_match = "any"
    sort = request.args.get("sort", DEFAULT_SORT)
    if sort not in SORT_OPTIONS:
        sort = DEFAULT_SORT

    # Base query: all cards in this set
    query = db.select(Card).where(Card.set_code == set_id)
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

    if rarity:
        query = query.where(Card.norm_rarity == rarity)

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

    query = apply_sort(query, sort, has_set_join=False, has_pokemon_join=has_pokemon_join)
    cards = db.session.execute(query).scalars().all()

    # Status map
    card_ids = [c.id for c in cards]
    status_rows = db.session.execute(
        db.select(CardStatus).where(CardStatus.card_id.in_(card_ids))
    ).scalars().all()
    status_map = {s.card_id: s for s in status_rows}

    # Filter options scoped to this set
    set_card_ids = db.select(Card.id).where(Card.set_code == set_id)

    all_rarities = db.session.execute(
        db.select(distinct(Card.norm_rarity))
        .where(Card.set_code == set_id)
        .where(Card.norm_rarity.is_not(None))
        .order_by(Card.norm_rarity_code)
    ).scalars().all()

    # Evo lines represented in this set (scoped)
    active_evo_lines = (
        db.select(Pokemon.evo_line).distinct()
        .where(Pokemon.evo_line.isnot(None))
        .where(Pokemon.id.in_(
            db.select(CardPokedexNumber.pokedex_number).distinct()
            .where(CardPokedexNumber.card_id.in_(set_card_ids))
        ))
    )
    BasePokemon = aliased(Pokemon)
    evo_line_rows = db.session.execute(
        db.select(Pokemon.evo_line, BasePokemon.name)
        .join(BasePokemon, Pokemon.evo_line == BasePokemon.id)
        .where(Pokemon.evo_line.in_(active_evo_lines))
        .distinct()
        .order_by(Pokemon.evo_line)
    ).all()
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
        "sets/detail.html",
        set=set_obj,
        cards=cards,
        status_map=status_map,
        all_sets=[],
        all_series=[],
        all_rarities=all_rarities,
        all_evo_lines=all_evo_lines,
        sort_options=[(k, v[0]) for k, v in SORT_OPTIONS.items()],
        # set/series are page context, not user filters — pass None so
        # any_filter and the Reset link aren't triggered by the URL set_id
        current_set_id=None,
        current_series=None,
        current_rarity=rarity,
        current_pokemon=pokemon,
        current_evo_line=evo_line,
        current_owned=owned,
        current_wanted=wanted,
        current_status_match=status_match,
        current_sort=sort,
    )
