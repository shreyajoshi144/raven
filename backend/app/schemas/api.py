from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class RegisterBody(_Strict):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=256)
    display_name: str | None = Field(default=None, max_length=80)


class LoginBody(_Strict):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=256)


class EmailBody(_Strict):
    email: str = Field(min_length=3, max_length=320)


class TokenBody(_Strict):
    token: str = Field(min_length=10, max_length=200)


class ResetPasswordBody(_Strict):
    token: str = Field(min_length=10, max_length=200)
    password: str = Field(min_length=1, max_length=256)


class MfaLoginBody(_Strict):
    mfa_token: str = Field(min_length=10, max_length=200)
    code: str = Field(min_length=6, max_length=20)


class CodeBody(_Strict):
    code: str = Field(min_length=6, max_length=20)


class DisableMfaBody(_Strict):
    password: str = Field(min_length=1, max_length=256)
    code: str = Field(min_length=6, max_length=20)


class CreateAnalysisBody(_Strict):
    url: str = Field(min_length=1, max_length=300)


class PrReviewBody(_Strict):
    url: str = Field(min_length=1, max_length=300)


class ChatBody(_Strict):
    message: str = Field(min_length=1, max_length=2000)


class DispatchBody(_Strict):
    kind: str = Field(pattern="^(analysis|docs_explain|docs_assemble)$")
    workflow: str = Field(min_length=1, max_length=80)
    execution_id: str = Field(min_length=1, max_length=80)
    idempotency_key: str | None = Field(default=None, max_length=200)
    doc_id: str | None = Field(default=None, max_length=40)


class StageResultBody(_Strict):
    stage: str = Field(min_length=1, max_length=40)
    workflow: str = Field(min_length=1, max_length=80)
    execution_id: str = Field(min_length=1, max_length=80)
    idempotency_key: str | None = Field(default=None, max_length=200)


class CompleteBody(_Strict):
    doc_id: str = Field(max_length=40)
    workflow: str = Field(min_length=1, max_length=80)
    execution_id: str = Field(min_length=1, max_length=80)
    idempotency_key: str | None = Field(default=None, max_length=200)


class FailBody(_Strict):
    error_code: str = Field(min_length=1, max_length=48)
    stage: str = Field(min_length=1, max_length=40)
    workflow: str = Field(min_length=1, max_length=80)
    execution_id: str = Field(min_length=1, max_length=80)
    idempotency_key: str | None = Field(default=None, max_length=200)
    doc_id: str | None = Field(default=None, max_length=40)


class QaRetrieveBody(_Strict):
    analysis_id: str = Field(max_length=40)
    message_id: str = Field(max_length=40)
    execution_id: str = Field(min_length=1, max_length=80)


class QaAnswerBody(_Strict):
    analysis_id: str = Field(max_length=40)
    message_id: str = Field(max_length=40)
    execution_id: str = Field(min_length=1, max_length=80)


class ImpactBody(_Strict):
    base: str | None = Field(default=None, max_length=200)
