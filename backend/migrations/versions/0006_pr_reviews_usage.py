"""pull request reviews; token and latency accounting on AI answers

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-03
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('chat_messages', sa.Column('input_tokens', sa.Integer(), nullable=True))
    op.add_column('chat_messages', sa.Column('output_tokens', sa.Integer(), nullable=True))
    op.add_column('chat_messages', sa.Column('latency_ms', sa.Integer(), nullable=True))
    op.create_table(
        'pr_reviews',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('owner_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('repository_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('repositories.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('pr_number', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(300), nullable=False),
        sa.Column('pr_state', sa.String(10), nullable=False),
        sa.Column('base_sha', sa.String(40), nullable=False),
        sa.Column('head_sha', sa.String(40), nullable=False),
        sa.Column('base_analysis_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('analysis_jobs.id', ondelete='SET NULL')),
        sa.Column('head_analysis_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('analysis_jobs.id', ondelete='SET NULL')),
        sa.Column('status', sa.String(10), nullable=False, server_default='PENDING'),
        sa.Column('error_code', sa.String(48)),
        sa.Column('result', postgresql.JSONB(astext_type=sa.Text())),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('owner_id', 'repository_id', 'pr_number', 'base_sha', 'head_sha', name='uq_pr_review_identity'),
    )
    op.create_index('ix_pr_review_owner_created', 'pr_reviews', ['owner_id', 'created_at'])


def downgrade() -> None:
    op.drop_index('ix_pr_review_owner_created', table_name='pr_reviews')
    op.drop_table('pr_reviews')
    op.drop_column('chat_messages', 'latency_ms')
    op.drop_column('chat_messages', 'output_tokens')
    op.drop_column('chat_messages', 'input_tokens')
