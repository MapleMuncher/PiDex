import re
from collections import defaultdict
from datetime import date

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from sqlalchemy import case, distinct, func
from sqlalchemy.orm import aliased

from app import db
from app.models import (
    Card,
    CardPokedexNumber,
    CardStatus,
    Collection,
    CollectionCard,
    CollectionPokemon,
    CollectionRarity,
    Pokemon,
    Set,
)
from app.sorting import DEFAULT_SORT, SORT_OPTIONS, VALID_GROUP_BY, apply_sort

collection_bp = Blueprint("collection", __name__, url_prefix="/collection")

CARDS_PER_PAGE = 30


# ---------------------------------------------------------------------------
# Helpers shared with cards.py (copied to avoid circular imports)
# ---------------------------------------------------------------------------

def _parse_multi(raw):
    """Parse a comma-separated query param into a list of non-empty strings."""
    if not raw:
        return []
    return [v.strip() for v in raw.split(",") if v.strip()]


def _parse_multi_int(raw):
    """Parse a comma-separated query param into a list of integers."""
    return [int(v) for v in _parse_multi(raw) if v.isdigit()]


def _parse_date(raw):
    """Parse a date string (YYYY-MM-DD) into a Python date object, or None."""
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Collection query helpers
# ---------------------------------------------------------------------------

def _eligible_query(collection):
    """Build the base SELECT(Card) query for cards eligible for a collection.

    Applies the collection's fixed criteria:
      - Pokémon list  (if any CollectionPokemon rows exist)
      - Rarity list   (if any CollectionRarity rows exist)
      - Date range    (if date_from / date_to are set)

    Returns (query, has_set_join, has_pokemon_join).
    """
    query = db.select(Card)
    has_set_join = False
    has_pokemon_join = False

    pokemon_ids = [cp.pokedex_number for cp in collection.collection_pokemon]
    if pokemon_ids:
        query = (
            query
            .join(CardPokedexNumber, Card.id == CardPokedexNumber.card_id)
            .where(CardPokedexNumber.pokedex_number.in_(pokemon_ids))
            .distinct()
        )
        has_pokemon_join = True

    rarities = [cr.norm_rarity for cr in collection.collection_rarities]
    if rarities:
        query = query.where(Card.norm_rarity.in_(rarities))

    if collection.date_from or collection.date_to:
        query = query.join(Set, Card.set_code == Set.id)
        has_set_join = True
        if collection.date_from:
            query = query.where(Set.release_date >= collection.date_from)
        if collection.date_to:
            query = query.where(Set.release_date <= collection.date_to)

    return query, has_set_join, has_pokemon_join


def _collection_stats(collection):
    """Return (owned_count, wanted_only_count, total_count) for a collection.

    total = number of eligible cards that have either owned=True or
            wanted=True (i.e. cards the user actively cares about).
    owned = subset of those that are owned.
    wanted_only = subset that are wanted but not owned.

    Example: 5 Charizard cards — 2 owned, 1 wanted → (2, 1, 3).
    """
    base_q, _, _ = _eligible_query(collection)
    eligible_sq = base_q.with_only_columns(Card.id).distinct().subquery()

    row = db.session.execute(
        db.select(
            func.sum(case((CardStatus.owned == True, 1), else_=0)).label("owned"),
            func.sum(case((db.and_(CardStatus.wanted == True, CardStatus.owned == False), 1), else_=0)).label("wanted_only"),
            func.count().label("total"),
        )
        .where(CardStatus.card_id.in_(db.select(eligible_sq.c.id)))
        .where(db.or_(CardStatus.owned == True, CardStatus.wanted == True))
    ).one()

    return (row.owned or 0), (row.wanted_only or 0), (row.total or 0)


