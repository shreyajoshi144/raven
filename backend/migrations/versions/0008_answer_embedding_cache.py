"""answer cache and question-embedding cache

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-07
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('chat_messages', sa.Column('cache_hit', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table(
        'answer_cache',
        sa.Column('key', sa.String(64), primary_key=True),
        sa.Column('repository_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('repositories.id', ondelete='CASCADE'), nullable=False),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('input_tokens', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('output_tokens', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('hits', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_hit_at', sa.DateTime(timezone=True)),
    )
    op.create_index('ix_answer_cache_repository_id', 'answer_cache', ['repository_id'])
    op.create_table(
        'embedding_cache',
        sa.Column('key', sa.String(64), primary_key=True),
        sa.Column('vector', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('hits', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('embedding_cache')
    op.drop_index('ix_answer_cache_repository_id', table_name='answer_cache')
    op.drop_table('answer_cache')
    op.drop_column('chat_messages', 'cache_hit')
