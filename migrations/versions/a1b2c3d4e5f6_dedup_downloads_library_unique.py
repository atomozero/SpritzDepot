"""dedup_key + downloads + library unique + users.is_admin

These schema changes shipped after the initial revision but were only ever
applied via create_all (which does not ALTER existing tables) and a one-off
SQLite script, so a fresh alembic deploy (or a Postgres one) was missing them.
This revision brings the alembic history in line with the models.

Revision ID: a1b2c3d4e5f6
Revises: 126d255d8b9c
"""
from alembic import op
import sqlalchemy as sa
import sqlmodel


revision = 'a1b2c3d4e5f6'
down_revision = '126d255d8b9c'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. cicheti.dedup_key: normalized name for grouping the same app across
    #    repos, indexed for WHERE dedup_key = ? lookups.
    with op.batch_alter_table('cicheti', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('dedup_key', sqlmodel.sql.sqltypes.AutoString(),
                      nullable=False, server_default=''))
        batch_op.create_index(batch_op.f('ix_cicheti_dedup_key'),
                              ['dedup_key'], unique=False)

    # 2. downloads: the append-only download-event log behind the "most
    #    downloaded" ranking.
    op.create_table(
        'downloads',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('cicheto_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('channel', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('arch', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('kind', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('downloads', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_downloads_cicheto_id'),
                              ['cicheto_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_downloads_kind'),
                              ['kind'], unique=False)
        batch_op.create_index(batch_op.f('ix_downloads_created_at'),
                              ['created_at'], unique=False)

    # 3. library: one row per (user, app), so a double-queue upserts instead of
    #    creating duplicate pending rows.
    with op.batch_alter_table('library', schema=None) as batch_op:
        batch_op.create_unique_constraint(
            'uq_library_user_cicheto', ['user_id', 'cicheto_id'])

    # 4. users.is_admin: the admin-bootstrap flag.
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('is_admin', sa.Boolean(), nullable=False,
                      server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('is_admin')

    with op.batch_alter_table('library', schema=None) as batch_op:
        batch_op.drop_constraint('uq_library_user_cicheto', type_='unique')

    with op.batch_alter_table('downloads', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_downloads_created_at'))
        batch_op.drop_index(batch_op.f('ix_downloads_kind'))
        batch_op.drop_index(batch_op.f('ix_downloads_cicheto_id'))
    op.drop_table('downloads')

    with op.batch_alter_table('cicheti', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_cicheti_dedup_key'))
        batch_op.drop_column('dedup_key')