def _compute_groups(cards, group_by, status_map):
    """Group a list of cards by the specified field.

    Returns [(label, [cards]), ...].  When group_by is falsy the entire
    list is returned as a single un-labelled group.
    """
    if not cards or not group_by:
        return [(None, list(cards))]

    card_ids = [c.id for c in cards]

    if group_by == "rarity":
        label_for = {c.id: c.norm_rarity or "Unknown" for c in cards}
    else:
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
    """Return [(id, name)] for all Pokémon that appear on cards."""
    return db.session.execute(
        db.select(Pokemon.id, Pokemon.name)
        .where(Pokemon.id.in_(db.select(CardPokedexNumber.pokedex_number).distinct()))
        .order_by(Pokemon.id)
    ).all()


def _all_rarities_query():
    return db.session.execute(
        db.select(distinct(Card.norm_rarity))
        .where(Card.norm_rarity.is_not(None))
        .order_by(Card.norm_rarity_code)
    ).scalars().all()


# ---------------------------------------------------------------------------
# Routes — collection index & CRUD
# ---------------------------------------------------------------------------

@collection_bp.route("/")
def index():
    """List all collections with progress stats."""
    collections = (
        db.session.execute(db.select(Collection).order_by(Collection.name))
        .scalars().all()
    )

    stats = {c.id: _collection_stats(c) for c in collections}

    return render_template(
        "collection/index.html",
        collections=collections,
        stats=stats,
    )


@collection_bp.route("/new", methods=["GET", "POST"])
def new():
    """Create a new collection."""
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("Name is required.", "danger")
            return redirect(url_for("collection.new"))

        # Derive a URL-safe ID from the name
        collection_id = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        base_id = collection_id
        suffix = 1
        while db.session.get(Collection, collection_id):
            collection_id = f"{base_id}-{suffix}"
            suffix += 1

        collection = Collection(
            id=collection_id,
            name=name,
            mode="custom",
            date_from=_parse_date(request.form.get("date_from")),
            date_to=_parse_date(request.form.get("date_to")),
        )
        db.session.add(collection)

        for pid in _parse_multi_int(request.form.get("pokemon_ids", "")):
            db.session.add(
                CollectionPokemon(collection_id=collection_id, pokedex_number=pid)
            )

        for rarity in _parse_multi(request.form.get("rarities", "")):
            db.session.add(
                CollectionRarity(collection_id=collection_id, norm_rarity=rarity)
            )

        db.session.commit()
        flash(f"Collection \"{name}\" created.", "success")
        return redirect(url_for("collection.detail", collection_id=collection_id))

    return render_template(
        "collection/form.html",
        collection=None,
        all_pokemon=_all_pokemon_options(),
        all_rarities=_all_rarities_query(),
        current_pokemon_ids=[],
        current_rarities=[],
    )


@collection_bp.route("/<collection_id>/edit", methods=["GET", "POST"])
def edit(collection_id):
    """Edit an existing collection."""
    collection = db.get_or_404(Collection, collection_id)

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("Name is required.", "danger")
            return redirect(url_for("collection.edit", collection_id=collection_id))

        collection.name = name
        collection.date_from = _parse_date(request.form.get("date_from"))
        collection.date_to = _parse_date(request.form.get("date_to"))

        db.session.execute(
            db.delete(CollectionPokemon).where(
                CollectionPokemon.collection_id == collection_id
            )
        )
        for pid in _parse_multi_int(request.form.get("pokemon_ids", "")):
            db.session.add(
                CollectionPokemon(collection_id=collection_id, pokedex_number=pid)
            )

        db.session.execute(
            db.delete(CollectionRarity).where(
                CollectionRarity.collection_id == collection_id
            )
        )
        for rarity in _parse_multi(request.form.get("rarities", "")):
            db.session.add(
                CollectionRarity(collection_id=collection_id, norm_rarity=rarity)
            )

        db.session.commit()
        flash(f"Collection \"{name}\" updated.", "success")
        return redirect(url_for("collection.detail", collection_id=collection_id))

    current_pokemon_ids = [cp.pokedex_number for cp in collection.collection_pokemon]
    current_rarities    = [cr.norm_rarity for cr in collection.collection_rarities]

    return render_template(
        "collection/form.html",
        collection=collection,
        all_pokemon=_all_pokemon_options(),
        all_rarities=_all_rarities_query(),
        current_pokemon_ids=current_pokemon_ids,
        current_rarities=current_rarities,
    )


