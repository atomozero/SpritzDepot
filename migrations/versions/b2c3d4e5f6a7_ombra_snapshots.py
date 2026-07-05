"""ombra_snapshots: prefetched github-latest resolutions

The ombra crawler resolves each github-latest app's newest release once and
stores the result here, so /resolve, /library/pending and app-page badges serve
from the DB (snapshot-first, live-fallback) instead of hitting the GitHub API on
every request. One row per app.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
"""
from alembic import op
import sqlalchemy as sa
import sqlmodel


revision = 'b2c3d4e5f6a7'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'ombra_snapshots',
        sa.Column('cicheto_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('repo', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('match', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('prerelease', sa.Boolean(), nullable=False),
        sa.Column('version', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('artifacts', sa.JSON(), nullable=True),
        sa.Column('resolved_at', sa.DateTime(), nullable=False),
        sa.Column('error', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.PrimaryKeyConstraint('cicheto_id'),
    )
    with op.batch_alter_table('ombra_snapshots', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_ombra_snapshots_resolved_at'),
                              ['resolved_at'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('ombra_snapshots', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_ombra_snapshots_resolved_at'))
    op.drop_table('ombra_snapshots')
