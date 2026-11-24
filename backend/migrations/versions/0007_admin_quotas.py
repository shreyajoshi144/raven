"""admin role, abuse switch, per-user quota overrides, admin audit trail

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-07
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('role', sa.String(10), nullable=False, server_default='user'))
    op.add_column('users', sa.Column('disabled_at', sa.DateTime(timezone=True)))
    op.add_column('users', sa.Column('disabled_reason', sa.String(200)))
    for c in ('quota_analyses_day', 'quota_questions_day', 'quota_tokens_day'):
        op.add_column('users', sa.Column(c, sa.Integer()))
    op.create_table(
        'admin_events',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('admin_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL')),
        sa.Column('action', sa.String(40), nullable=False),
        sa.Column('target_user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL')),
        sa.Column('detail', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_admin_event_created', 'admin_events', ['created_at'])


def downgrade() -> None:
    op.drop_index('ix_admin_event_created', table_name='admin_events')
    op.drop_table('admin_events')
    for c in ('quota_tokens_day', 'quota_questions_day', 'quota_analyses_day', 'disabled_reason', 'disabled_at', 'role'):
        op.drop_column('users', c)