@collection_bp.route("/<collection_id>/delete", methods=["POST"])
def delete(collection_id):
    """Delete a collection."""
    collection = db.get_or_404(Collection, collection_id)
    name = collection.name
    db.session.delete(collection)
    db.session.commit()
    flash(f"Collection \"{name}\" deleted.", "success")
    return redirect(url_for("collection.index"))


# ---------------------------------------------------------------------------
# Routes — collection detail (card grid)
# ---------------------------------------------------------------------------

@collection_bp.route("/<collection_id>")
def detail(collection_id):
    """Show all eligible cards for a collection with filters and sorting."""
    collection = db.get_or_404(Collection, collection_id)

    # User-applied filters (layered on top of the collection's base criteria)
    set_ids  = _parse_multi(request.args.get("set_id", ""))
    rarities = _parse_multi(request.args.get("rarity", ""))
    owned    = "owned" in request.args
    wanted   = "wanted" in request.args
    binder   = "binder" in request.args

    group_by = request.args.get("group_by", "").strip() or None
    if group_by not in VALID_GROUP_BY:
        group_by = None

    sort = request.args.get("sort", DEFAULT_SORT)
    if sort not in SORT_OPTIONS:
        sort = DEFAULT_SORT
    page = request.args.get("page", 1, type=int)

    query, has_set_join, has_pokemon_join = _eligible_query(collection)

    if set_ids:
        query = query.where(Card.set_code.in_(set_ids))

    if rarities:
        query = query.where(Card.norm_rarity.in_(rarities))

    if owned:
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

    if binder:
        query = (
            query
            .join(
                CollectionCard,
                db.and_(
                    CollectionCard.card_id == Card.id,
                    CollectionCard.collection_id == collection_id,
                )
            )
            .where(CollectionCard.is_binder == True)
        )

    query      = apply_sort(
        query, sort,
        has_set_join=has_set_join,
        # Always False: the collection's CardPokedexNumber join is for filtering
        # only. apply_sort needs to add its own subquery to resolve Pokemon
        # columns (evo_line, generation etc.) for sort/group ordering.
        has_pokemon_join=False,
        group_by=group_by,
    )
    pagination = db.paginate(query, page=page, per_page=CARDS_PER_PAGE, error_out=False)
    cards      = pagination.items

    # Status map
    card_ids    = [c.id for c in cards]
    status_rows = db.session.execute(
        db.select(CardStatus).where(CardStatus.card_id.in_(card_ids))
    ).scalars().all()
    status_map  = {s.card_id: s for s in status_rows}

    # Binder set — cards flagged as binder picks for this collection
    binder_rows = db.session.execute(
        db.select(CollectionCard)
        .where(CollectionCard.collection_id == collection_id)
        .where(CollectionCard.card_id.in_(card_ids))
        .where(CollectionCard.is_binder == True)
    ).scalars().all()
    binder_set  = {r.card_id for r in binder_rows}

    card_groups = _compute_groups(cards, group_by, status_map)

    # Filter options scoped to eligible cards only
    base_q, _, _ = _eligible_query(collection)
    eligible_sq  = base_q.with_only_columns(Card.id).distinct().subquery()

    all_sets = db.session.execute(
        db.select(Set)
        .where(
            Set.id.in_(
                db.select(Card.set_code)
                .where(Card.id.in_(db.select(eligible_sq.c.id)))
                .distinct()
            )
        )
        .order_by(Set.release_date.desc())
    ).scalars().all()

    all_rarities = db.session.execute(
        db.select(distinct(Card.norm_rarity))
        .where(Card.id.in_(db.select(eligible_sq.c.id)))
        .where(Card.norm_rarity.is_not(None))
        .order_by(Card.norm_rarity_code)
    ).scalars().all()

    owned_count, wanted_only_count, total_count = _collection_stats(collection)

    return render_template(
        "collection/detail.html",
        collection=collection,
        cards_pagination=pagination,
        cards=cards,
        card_groups=card_groups,
        status_map=status_map,
        binder_set=binder_set,
        all_sets=all_sets,
        all_rarities=all_rarities,
        sort_options=[(k, v[0]) for k, v in SORT_OPTIONS.items()],
        group_by_options=[
            ("",           "No grouping"),
            ("evo_line",   "Evolution line"),
            ("generation", "Generation"),
            ("rarity",     "Rarity"),
        ],
        # Current filter state
        current_set_ids=set_ids,
        current_series=[],
        current_rarities=rarities,
        current_evo_lines=[],
        current_pokemon_ids=[],
        current_owned=owned,
        current_wanted=wanted,
        current_binder=binder,
        current_status_match="any",
        current_group_by=group_by,
        current_sort=sort,
        # Progress
        owned_count=owned_count,
        total_count=total_count,
    )


