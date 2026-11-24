"""ORM entities. PostgreSQL is the source of truth for jobs, artifacts and queue state."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text,
    UniqueConstraint, text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, new_id, utcnow

JOB_STATES = (
    "QUEUED", "FETCHING", "PARSING", "BUILDING_GRAPH", "GENERATING_DOCS", "READY",
    "RETRYING", "FAILED", "CANCELLED",
)
_STATE_LIST = ", ".join(f"'{s}'" for s in JOB_STATES)

TS = DateTime(timezone=True)


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(80))
    email_verified_at: Mapped[datetime | None] = mapped_column(TS)
    totp_secret: Mapped[str | None] = mapped_column(String(64))  # base32; only trusted once totp_enabled
    totp_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    totp_last_step: Mapped[int | None] = mapped_column(BigInteger)  # last accepted 30 s step (replay protection)
    role: Mapped[str] = mapped_column(String(10), nullable=False, default="user", server_default=text("'user'"))  # user | admin
    disabled_at: Mapped[datetime | None] = mapped_column(TS)  # abuse switch: set => cannot sign in or use the API
    disabled_reason: Mapped[str | None] = mapped_column(String(200))
    quota_analyses_day: Mapped[int | None] = mapped_column(Integer)  # per-user overrides of the daily defaults (null = default)
    quota_questions_day: Mapped[int | None] = mapped_column(Integer)
    quota_tokens_day: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TS, default=utcnow, onupdate=utcnow, nullable=False)


class AuthToken(Base):
    """Single-use secrets for email verification, password reset, the 2FA login step and recovery codes. Only SHA-256 digests are stored."""
    __tablename__ = "auth_tokens"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)  # verify_email | reset_password | mfa | recovery
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(TS)
    used_at: Mapped[datetime | None] = mapped_column(TS)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow, nullable=False)


class UserSession(Base):
    __tablename__ = "sessions"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(TS, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(TS)


class Repository(Base):
    __tablename__ = "repositories"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    provider: Mapped[str] = mapped_column(String(20), nullable=False, default="github")
    owner: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    full_name: Mapped[str] = mapped_column(String(320), nullable=False)
    full_name_lower: Mapped[str] = mapped_column(String(320), nullable=False)
    canonical_url: Mapped[str] = mapped_column(String(500), nullable=False)
    default_branch: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))
    primary_language: Mapped[str | None] = mapped_column(String(80))
    size_kb: Mapped[int | None] = mapped_column(Integer)
    stars: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TS, default=utcnow, onupdate=utcnow, nullable=False)
    __table_args__ = (UniqueConstraint("provider", "full_name_lower", name="uq_repository_identity"),)


class AnalysisJob(Base):
    __tablename__ = "analysis_jobs"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    repository_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("repositories.id", ondelete="RESTRICT"), nullable=False)
    commit_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    default_branch: Mapped[str] = mapped_column(String(255), nullable=False)
    analyzer_version: Mapped[str] = mapped_column(String(32), nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False, default="QUEUED")
    stage_detail: Mapped[str | None] = mapped_column(String(120))
    progress: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(48))
    error_message: Mapped[str | None] = mapped_column(String(300))
    error_retryable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    failed_state: Mapped[str | None] = mapped_column(String(24))
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retry_after: Mapped[datetime | None] = mapped_column(TS)
    graph_complete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    trigger_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_triggered_at: Mapped[datetime | None] = mapped_column(TS)
    dispatched_at: Mapped[datetime | None] = mapped_column(TS)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TS, default=utcnow, onupdate=utcnow, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(TS)
    finished_at: Mapped[datetime | None] = mapped_column(TS)

    repository: Mapped[Repository] = relationship(lazy="joined")

    __table_args__ = (
        CheckConstraint(f"state IN ({_STATE_LIST})", name="ck_analysis_state"),
        Index("ix_analysis_owner_created", "owner_id", "created_at"),
        Index("ix_analysis_state", "state"),
        Index(
            "uq_analysis_identity_active", "owner_id", "repository_id", "commit_sha", "analyzer_version",
            unique=True, postgresql_where=text("state <> 'CANCELLED'"),
        ),
        UniqueConstraint("idempotency_key", name="uq_analysis_idempotency_key"),
    )


class AnalysisTransition(Base):
    __tablename__ = "analysis_transitions"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    analysis_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("analysis_jobs.id", ondelete="CASCADE"), nullable=False)
    from_state: Mapped[str | None] = mapped_column(String(24))
    to_state: Mapped[str] = mapped_column(String(24), nullable=False)
    actor: Mapped[str] = mapped_column(String(24), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(48))
    note: Mapped[str | None] = mapped_column(String(200))
    at: Mapped[datetime] = mapped_column(TS, default=utcnow, nullable=False)
    __table_args__ = (Index("ix_transition_analysis_at", "analysis_id", "at"),)


class AnalysisFile(Base):
    __tablename__ = "analysis_files"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    analysis_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("analysis_jobs.id", ondelete="CASCADE"), nullable=False)
    path: Mapped[str] = mapped_column(String(1024), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # python | support | other
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # analyzed|parse_error|excluded|skipped_limit
    excluded_reason: Mapped[str | None] = mapped_column(String(32))
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    line_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content_sha256: Mapped[str | None] = mapped_column(String(64))
    content: Mapped[str | None] = mapped_column(Text)  # redacted; python + support files only
    has_secret_like: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    redaction_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    redaction_lines: Mapped[list[Any] | None] = mapped_column(JSONB)  # line numbers only; never the matched text
    parse_warning: Mapped[str | None] = mapped_column(String(300))
    facts: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    explanation: Mapped[str | None] = mapped_column(Text)
    explanation_source: Mapped[str | None] = mapped_column(String(16))  # ai | deterministic
    __table_args__ = (
        UniqueConstraint("analysis_id", "path", name="uq_file_path"),
        Index("ix_file_analysis_kind", "analysis_id", "kind"),
        Index("ix_file_analysis_status", "analysis_id", "status"),
        Index("ix_file_content_fts", text("to_tsvector('simple', coalesce(content, ''))"), postgresql_using="gin"),
    )


class CodeNode(Base):
    __tablename__ = "code_nodes"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    analysis_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("analysis_jobs.id", ondelete="CASCADE"), nullable=False)
    node_key: Mapped[str] = mapped_column(String(64), nullable=False)
    type: Mapped[str] = mapped_column(String(24), nullable=False)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    qualified_name: Mapped[str] = mapped_column(String(600), nullable=False)
    path: Mapped[str | None] = mapped_column(String(1024))
    start_line: Mapped[int | None] = mapped_column(Integer)
    end_line: Mapped[int | None] = mapped_column(Integer)
    facts: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    evidence: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    explanation: Mapped[str | None] = mapped_column(Text)
    explanation_source: Mapped[str | None] = mapped_column(String(16))
    search_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    embedding: Mapped[list[float] | None] = mapped_column(JSONB, deferred=True)  # optional semantic vector (see services/embeddings.py)
    __table_args__ = (
        UniqueConstraint("analysis_id", "node_key", name="uq_node_key"),
        Index("ix_node_analysis_type", "analysis_id", "type"),
        Index("ix_node_analysis_path", "analysis_id", "path"),
        Index("ix_node_analysis_qname", "analysis_id", "qualified_name"),
        Index("ix_node_search_fts", text("to_tsvector('simple', search_text)"), postgresql_using="gin"),
    )


class CodeEdge(Base):
    __tablename__ = "code_edges"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    analysis_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("analysis_jobs.id", ondelete="CASCADE"), nullable=False)
    edge_key: Mapped[str] = mapped_column(String(64), nullable=False)
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("code_nodes.id", ondelete="CASCADE"), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("code_nodes.id", ondelete="CASCADE"), nullable=False)
    relation: Mapped[str] = mapped_column(String(24), nullable=False)
    resolution: Mapped[str] = mapped_column(String(20), nullable=False)  # verified_static | inferred | unresolved
    evidence: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    label: Mapped[str | None] = mapped_column(String(200))
    __table_args__ = (
        UniqueConstraint("analysis_id", "edge_key", name="uq_edge_key"),
        CheckConstraint("resolution IN ('verified_static','inferred','unresolved')", name="ck_edge_resolution"),
        Index("ix_edge_analysis_relation", "analysis_id", "relation"),
        Index("ix_edge_source", "source_id"),
        Index("ix_edge_target", "target_id"),
    )


class Documentation(Base):
    __tablename__ = "documentation"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    analysis_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("analysis_jobs.id", ondelete="CASCADE"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")  # PENDING|GENERATING|READY|PARTIAL|FAILED
    ai_status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")  # pending|ok|partial|unavailable
    markdown: Mapped[str | None] = mapped_column(Text)
    diagrams: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    gaps: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    stats: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(48))
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    trigger_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_triggered_at: Mapped[datetime | None] = mapped_column(TS)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TS, default=utcnow, onupdate=utcnow, nullable=False)
    __table_args__ = (
        UniqueConstraint("analysis_id", "version", name="uq_doc_version"),
        UniqueConstraint("idempotency_key", name="uq_doc_idempotency"),
        Index("ix_doc_analysis_status", "analysis_id", "status"),
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    analysis_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("analysis_jobs.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[str] = mapped_column(String(12), nullable=False)  # user | assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)
    citations: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    evidence_sufficiency: Mapped[str | None] = mapped_column(String(16))
    limitations: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    answer_source: Mapped[str | None] = mapped_column(String(20))  # ai | retrieval_only
    model: Mapped[str | None] = mapped_column(String(80))  # model that produced an AI answer (after any fallback)
    input_tokens: Mapped[int | None] = mapped_column(Integer)  # AI answers only: tokens billed by the provider for this answer
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)  # wall time of the AI call(s), retries and fallback included
    commit_sha: Mapped[str | None] = mapped_column(String(40))  # repository commit the evidence (and so the answer) was taken from
    prompt_version: Mapped[str | None] = mapped_column(String(16))  # content hash of the prompt that produced it
    confidence: Mapped[str | None] = mapped_column(String(8))  # high | medium | low (evidence coverage, not a probability)
    inferred: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))  # claims not directly shown in cited code
    cache_hit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))  # answer served from answer_cache (no model call)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="complete")  # pending|complete|failed
    error_code: Mapped[str | None] = mapped_column(String(48))
    parent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    evidence: Mapped[list[Any] | None] = mapped_column(JSONB)  # retrieved evidence, internal only
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow, nullable=False)
    __table_args__ = (Index("ix_chat_analysis_created", "analysis_id", "created_at"),)


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    analysis_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("analysis_jobs.id", ondelete="CASCADE"), nullable=False)
    workflow_name: Mapped[str] = mapped_column(String(80), nullable=False)
    n8n_execution_id: Mapped[str] = mapped_column(String(80), nullable=False)
    stage: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")  # running|succeeded|failed
    error_code: Mapped[str | None] = mapped_column(String(48))
    started_at: Mapped[datetime] = mapped_column(TS, default=utcnow, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(TS)
    __table_args__ = (
        UniqueConstraint("analysis_id", "workflow_name", "n8n_execution_id", name="uq_workflow_run"),
        Index("ix_workflow_run_analysis", "analysis_id", "started_at"),
    )


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    actor_kind: Mapped[str] = mapped_column(String(16), nullable=False, default="user")
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(32))
    resource_id: Mapped[str | None] = mapped_column(String(64))
    request_id: Mapped[str | None] = mapped_column(String(64))
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    at: Mapped[datetime] = mapped_column(TS, default=utcnow, nullable=False)
    __table_args__ = (Index("ix_audit_actor_at", "actor_id", "at"), Index("ix_audit_action", "action"))


class WorkerTask(Base):
    """PostgreSQL-backed work queue (claimed with FOR UPDATE SKIP LOCKED + leases)."""
    __tablename__ = "worker_tasks"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    analysis_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("analysis_jobs.id", ondelete="CASCADE"), nullable=False)
    task_type: Mapped[str] = mapped_column(String(24), nullable=False)  # analysis | docs_explain | docs_assemble
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="pending")  # pending|running|done|failed
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    claimed_by: Mapped[str | None] = mapped_column(String(80))
    lease_expires_at: Mapped[datetime | None] = mapped_column(TS)
    error_code: Mapped[str | None] = mapped_column(String(48))
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TS, default=utcnow, onupdate=utcnow, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(TS)
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_task_idempotency"),
        Index("ix_task_status_created", "status", "created_at"),
    )


class CallbackReceipt(Base):
    """Idempotency receipts for internal callbacks (duplicate callbacks replay the stored response)."""
    __tablename__ = "callback_receipts"
    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    analysis_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("analysis_jobs.id", ondelete="CASCADE"), nullable=False)
    endpoint: Mapped[str] = mapped_column(String(40), nullable=False)
    response: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow, nullable=False)
    __table_args__ = (Index("ix_receipt_analysis", "analysis_id"),)


class RateLimitEvent(Base):
    __tablename__ = "rate_limit_events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    bucket: Mapped[str] = mapped_column(String(40), nullable=False)
    key: Mapped[str] = mapped_column(String(200), nullable=False)
    at: Mapped[datetime] = mapped_column(TS, default=utcnow, nullable=False)
    __table_args__ = (Index("ix_rate_bucket_key_at", "bucket", "key", "at"),)


class ImpactReport(Base):
    """Cached change-impact comparisons (GitHub compare API result mapped onto the analyzed graph)."""
    __tablename__ = "impact_reports"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    analysis_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("analysis_jobs.id", ondelete="CASCADE"), nullable=False)
    base_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    base_sha: Mapped[str | None] = mapped_column(String(40))
    head_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow, nullable=False)
    __table_args__ = (Index("ix_impact_analysis_created", "analysis_id", "created_at"),)


class PrReview(Base):
    """Evidence-backed review of one GitHub pull request: base and head commits are analysed like any other commit, then compared."""
    __tablename__ = "pr_reviews"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    repository_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("repositories.id", ondelete="RESTRICT"), nullable=False)
    pr_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    pr_state: Mapped[str] = mapped_column(String(10), nullable=False)  # open | closed | merged (as reported by GitHub when submitted)
    base_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    head_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    base_analysis_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("analysis_jobs.id", ondelete="SET NULL"))
    head_analysis_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("analysis_jobs.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="PENDING")  # PENDING | READY | FAILED
    error_code: Mapped[str | None] = mapped_column(String(48))
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TS, default=utcnow, onupdate=utcnow, nullable=False)
    __table_args__ = (UniqueConstraint("owner_id", "repository_id", "pr_number", "base_sha", "head_sha", name="uq_pr_review_identity"),
                      Index("ix_pr_review_owner_created", "owner_id", "created_at"))


class AdminEvent(Base):
    """Append-only audit trail of administrator actions."""
    __tablename__ = "admin_events"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    admin_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    target_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow, nullable=False)
    __table_args__ = (Index("ix_admin_event_created", "created_at"),)


class AnswerCache(Base):
    """Validated AI answers keyed by (repository, commit, analyzer, prompt, model, normalised question). Commits are immutable, so entries never go stale."""
    __tablename__ = "answer_cache"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    repository_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # tokens the original call cost: what each hit saves
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    hits: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow, nullable=False)
    last_hit_at: Mapped[datetime | None] = mapped_column(TS)


class EmbeddingCache(Base):
    """Question embeddings keyed by (model, normalised text): repeated or re-asked questions skip the embeddings endpoint."""
    __tablename__ = "embedding_cache"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    vector: Mapped[list[float]] = mapped_column(JSONB, nullable=False)
    hits: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow, nullable=False)
