from app import db


class Set(db.Model):
    """
    Represents a Pokémon TCG expansion set.

    Sets belong to a Series and contain Cards. Set metadata is sourced 
    from the pokemon-tcg-data GitHub repository and populated by the 
    seed and update scripts. Not managed through the web app.

    Attributes:
        id (str): Set code used as primary key, e.g. "swsh3".
        code (str): Official set abbreviation, e.g. "DAA".
        name (str): Full set name, e.g. "Darkness Ablaze".
        release_date (date): Official release date of the set.
        nr_official_cards (int): Card count within the official set 
            number range.
        nr_total_cards (int): Total cards including secret rares beyond 
            the official count.
        series_name (str): Name of the series this set belongs to,
            e.g. "Sword & Shield".
        logo_url (str): Fallback remote URL for the set logo.
        symbol_url (str): Fallback remote URL for the set symbol.
    """

    __tablename__ = "sets"

    id = db.Column(db.String, primary_key=True)
    code = db.Column(db.String, nullable=False)
    name = db.Column(db.String, nullable=False)
    release_date = db.Column(db.Date, nullable=True)
    nr_official_cards = db.Column(db.Integer, nullable=True)
    nr_total_cards = db.Column(db.Integer, nullable=True)
    series_name = db.Column(db.String, nullable=False)
    logo_url = db.Column(db.String, nullable=True)
    symbol_url = db.Column(db.String, nullable=True)

    cards = db.relationship("Card", back_populates="set")


class Pokemon(db.Model):
    """
    Represents a Pokémon species, identified by Pokédex number.

    Used to filter cards by Pokémon and to group cards in binder slots. 
    Only Pokémon matching the personal preference filter (Gen 1–2 plus 
    select later Pokémon) are included.

    Attributes:
        id (int): Pokédex number, used as primary key.
        name (str): Pokémon species name.
        type_1 (str): Primary Pokémon type, e.g. "Water".
        type_2 (str): Secondary Pokémon type, if any.
        stage (int): Evolution stage. 
            -1 = Baby, 
            0 = Basic,
            1 = Stage 1, 
            2 = Stage 2.
        generation (int): Generation in which the Pokémon was
            introduced.
        evo_line (int): Pokédex number of the base stage of the
            evolution line, excluding Baby Pokémon. Used to group 
            evolution families together.
        category (str): Evolution line category code.
            A = Part of 3-stage evolution line.
            B = Part of 2-stage evolution line.
            C = Baby or additional pre-evolution.
            D = Branch evolution.
            E = Standalone Basic Pokémon.
            F = Legendary or Mythical Pokémon.
    """

    __tablename__ = "pokemon"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String, nullable=False)
    type_1 = db.Column(db.String, nullable=True)
    type_2 = db.Column(db.String, nullable=True)
    stage = db.Column(db.Integer, nullable=True)
    generation = db.Column(db.Integer, nullable=True)
    evo_line = db.Column(db.Integer, nullable=True)
    category = db.Column(db.String, nullable=True)

    card_pokedex_numbers = db.relationship(
        "CardPokedexNumber", back_populates="pokemon"
    )
    collection_pokemon = db.relationship(
        "CollectionPokemon", back_populates="pokemon"
    )
    slots = db.relationship("Slot", back_populates="pokemon")