# ---------------------------------------------------------------------------
# Routes — highlight & binder toggles (JSON)
# ---------------------------------------------------------------------------

@collection_bp.route("/<collection_id>/highlight/<card_id>", methods=["POST"])
def highlight(collection_id, card_id):
    """Toggle the highlighted card for a collection.

    If the card is already the highlighted card, clears the highlight.
    """
    collection = db.get_or_404(Collection, collection_id)
    if collection.highlighted_card_id == card_id:
        collection.highlighted_card_id = None
        highlighted = False
    else:
        collection.highlighted_card_id = card_id
        highlighted = True
    db.session.commit()
    return jsonify({"card_id": card_id, "highlighted": highlighted})


@collection_bp.route("/toggle-binder", methods=["POST"])
def toggle_binder():
    """Toggle the binder flag for a card within a specific collection.

    Expects JSON: { "collection_id": "...", "card_id": "..." }
    Returns JSON: { "card_id": "...", "is_binder": true/false }
    """
    data          = request.get_json()
    collection_id = data.get("collection_id")
    card_id       = data.get("card_id")

    if not collection_id or not card_id:
        return jsonify({"error": "collection_id and card_id are required"}), 400

    entry = db.session.execute(
        db.select(CollectionCard)
        .where(
            CollectionCard.collection_id == collection_id,
            CollectionCard.card_id == card_id,
        )
    ).scalar_one_or_none()

    if entry:
        entry.is_binder = not entry.is_binder
        is_binder = entry.is_binder
        # Clean up the row if it no longer carries any useful state
        if not entry.is_binder and entry.pokemon_id is None:
            db.session.delete(entry)
            is_binder = False
    else:
        db.session.add(
            CollectionCard(
                collection_id=collection_id,
                card_id=card_id,
                is_binder=True,
            )
        )
        is_binder = True

    db.session.commit()
    return jsonify({"card_id": card_id, "is_binder": is_binder})


# ---------------------------------------------------------------------------
# Route — owned/wanted toggle (unchanged, kept here as the canonical endpoint)
# ---------------------------------------------------------------------------

@collection_bp.route("/toggle", methods=["POST"])
def toggle():
    """Set the owned/wanted/partner status for a card.

    Expects JSON: { "card_id": "base1-1", "owned": true/false,
                    "wanted": true/false, "partner": true/false }
    Returns JSON: { "card_id": ..., "owned": ..., "wanted": ...,
                    "partner": ... }
    """
    data    = request.get_json()
    card_id = data.get("card_id")
    owned   = bool(data.get("owned",   False))
    wanted  = bool(data.get("wanted",  False))
    partner = bool(data.get("partner", False))

    if not card_id:
        return jsonify({"error": "card_id is required"}), 400

    entry = db.session.get(CardStatus, card_id)

    if not owned and not wanted and not partner:
        if entry:
            db.session.delete(entry)
            db.session.commit()
    elif entry:
        entry.owned   = owned
        entry.wanted  = wanted
        entry.partner = partner
        db.session.commit()
    else:
        entry = CardStatus(card_id=card_id, owned=owned, wanted=wanted, partner=partner)
        db.session.add(entry)
        db.session.commit()

    return jsonify({"card_id": card_id, "owned": owned, "wanted": wanted, "partner": partner})
