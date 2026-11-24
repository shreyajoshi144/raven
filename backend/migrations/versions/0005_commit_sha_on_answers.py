"""commit SHA recorded on every chat message (answer provenance)

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-02
"""
from alembic import op
import sqlalchemy as sa

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('chat_messages', sa.Column('commit_sha', sa.String(length=40), nullable=True))
    # existing messages belong to the analysis they were asked on, which is pinned to one commit
    op.execute("UPDATE chat_messages m SET commit_sha = j.commit_sha FROM analysis_jobs j WHERE j.id = m.analysis_id")


def downgrade() -> None:
    op.drop_column('chat_messages', 'commit_sha')