class Card(db.Model):
    """
    Represents a single Pokémon TCG card.

    Cards are populated by the seed and update scripts from the
    pokemon-tcg-data GitHub repository, filtered by normalised rarity 
    and Pokédex number. Cards can also be added one at a time through 
    the web app via the TCGDex API or a TCGCollector URL.

    Standard-resolution images are stored locally on the Pi. The 
    hd_image_url field provides a fallback remote URL for high-
    resolution images, which are fetched on demand rather than stored 
    locally.

    Ownership status (owned/wanted) is tracked in the CardStatus
    table, not on the Card itself.

    Attributes:
        id (str): Combination of set code and card number, 
            e.g. "swsh3-69".
        super_type (str): Card category: "Pokemon", "Trainer", or 
            "Energy".
        name (str): Name printed on the card.
        set_code (str): Foreign key to the parent Set.
        set_number (str): Card's number within the set. May be 
            non-numeric, e.g. "TG01".
        rarity (str): Raw rarity string from source data,
            e.g. "Holo Rare V".
        norm_rarity (str): Normalised rarity label,
            e.g. "Holo Rare".
        norm_rarity_code (int): Integer for sorting by rarity.
            1 = Common through 10 = Special.
        image_url (str): Fallback remote URL for the standard-resolution 
            card image.
        hd_image_url (str): Remote URL for the high-resolution image, 
            loaded on demand.
        flavor (str): Flavor text printed on the card, if any.
    """

    __tablename__ = "cards"

    id = db.Column(db.String, primary_key=True)
    super_type = db.Column(db.String, nullable=True)
    name = db.Column(db.String, nullable=False)
    set_code = db.Column(
        db.String, db.ForeignKey("sets.id"), nullable=False
    )
    set_number = db.Column(db.String, nullable=True)
    rarity = db.Column(db.String, nullable=True)
    norm_rarity = db.Column(db.String, nullable=True)
    norm_rarity_code = db.Column(db.Integer, nullable=True)
    image_url = db.Column(db.String, nullable=True)
    hd_image_url = db.Column(db.String, nullable=True)
    flavor = db.Column(db.String, nullable=True)
    manually_added = db.Column(db.Boolean, nullable=False, server_default=db.false())

    set = db.relationship("Set", back_populates="cards")
    sub_types = db.relationship("CardSubType", back_populates="card")
    energy_types = db.relationship(
        "CardEnergyType", back_populates="card"
    )
    pokedex_numbers = db.relationship(
        "CardPokedexNumber", back_populates="card"
    )
    card_status = db.relationship(
        "CardStatus", back_populates="card", uselist=False
    )
    collection_cards = db.relationship(
        "CollectionCard", back_populates="card"
    )
    slots = db.relationship(
        "Slot", back_populates="card", foreign_keys="Slot.card_id"
    )
    reserved_slots = db.relationship(
        "Slot",
        back_populates="reserved_card",
        foreign_keys="Slot.reserved_card_id",
    )


class CardSubType(db.Model):
    """
    Join table storing the sub-types of a card.

    A card can have multiple sub-types (e.g. both "GX" and "Stage 2"), 
    so these are stored in a separate table with a composite primary 
    key.

    Examples of sub-type values: "Basic", "Stage 1", "Stage 2", "EX", 
    "GX", "V", "VMAX", "VSTAR", "Item", "Supporter", "Stadium".

    Attributes:
        card_id (str): Foreign key to the parent Card.
        sub_type (str): Sub-type label for that card.
    """

    __tablename__ = "card_sub_types"

    card_id = db.Column(
        db.String, db.ForeignKey("cards.id"), primary_key=True
    )
    sub_type = db.Column(db.String, primary_key=True)

    card = db.relationship("Card", back_populates="sub_types")


class CardEnergyType(db.Model):
    """
    Join table storing the energy types of a card.

    A card can have multiple energy types (e.g. a dual-type Pokémon), so 
    these are stored in a separate table with a composite primary key.

    Examples of energy type values: "Fire", "Water", "Grass",
    "Lightning", "Psychic", "Fighting", "Darkness", "Metal", "Dragon", 
    "Colorless".

    Attributes:
        card_id (str): Foreign key to the parent Card.
        energy_type (str): Energy type label for that card.
    """

    __tablename__ = "card_energy_types"

    card_id = db.Column(
        db.String, db.ForeignKey("cards.id"), primary_key=True
    )
    energy_type = db.Column(db.String, primary_key=True)

    card = db.relationship("Card", back_populates="energy_types")


