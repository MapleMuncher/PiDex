from collections import defaultdict

from flask import Blueprint, render_template, request
from sqlalchemy import distinct, func
from sqlalchemy.orm import aliased

from app import db
from app.models import Card, CardPokedexNumber, CardStatus, Pokemon, Set
from app.sorting import DEFAULT_SORT, SORT_OPTIONS, VALID_GROUP_BY, apply_sort, needs_set_join

cards_bp = Blueprint("cards", __name__, url_prefix="/cards")

CARDS_PER_PAGE = 60


def _parse_multi(raw):
    """Parse a comma-separated query param into a list of non-empty strings."""
    if not raw:
        return []
    return [v.strip() for v in raw.split(",") if v.strip()]


def _parse_multi_int(raw):
    """Parse a comma-separated query param into a list of integers."""
    return [int(v) for v in _parse_multi(raw) if v.isdigit()]


def _base_query(
    set_ids=None,
    series_list=None,
    rarities=None,
    pokemon_ids=None,
    evo_lines=None,
    generations=None,
    owned=False,
    wanted=False,
    status_match="any",
    untracked=False,
):
    """Build a filtered Card query. Accepts lists for multi-select filters."""
    query = db.select(Card)
    has_set_join = False
    has_pokemon_join = False

    if pokemon_ids:
        query = (
            query
            .join(CardPokedexNumber, Card.id == CardPokedexNumber.card_id)
            .where(CardPokedexNumber.pokedex_number.in_(pokemon_ids))
        )
        has_pokemon_join = True

    if generations:
        gen_card_ids = (
            db.select(CardPokedexNumber.card_id)
            .join(Pokemon, CardPokedexNumber.pokedex_number == Pokemon.id)
            .where(Pokemon.generation.in_(generations))
        )
        query = query.where(Card.id.in_(gen_card_ids))

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


def _all_pokemon_options():
    """Return list of (id, name) for all Pokémon that appear on cards."""
    return db.session.execute(
        db.select(Pokemon.id, Pokemon.name)
        .where(Pokemon.id.in_(db.select(CardPokedexNumber.pokedex_number).distinct()))
        .order_by(Pokemon.id)
    ).all()


@cards_bp.route("/")
def index():
    """Browse all cards with optional filtering and sorting."""
    set_ids      = _parse_multi(request.args.get("set_id", ""))
    series_list  = _parse_multi(request.args.get("series", ""))
    rarities     = _parse_multi(request.args.get("rarity", ""))
    pokemon_ids  = _parse_multi_int(request.args.get("pokemon", ""))
    evo_lines    = _parse_multi_int(request.args.get("evo_line", ""))
    generations  = _parse_multi_int(request.args.get("generation", ""))
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

    query, has_set_join, has_pokemon_join = _base_query(
        set_ids=set_ids, series_list=series_list, rarities=rarities,
        pokemon_ids=pokemon_ids, evo_lines=evo_lines, generations=generations,
        owned=owned, wanted=wanted, status_match=status_match, untracked=untracked,
    )
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
    if series_list:
        sets_query = sets_query.where(Set.series_name.in_(series_list))
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

    all_pokemon = _all_pokemon_options()

    all_generations = db.session.execute(
        db.select(distinct(Pokemon.generation))
        .where(Pokemon.generation.isnot(None))
        .where(Pokemon.id.in_(db.select(CardPokedexNumber.pokedex_number).distinct()))
        .order_by(Pokemon.generation)
    ).scalars().all()

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
        all_pokemon=all_pokemon,
        all_generations=all_generations,
        sort_options=[(k, v[0]) for k, v in SORT_OPTIONS.items()],
        group_by_options=[("", "No grouping"), ("evo_line", "Evolution line"), ("generation", "Generation"), ("rarity", "Rarity")],
        current_set_ids=set_ids,
        current_series=series_list,
        current_rarities=rarities,
        current_pokemon_ids=pokemon_ids,
        current_evo_lines=evo_lines,
        current_generations=generations,
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
