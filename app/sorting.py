"""
Shared card sort options used across card browsing views.

Usage in a route:
    from app.sorting import SORT_OPTIONS, DEFAULT_SORT, apply_sort

    sort  = request.args.get("sort", DEFAULT_SORT)
    query = apply_sort(base_query, sort, has_set_join=True)

Usage in a template:
    {% for key, label in sort_options.items() %}
"""
from sqlalchemy import func

from app import db
from app.models import Card, CardPokedexNumber, Pokemon, Set

# ---------------------------------------------------------------------------
# Sort option definitions
# key  → (display label, needs_set_join, needs_pokemon_join)
# ---------------------------------------------------------------------------
SORT_OPTIONS: dict[str, tuple[str, bool, bool]] = {
    "release_desc": ("Newest first",   True,  False),
    "release_asc":  ("Oldest first",   True,  False),
    "pokedex_asc":  ("Pokédex number", True,  True),
    "evo_line":     ("Evolution line", True,  True),
    "generation":   ("Generation",     True,  True),
    "rarity":       ("Rarity",         True,  False),
    "name":         ("Name A–Z",       False, False),
    "category":     ("Category",       True,  True),
}

VALID_GROUP_BY = {"evo_line", "generation", "rarity"}

# group_by → (needs_set_join, needs_pokemon_join)
_GROUP_JOIN_REQS: dict[str, tuple[bool, bool]] = {
    "evo_line":   (False, True),
    "generation": (False, True),
    "rarity":     (False, False),
}

DEFAULT_SORT = "release_desc"


def sort_label(key: str) -> str:
    """Return the display label for a sort key."""
    return SORT_OPTIONS.get(key, SORT_OPTIONS[DEFAULT_SORT])[0]


def needs_set_join(key: str) -> bool:
    return SORT_OPTIONS.get(key, (None, False, False))[1]


def needs_pokemon_join(key: str) -> bool:
    return SORT_OPTIONS.get(key, (None, False, False))[2]


# ---------------------------------------------------------------------------
# Subquery: primary Pokémon per card (lowest Pokédex number)
#
# Cards can link to multiple Pokémon (Tag Team etc.). For sorting we need
# exactly one Pokémon per card — we take the one with the lowest Pokédex
# number as the "primary" Pokémon.
# ---------------------------------------------------------------------------
def _primary_pokemon_subquery():
    return (
        db.select(
            CardPokedexNumber.card_id,
            func.min(CardPokedexNumber.pokedex_number).label("primary_dex")
        )
        .group_by(CardPokedexNumber.card_id)
        .subquery()
    )


# ---------------------------------------------------------------------------
# Numeric set number expression
#
# set_number is stored as a string (e.g. "15", "TG01"). Casting to INTEGER
# in SQLite extracts the leading numeric part: CAST("15" AS INTEGER) = 15,
# CAST("TG01" AS INTEGER) = 0. Non-numeric cards sort before numbered ones,
# which is acceptable for the purposes of secondary tiebreaking.
# ---------------------------------------------------------------------------
def _set_number_int():
    return func.cast(Card.set_number, db.Integer)


# ---------------------------------------------------------------------------
# apply_sort
# ---------------------------------------------------------------------------
def apply_sort(query, sort_key: str, has_set_join: bool = False, has_pokemon_join: bool = False, group_by: str | None = None):
    """
    Apply ORDER BY clauses to a Card select query.

    When *group_by* is set the group's primary column(s) are prepended to
    the ORDER BY so that cards within the same group are contiguous.  The
    user's chosen *sort_key* then determines ordering within each group.

    If the sort requires a Set or Pokémon join that isn't already present,
    this function adds it. Pass has_set_join=True or has_pokemon_join=True
    if the caller has already joined those tables to avoid duplicate joins.

    Returns the modified query.
    """
    if sort_key not in SORT_OPTIONS:
        sort_key = DEFAULT_SORT

    # ---- determine total join requirements (group_by + sort) ----
    need_set = needs_set_join(sort_key)
    need_pokemon = needs_pokemon_join(sort_key)

    if group_by and group_by in _GROUP_JOIN_REQS:
        gs, gp = _GROUP_JOIN_REQS[group_by]
        need_set = need_set or gs
        need_pokemon = need_pokemon or gp

    # Add Set join if needed and not already present
    if need_set and not has_set_join:
        query = query.join(Set, Card.set_code == Set.id)

    # Add Pokémon join via primary-Pokémon subquery if needed and not already present.
    # If Pokémon is already joined (e.g. from a name filter), reuse that join directly
    # rather than adding the subquery — ORDER BY will use the existing pokemon alias.
    if need_pokemon and not has_pokemon_join:
        sq = _primary_pokemon_subquery()
        query = (
            query
            .outerjoin(sq, Card.id == sq.c.card_id)
            .outerjoin(Pokemon, Pokemon.id == sq.c.primary_dex)
        )

    # ---- build ORDER BY columns ----
    group_prefix = _group_order_columns(group_by)
    sort_columns = _sort_order_columns(sort_key)
    query = query.order_by(*group_prefix, *sort_columns)

    return query


def _group_order_columns(group_by: str | None) -> list:
    """Return ORDER BY column expressions for the group_by value."""
    if group_by == "evo_line":
        return [Pokemon.evo_line]
    if group_by == "generation":
        return [Pokemon.generation]
    if group_by == "rarity":
        return [Card.norm_rarity_code]
    return []


def _sort_order_columns(sort_key: str) -> list:
    """Return ORDER BY column expressions for a sort key."""
    if sort_key == "release_desc":
        return [Set.release_date.desc(), _set_number_int()]

    if sort_key == "release_asc":
        return [Set.release_date, _set_number_int()]

    if sort_key == "pokedex_asc":
        return [Pokemon.id, Set.release_date.desc(), _set_number_int()]

    if sort_key == "evo_line":
        return [Pokemon.evo_line, Pokemon.stage, Pokemon.id, Set.release_date.desc(), _set_number_int()]

    if sort_key == "generation":
        return [Pokemon.generation, Pokemon.evo_line, Pokemon.stage, Pokemon.id, Set.release_date.desc(), _set_number_int()]

    if sort_key == "rarity":
        return [Card.norm_rarity_code, Set.release_date.desc(), _set_number_int()]

    if sort_key == "name":
        return [Card.name, Card.set_code, _set_number_int()]

    if sort_key == "category":
        return [Pokemon.category, Pokemon.evo_line, Pokemon.stage, Pokemon.id, Set.release_date.desc(), _set_number_int()]

    return [Set.release_date.desc(), _set_number_int()]