class CardPokedexNumber(db.Model):
    """
    Join table linking cards to one or more Pokédex entries.

    Most cards feature a single Pokémon, but some (e.g. Tag Team cards) 
    feature multiple Pokémon and should appear when browsing by any of 
    those Pokémon. The composite primary key ensures each card-Pokémon 
    pairing is unique.

    Attributes:
        card_id (str): Foreign key to the parent Card.
        pokedex_number (int): Foreign key to the parent Pokemon.
    """

    __tablename__ = "card_pokedex_numbers"

    card_id = db.Column(
        db.String, db.ForeignKey("cards.id"), primary_key=True
    )
    pokedex_number = db.Column(
        db.Integer, db.ForeignKey("pokemon.id"), primary_key=True
    )

    card = db.relationship("Card", back_populates="pokedex_numbers")
    pokemon = db.relationship(
        "Pokemon", back_populates="card_pokedex_numbers"
    )


class CardStatus(db.Model):
    """
    Tracks owned/wanted/partner status of a card independently.

    Attributes:
        card_id (str): Foreign key to the Card. Primary key.
        owned (bool): Whether the household owns this card.
        wanted (bool): Whether the user wants this card.
        partner (bool): Whether this card belongs to the partner.
            Shown as a red "B" badge on thumbnails.
    """

    __tablename__ = "card_status"

    card_id = db.Column(
        db.String, db.ForeignKey("cards.id"), primary_key=True
    )
    owned = db.Column(db.Boolean, nullable=False, default=False)
    wanted = db.Column(db.Boolean, nullable=False, default=False)
    partner = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())

    card = db.relationship("Card", back_populates="card_status")


class Collection(db.Model):
    """
    A named group of cards with optional date and constraint filters.

    Attributes:
        id (str): Collection identifier, e.g. "classic".
        name (str): Display name.
        mode (str): Collection mode, e.g. "pokemon", "set".
        date_from (date): Optional start date filter for sets.
        date_to (date): Optional end date filter for sets.
        highlighted_card_id (str): Optional card to feature on the
            collection index tile.
    """

    __tablename__ = "collections"

    id = db.Column(db.String, primary_key=True)
    name = db.Column(db.String, nullable=False)
    mode = db.Column(db.String, nullable=False)
    date_from = db.Column(db.Date, nullable=True)
    date_to = db.Column(db.Date, nullable=True)
    highlighted_card_id = db.Column(
        db.String, db.ForeignKey("cards.id"), nullable=True
    )

    collection_pokemon = db.relationship(
        "CollectionPokemon", back_populates="collection", cascade="all, delete-orphan"
    )
    collection_rarities = db.relationship(
        "CollectionRarity", back_populates="collection", cascade="all, delete-orphan"
    )
    collection_cards = db.relationship(
        "CollectionCard", back_populates="collection", cascade="all, delete-orphan"
    )
    highlighted_card = db.relationship(
        "Card", foreign_keys=[highlighted_card_id]
    )


class CollectionPokemon(db.Model):
    """Links a collection to the Pokémon it covers."""

    __tablename__ = "collection_pokemon"

    collection_id = db.Column(
        db.String, db.ForeignKey("collections.id"), primary_key=True
    )
    pokedex_number = db.Column(
        db.Integer, db.ForeignKey("pokemon.id"), primary_key=True
    )

    collection = db.relationship(
        "Collection", back_populates="collection_pokemon"
    )
    pokemon = db.relationship(
        "Pokemon", back_populates="collection_pokemon"
    )


class CollectionRarity(db.Model):
    """Links a collection to the normalised rarities it includes."""

    __tablename__ = "collection_rarities"

    collection_id = db.Column(
        db.String, db.ForeignKey("collections.id"), primary_key=True
    )
    norm_rarity = db.Column(db.String, primary_key=True)

    collection = db.relationship(
        "Collection", back_populates="collection_rarities"
    )


