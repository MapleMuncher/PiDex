from collections import defaultdict

from flask import Blueprint, render_template, request
from sqlalchemy import case, distinct, func
from sqlalchemy.orm import aliased

from app import db
from app.models import Card, CardPokedexNumber, CardStatus, Pokemon, Set
from app.sorting import DEFAULT_SORT, SORT_OPTIONS, apply_sort

sets_bp = Blueprint("sets", __name__, url_prefix="/sets")


# ---------------------------------------------------------------------------
# Helper: build per-set collection stats in a single aggregated query
# ---------------------------------------------------------------------------
def _set_stats():
    """
    Returns a list of dicts, one per set, containing collection progress data.
    Sorted newest-first. Each dict carries stats for both 'official' mode
    (denominator = nr_official_cards) and 'db' mode (denominator = cards in DB).
    """
    owned_expr = func.sum(
        case((CardStatus.owned == True, 1), else_=0)
    ).label("owned_count")

    wanted_only_expr = func.sum(
        case(
            (db.and_(CardStatus.wanted == True, CardStatus.owned != True), 1),
            else_=0,
        )
    ).label("wanted_only_count")

    # COUNT(Card.id) is 0 for sets with no cards in DB (LEFT JOIN gives NULL)
    db_total_expr = func.count(Card.id).label("db_total")

    rows = db.session.execute(
        db.select(
            Set.id,
            Set.name,
            Set.code,
            Set.release_date,
            Set.nr_official_cards,
            Set.series_name,
            Set.logo_url,
            Set.symbol_url,
            owned_expr,
            wanted_only_expr,
            db_total_expr,
        )
        .outerjoin(Card, Card.set_code == Set.id)
        .outerjoin(CardStatus, CardStatus.card_id == Card.id)
        .group_by(Set.id)
        .order_by(Set.release_date.desc())
    ).all()

    result = []
    for row in rows:
        off_total    = row.nr_official_cards or 0
        db_total     = row.db_total or 0
        owned        = row.owned_count or 0
        wanted_only  = row.wanted_only_count or 0

        # Official-mode — 4 segments: owned | wanted | in-DB-untracked | not-in-DB
        # Cap db_total to official range to avoid secret-rare inflation
        db_in_off          = min(db_total, off_total)
        off_untracked_db   = max(0, db_in_off - owned - wanted_only)
        off_not_in_db      = max(0, off_total - db_in_off)
        off_owned_pct      = round(owned            / off_total * 100, 1) if off_total > 0 else 0
        off_wanted_pct     = round(wanted_only      / off_total * 100, 1) if off_total > 0 else 0
        off_untracked_pct  = round(off_untracked_db / off_total * 100, 1) if off_total > 0 else 0
        off_not_in_db_pct  = max(0.0, round(100 - off_owned_pct - off_wanted_pct - off_untracked_pct, 1))

        # DB-mode (denominator = cards seeded in the database)
        db_neither     = max(0, db_total - owned - wanted_only)
        db_owned_pct   = round(owned       / db_total * 100, 1) if db_total > 0 else 0
        db_wanted_pct  = round(wanted_only / db_total * 100, 1) if db_total > 0 else 0
        db_neither_pct = max(0.0, round(100 - db_owned_pct - db_wanted_pct, 1))

        # Tracked-mode (denominator = owned + wanted; no grey segments)
        tr_total      = owned + wanted_only
        tr_owned_pct  = round(owned       / tr_total * 100, 1) if tr_total > 0 else 0
        tr_wanted_pct = max(0.0, round(100 - tr_owned_pct, 1)) if tr_total > 0 else 0

        result.append({
            "id":               row.id,
            "name":             row.name,
            "code":             row.code,
            "release_date":     row.release_date,
            "series_name":      row.series_name,
            "logo_url":         row.logo_url,
            "symbol_url":       row.symbol_url,
            "owned":            owned,
            "wanted_only":      wanted_only,
            # Official mode (4-segment bar)
            "total":            off_total,
            "owned_pct":        off_owned_pct,
            "wanted_pct":       off_wanted_pct,
            "off_untracked_db": off_untracked_db,
            "off_untracked_pct": off_untracked_pct,
            "off_not_in_db":    off_not_in_db,
            "off_not_in_db_pct": off_not_in_db_pct,
            # DB mode
            "db_total":         db_total,
            "db_neither":       db_neither,
            "db_owned_pct":     db_owned_pct,
            "db_wanted_pct":    db_wanted_pct,
            "db_neither_pct":   db_neither_pct,
            # Tracked mode (owned + wanted only, no grey)
            "tr_total":         tr_total,
            "tr_owned_pct":     tr_owned_pct,
            "tr_wanted_pct":    tr_wanted_pct,
        })

    return result


@sets_bp.route("/")
def index():
    view = request.args.get("view", "card")
    if view not in ("card", "list"):
        view = "card"
    count = request.args.get("count", "tracked")
    if count not in ("official", "db", "tracked"):
        count = "tracked"

    sets_data = _set_stats()

    # Filter out sets irrelevant to the active count mode
    if count == "tracked":
        sets_data = [s for s in sets_data if s["owned"] > 0 or s["wanted_only"] > 0]
    elif count == "db":
        sets_data = [s for s in sets_data if s["db_total"] > 0]

    # Group by series for section headers (preserve newest-first order)
    series_order = []
    grouped: dict[str, list] = defaultdict(list)
    for s in sets_data:
        key = s["series_name"] or "Unknown"
        if key not in grouped:
            series_order.append(key)
        grouped[key].append(s)

    return render_template(
        "sets/index.html",
        view=view,
        count=count,
        series_order=series_order,
        grouped=grouped,
    )


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
