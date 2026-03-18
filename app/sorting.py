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
    "set":          ("Set / number",        True,  False),
    "name":         ("Name A–Z",            False, False),
    "rarity_asc":   ("Rarity (low–high)",   False, False),
    "rarity_desc":  ("Rarity (high–low)",   False, False),
    "release_desc": ("Newest first",        True,  False),
    "release_asc":  ("Oldest first",        True,  False),
    "pokemon_name": ("Pokémon A–Z",         False, True),
    "evo_line":     ("Evolution line",      False, True),
    "category":     ("Category",            False, True),
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
# apply_sort
# ---------------------------------------------------------------------------
def apply_sort(query, sort_key: str, has_set_join: bool = False, has_pokemon_join: bool = False):
    """
    Apply ORDER BY clauses to a Card select query.

    If the sort requires a Set or Pokémon join that isn't already present,
    this function adds it. Pass has_set_join=True or has_pokemon_join=True
    if the caller has already joined those tables to avoid duplicate joins.

    Returns the modified query.
    """
    if sort_key not in SORT_OPTIONS:
        sort_key = DEFAULT_SORT

    # Add Set join if needed and not already present
    if needs_set_join(sort_key) and not has_set_join:
        query = query.join(Set, Card.set_code == Set.id)

    # Add Pokémon join via primary-Pokémon subquery if needed and not already present.
    # If Pokémon is already joined (e.g. from a name filter), reuse that join directly
    # rather than adding the subquery — ORDER BY will use the existing pokemon alias.
    if needs_pokemon_join(sort_key) and not has_pokemon_join:
        sq = _primary_pokemon_subquery()
        query = (
            query
            .outerjoin(sq, Card.id == sq.c.card_id)
            .outerjoin(Pokemon, Pokemon.id == sq.c.primary_dex)
        )

    # Apply ORDER BY
    if sort_key == "set":
        query = query.order_by(Set.release_date, Card.set_code, Card.set_number)
    elif sort_key == "name":
        query = query.order_by(Card.name)
    elif sort_key == "rarity_asc":
        query = query.order_by(Card.norm_rarity_code, Card.set_code, Card.set_number)
    elif sort_key == "rarity_desc":
        query = query.order_by(Card.norm_rarity_code.desc(), Card.set_code, Card.set_number)
    elif sort_key == "release_desc":
        query = query.order_by(Set.release_date.desc(), Card.set_number)
    elif sort_key == "release_asc":
        query = query.order_by(Set.release_date, Card.set_number)
    elif sort_key == "pokemon_name":
        query = query.order_by(Pokemon.name, Card.set_code, Card.set_number)
    elif sort_key == "evo_line":
        # Group by evolution family, then order within it by stage
        query = query.order_by(
            Pokemon.evo_line,
            Pokemon.stage,
            Pokemon.name,
            Card.set_code,
            Card.set_number,
        )
    elif sort_key == "category":
        # Order by category code (A=3-stage, B=2-stage, E=standalone, F=legendary...)
        # then group evolution lines together within each category
        query = query.order_by(
            Pokemon.category,
            Pokemon.evo_line,
            Pokemon.stage,
            Card.set_code,
            Card.set_number,
        )

    return query