class CollectionCard(db.Model):
    """
    Per-collection card metadata.

    Tracks collection-specific state for a card, such as whether the
    user has flagged it as their binder pick for this collection.

    Attributes:
        collection_id (str): Foreign key to the parent Collection.
        card_id (str): Foreign key to the Card.
        pokemon_id (int): Optional Pokémon context for the slot.
        is_binder (bool): Whether this card is flagged as the binder
            pick for this collection. Shown as a blue badge.
    """

    __tablename__ = "collection_cards"

    collection_id = db.Column(
        db.String, db.ForeignKey("collections.id"), primary_key=True
    )
    card_id = db.Column(
        db.String, db.ForeignKey("cards.id"), primary_key=True
    )
    pokemon_id = db.Column(
        db.Integer, db.ForeignKey("pokemon.id"), nullable=True
    )
    is_binder = db.Column(
        db.Boolean, nullable=False, default=False, server_default=db.false()
    )

    collection = db.relationship(
        "Collection", back_populates="collection_cards"
    )
    card = db.relationship("Card", back_populates="collection_cards")


class Binder(db.Model):
    """
    Represents a physical card binder.

    Binders contain Slots arranged in pages. Each binder has a page 
    shape and a total page count. Binders can optionally have 
    restriction rules that limit which cards are allowed in their slots.

    Attributes:
        id (str): Binder identifier, e.g. "B001".
        name (str): Display name of the binder.
        page_shape (str): Page layout code, e.g. "B3A" for a 3x3 
            asymmetrical layout. See DB design for the full list of 
            valid values.
        nr_pages (int): Total number of pages in the binder.
        restrictions (str): Custom restriction syntax limiting
            which cards may occupy slots in this binder,
            e.g. "[Pokedex <= 251]
            [SerieRelease >= 2023-01-01]".
    """

    __tablename__ = "binders"

    id = db.Column(db.String, primary_key=True)
    name = db.Column(db.String, nullable=False)
    page_shape = db.Column(db.String, nullable=True)
    nr_pages = db.Column(db.Integer, nullable=True)
    restrictions = db.Column(db.String, nullable=True)

    slots = db.relationship("Slot", back_populates="binder")


class Slot(db.Model):
    """
    Represents a physical slot in a binder page.

    A slot can be in one of three states:

    - Empty: no card assigned, no Pokémon reserved.
        card_id and pokemon_id are both NULL.
    - Pokémon-reserved: reserved for any card featuring a specific 
        Pokémon. pokemon_id is set, card_id is NULL.
    - Card-reserved: reserved for one specific card only.
        reserved_card_id is set.

    The card_id field holds the card currently occupying the slot.
    Ownership status is not stored on the slot — it is looked up from
    the CardStatus table via the card's card_status relationship.

    Position within the binder is stored as a float using fractional 
    indexing, allowing reordering by updating only a single row. When 
    float precision degrades from repeated insertions, a one-time 
    rebalance resets all positions to clean integers.

    Attributes:
        binder_id (str): Foreign key to the parent Binder.
        binder_position (float): Fractional index used for ordering 
            slots within the binder.
        pokemon_id (int): If set, only cards featuring this Pokémon are 
            allowed in this slot.
        card_id (str): The card currently in this slot, NULL if empty.
        reserved_card_id (str): If set, only this specific card is 
            allowed in this slot.
    """

    __tablename__ = "slots"

    binder_id = db.Column(
        db.String, db.ForeignKey("binders.id"), primary_key=True
    )
    binder_position = db.Column(db.Float, primary_key=True)
    pokemon_id = db.Column(
        db.Integer, db.ForeignKey("pokemon.id"), nullable=True
    )
    card_id = db.Column(
        db.String, db.ForeignKey("cards.id"), nullable=True
    )
    reserved_card_id = db.Column(
        db.String, db.ForeignKey("cards.id"), nullable=True
    )

    binder = db.relationship("Binder", back_populates="slots")
    pokemon = db.relationship("Pokemon", back_populates="slots")
    card = db.relationship(
        "Card", back_populates="slots", foreign_keys=[card_id]
    )
    reserved_card = db.relationship(
        "Card",
        back_populates="reserved_slots",
        foreign_keys=[reserved_card_id],
    )