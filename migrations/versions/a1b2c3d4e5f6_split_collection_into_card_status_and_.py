"""Split collection into card_status and collections

Revision ID: a1b2c3d4e5f6
Revises: d242f240f793
Create Date: 2026-03-20 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = 'd242f240f793'
branch_labels = None
depends_on = None


def upgrade():
    # 1. Create card_status table
    op.create_table('card_status',
        sa.Column('card_id', sa.String(), nullable=False),
        sa.Column('owned', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('wanted', sa.Boolean(), nullable=False, server_default='0'),
        sa.ForeignKeyConstraint(['card_id'], ['cards.id']),
        sa.PrimaryKeyConstraint('card_id')
    )

    # 2. Migrate data from old collection table
    op.execute("""
        INSERT INTO card_status (card_id, owned, wanted)
        SELECT card_id,
               CASE WHEN status = 'OWNED' THEN 1 ELSE 0 END,
               CASE WHEN status = 'WANTED' THEN 1 ELSE 0 END
        FROM collection
    """)

    # 3. Drop old collection table
    op.drop_table('collection')

    # 4. Create new collections system
    op.create_table('collections',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('mode', sa.String(), nullable=False),
        sa.Column('date_from', sa.Date(), nullable=True),
        sa.Column('date_to', sa.Date(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )

    op.create_table('collection_pokemon',
        sa.Column('collection_id', sa.String(), nullable=False),
        sa.Column('pokedex_number', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['collection_id'], ['collections.id']),
        sa.ForeignKeyConstraint(['pokedex_number'], ['pokemon.id']),
        sa.PrimaryKeyConstraint('collection_id', 'pokedex_number')
    )

    op.create_table('collection_rarities',
        sa.Column('collection_id', sa.String(), nullable=False),
        sa.Column('norm_rarity', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['collection_id'], ['collections.id']),
        sa.PrimaryKeyConstraint('collection_id', 'norm_rarity')
    )

    op.create_table('collection_cards',
        sa.Column('collection_id', sa.String(), nullable=False),
        sa.Column('card_id', sa.String(), nullable=False),
        sa.Column('pokemon_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['collection_id'], ['collections.id']),
        sa.ForeignKeyConstraint(['card_id'], ['cards.id']),
        sa.ForeignKeyConstraint(['pokemon_id'], ['pokemon.id']),
        sa.PrimaryKeyConstraint('collection_id', 'card_id')
    )

    # 5. Seed predefined collections
    op.execute("""
        INSERT INTO collections (id, name, mode, date_from, date_to) VALUES
        ('classic', 'Classic', 'pokemon', NULL, '2002-12-31'),
        ('modern', 'Modern', 'pokemon', '2023-01-01', NULL),
        ('cyndaquil', 'Cyndaquil', 'pokemon', NULL, NULL),
        ('sneasel', 'Sneasel', 'pokemon', NULL, NULL),
        ('scyther', 'Scyther', 'pokemon', NULL, NULL),
        ('scizor', 'Scizor', 'pokemon', NULL, NULL)
    """)

    # Seed collection_pokemon rows
    # classic & modern: all pokemon (1-251 + select later) — handled dynamically, skip for now
    # Specific pokemon collections:
    # Cyndaquil line: 155 (Cyndaquil), 156 (Quilava), 157 (Typhlosion)
    # Sneasel line: 215 (Sneasel), 461 (Weavile)
    # Scyther: 123 (Scyther)
    # Scizor: 212 (Scizor)
    op.execute("""
        INSERT INTO collection_pokemon (collection_id, pokedex_number) VALUES
        ('cyndaquil', 155),
        ('cyndaquil', 156),
        ('cyndaquil', 157),
        ('sneasel', 215),
        ('sneasel', 461),
        ('scyther', 123),
        ('scizor', 212)
    """)


def downgrade():
    # Drop new tables
    op.drop_table('collection_cards')
    op.drop_table('collection_rarities')
    op.drop_table('collection_pokemon')
    op.drop_table('collections')

    # Recreate old collection table
    op.create_table('collection',
        sa.Column('card_id', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('copies_owned', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['card_id'], ['cards.id']),
        sa.PrimaryKeyConstraint('card_id')
    )

    # Migrate data back
    op.execute("""
        INSERT INTO collection (card_id, status, copies_owned)
        SELECT card_id,
               CASE WHEN owned = 1 THEN 'OWNED'
                    WHEN wanted = 1 THEN 'WANTED'
                    ELSE 'WANTED' END,
               1
        FROM card_status
    """)

    op.drop_table('card_status')
