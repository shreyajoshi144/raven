"""optional node embeddings; model and prompt version on chat messages

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-01
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('code_nodes', sa.Column('embedding', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('chat_messages', sa.Column('model', sa.String(length=80), nullable=True))
    op.add_column('chat_messages', sa.Column('prompt_version', sa.String(length=16), nullable=True))


def downgrade() -> None:
    op.drop_column('chat_messages', 'prompt_version')
    op.drop_column('chat_messages', 'model')
    op.drop_column('code_nodes', 'embedding')
