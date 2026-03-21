from collections import defaultdict

from flask import Blueprint, render_template, request
from sqlalchemy import distinct, func
from sqlalchemy.orm import aliased

from app import db
from app.models import Card, CardPokedexNumber, CardStatus, Pokemon, Set
from app.sorting import DEFAULT_SORT, SORT_OPTIONS, VALID_GROUP_BY, apply_sort, needs_set_join

cards_bp = Blueprint("cards", __name__, url_prefix="/cards")

CARDS_PER_PAGE = 30


def _base_query(set_id=None, series=None, rarity=None, pokemon=None, evo_line=None, owned=False, wanted=False, status_match="any", untracked=False):
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

    if untracked:
        # Pokémon that have at least one card marked owned or wanted
        tracked_pokemon = (
            db.select(CardPokedexNumber.pokedex_number).distinct()
            .join(CardStatus, CardPokedexNumber.card_id == CardStatus.card_id)
            .where(db.or_(CardStatus.owned == True, CardStatus.wanted == True))
        )
        # Cards that feature any tracked Pokémon
        tracked_cards = (
            db.select(CardPokedexNumber.card_id)
            .where(CardPokedexNumber.pokedex_number.in_(tracked_pokemon))
        )
        query = query.where(Card.id.not_in(tracked_cards))

    return query, has_set_join, has_pokemon_join


def _compute_groups(cards, group_by, status_map):
    """Group paginated cards by the specified field.

    Returns [(label, [cards]), ...].  When group_by is falsy the entire
    list is returned as a single group with label ``None``.
    """
    if not cards or not group_by:
        return [(None, list(cards))]

    card_ids = [c.id for c in cards]

    if group_by == "rarity":
        label_for = {c.id: c.norm_rarity or "Unknown" for c in cards}
    else:
        # Need Pokémon info (evo_line or generation)
        primary_sq = (
            db.select(
                CardPokedexNumber.card_id,
                func.min(CardPokedexNumber.pokedex_number).label("primary_dex"),
            )
            .where(CardPokedexNumber.card_id.in_(card_ids))
            .group_by(CardPokedexNumber.card_id)
            .subquery()
        )
        if group_by == "evo_line":
            BasePokemon = aliased(Pokemon)
            rows = db.session.execute(
                db.select(primary_sq.c.card_id, BasePokemon.name, Pokemon.evo_line)
                .join(Pokemon, Pokemon.id == primary_sq.c.primary_dex)
                .outerjoin(BasePokemon, BasePokemon.id == Pokemon.evo_line)
            ).all()
            label_for = {
                r.card_id: f"{r.name}-line" if r.name else "Unknown"
                for r in rows
            }
        else:  # generation
            rows = db.session.execute(
                db.select(primary_sq.c.card_id, Pokemon.generation)
                .join(Pokemon, Pokemon.id == primary_sq.c.primary_dex)
            ).all()
            label_for = {
                r.card_id: f"Generation {r.generation}" if r.generation else "Unknown"
                for r in rows
            }

    # Build ordered groups — cards are already sorted, so detect boundaries
    groups = []
    current_label = None
    current_cards = []
    for card in cards:
        label = label_for.get(card.id, "Unknown")
        if label != current_label:
            if current_cards:
                groups.append((current_label, current_cards))
            current_label = label
            current_cards = [card]
        else:
            current_cards.append(card)
    if current_cards:
        groups.append((current_label, current_cards))
    return groups


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
    untracked    = "untracked" in request.args

    group_by = request.args.get("group_by", "").strip() or None
    if group_by not in VALID_GROUP_BY:
        group_by = None

    sort    = request.args.get("sort", DEFAULT_SORT)
    if sort not in SORT_OPTIONS:
        sort = DEFAULT_SORT
    page    = request.args.get("page", 1, type=int)

    query, has_set_join, has_pokemon_join = _base_query(set_id=set_id, series=series, rarity=rarity, pokemon=pokemon, evo_line=evo_line, owned=owned, wanted=wanted, status_match=status_match, untracked=untracked)
    query               = apply_sort(query, sort, has_set_join=has_set_join, has_pokemon_join=has_pokemon_join, group_by=group_by)
    pagination          = db.paginate(query, page=page, per_page=CARDS_PER_PAGE, error_out=False)
    cards               = pagination.items

    # Build status map for badge display
    card_ids    = [c.id for c in cards]
    status_rows = db.session.execute(
        db.select(CardStatus).where(CardStatus.card_id.in_(card_ids))
    ).scalars().all()
    status_map  = {s.card_id: s for s in status_rows}

    # Compute groups
    card_groups = _compute_groups(cards, group_by, status_map)

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
        card_groups=card_groups,
        status_map=status_map,
        all_sets=all_sets,
        all_series=all_series,
        all_rarities=all_rarities,
        all_evo_lines=all_evo_lines,
        sort_options=[(k, v[0]) for k, v in SORT_OPTIONS.items()],
        group_by_options=[("", "No grouping"), ("evo_line", "Evolution line"), ("generation", "Generation"), ("rarity", "Rarity")],
        current_set_id=set_id,
        current_series=series,
        current_rarity=rarity,
        current_pokemon=pokemon,
        current_evo_line=evo_line,
        current_owned=owned,
        current_wanted=wanted,
        current_status_match=status_match,
        current_untracked=untracked,
        current_group_by=group_by,
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
