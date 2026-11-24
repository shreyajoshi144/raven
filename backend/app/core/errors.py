"""Stable error codes, safe messages and retry classification."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ErrorInfo:
    code: str
    message: str
    retryable: bool
    http_status: int = 400


def _e(code: str, message: str, retryable: bool = False, http_status: int = 400) -> tuple[str, ErrorInfo]:
    return code, ErrorInfo(code, message, retryable, http_status)


ERRORS: dict[str, ErrorInfo] = dict(
    [
        # request / auth
        _e("VALIDATION_ERROR", "The request was not valid.", False, 422),
        _e("INVALID_REPOSITORY_URL", "Enter a public GitHub repository URL like https://github.com/owner/repo.", False, 422),
        _e("UNAUTHENTICATED", "Sign in to continue.", False, 401),
        _e("INVALID_CREDENTIALS", "Email or password is incorrect.", False, 401),
        _e("FORBIDDEN", "You do not have access to this resource.", False, 403),
        _e("CSRF_FAILED", "Request origin could not be verified. Reload the page and try again.", False, 403),
        _e("NOT_FOUND", "The requested resource was not found.", False, 404),
        _e("CONFLICT", "The request conflicts with the current state.", False, 409),
        _e("EMAIL_NOT_VERIFIED", "Verify your email address first. Check your inbox, or request a new link.", False, 403),
        _e("TOKEN_INVALID", "This link or code is invalid or has expired.", False, 400),
        _e("MFA_CODE_INVALID", "That code is incorrect or was already used.", False, 401),
        _e("MFA_STATE", "Two-factor authentication is not in the right state for this action.", False, 409),
        _e("EMAIL_TAKEN", "An account with this email already exists.", False, 409),
        _e("REGISTRATION_DISABLED", "Registration is disabled on this instance.", False, 403),
        _e("PAYLOAD_TOO_LARGE", "The request body is too large.", False, 413),
        _e("ACCOUNT_DISABLED", "This account has been disabled. Contact the administrator.", False, 403),
        _e("QUOTA_EXCEEDED", "You have reached today's usage limit. It resets at 00:00 UTC.", False, 429),
        _e("RATE_LIMITED", "Too many requests. Please wait and try again.", True, 429),
        _e("INVALID_STATE", "This action is not allowed in the current analysis state.", False, 409),
        _e("INTERNAL_ERROR", "An unexpected error occurred.", True, 500),
        _e("SERVICE_UNAVAILABLE", "A required service is temporarily unavailable.", True, 503),
        _e("WORKFLOW_UNAVAILABLE", "The automation service is unavailable. Try again shortly.", True, 503),
        _e("WORKFLOW_FAILED", "The automation workflow did not complete.", True, 502),
        # github
        _e("PR_FORK_UNSUPPORTED", "Pull requests from forks are not supported yet: the head commit lives in another repository.", False, 422),
        _e("PR_ANALYSIS_FAILED", "The base or head commit of this pull request could not be analyzed.", False, 502),
        _e("REPO_NOT_FOUND", "Repository not found. Raven can only analyze public GitHub repositories.", False, 404),
        _e("REPO_NOT_PUBLIC", "This repository is not public. Raven only analyzes public repositories.", False, 422),
        _e("REPO_UNAVAILABLE", "GitHub reports this repository is unavailable.", False, 422),
        _e("REPO_FORBIDDEN", "GitHub denied access to this repository.", False, 422),
        _e("REPO_TOO_LARGE", "This repository exceeds the configured size limit.", False, 422),
        _e("GITHUB_RATE_LIMITED", "GitHub rate limit reached. Try again later.", True, 503),
        _e("GITHUB_UNAVAILABLE", "GitHub is temporarily unavailable.", True, 503),
        _e("GITHUB_TIMEOUT", "GitHub did not respond in time.", True, 503),
        _e("GITHUB_BAD_RESPONSE", "GitHub returned an unexpected response.", False, 502),
        _e("REF_NOT_FOUND", "That commit or branch was not found in this repository.", False, 404),
        _e("INVALID_REF", "Enter a commit SHA or branch name (letters, digits, . _ - / only).", False, 422),
        _e("ARCHIVE_INVALID", "The repository archive could not be read.", False, 422),
        # analysis
        _e("ANALYSIS_TIMEOUT", "Analysis exceeded the configured time limit.", False, 422),
        _e("ANALYSIS_CANCELLED", "Analysis was cancelled.", False, 409),
        _e("NO_PYTHON_FILES", "No analyzable Python source files were found in this repository.", False, 422),
        _e("WORKER_LOST", "The analysis worker stopped unexpectedly.", True, 500),
        _e("ORCHESTRATOR_UNAVAILABLE", "The automation service could not be reached to start this analysis.", True, 503),
        _e("WORKFLOW_TIMEOUT", "The workflow did not finish in time.", True, 504),
        _e("RETRIES_EXHAUSTED", "A transient error persisted after the maximum number of attempts.", True, 503),
        _e("INTERNAL_ANALYSIS_ERROR", "Analysis failed because of an internal error.", True, 500),
        # llm
        _e("LLM_NOT_CONFIGURED", "The language model provider is not configured.", False, 503),
        _e("LLM_AUTH_FAILED", "The language model provider rejected the configured credentials.", False, 503),
        _e("LLM_QUOTA_EXHAUSTED", "The language model provider account has no remaining quota or credit.", False, 503),
        _e("LLM_RATE_LIMITED", "The language model provider rate limit was reached.", True, 503),
        _e("LLM_TIMEOUT", "The language model provider did not respond in time.", True, 503),
        _e("LLM_PROVIDER_UNAVAILABLE", "The language model provider is temporarily unavailable.", True, 503),
        _e("LLM_MALFORMED_OUTPUT", "The language model returned output that failed validation.", False, 502),
        _e("LLM_BUDGET_EXCEEDED", "The language model call budget for this analysis was reached.", False, 422),
    ]
)


def info(code: str) -> ErrorInfo:
    return ERRORS.get(code) or ERRORS["INTERNAL_ERROR"]


def is_retryable(code: str) -> bool:
    return info(code).retryable


class ApiError(Exception):
    def __init__(self, code: str, message: str | None = None, *, status: int | None = None,
                 retryable: bool | None = None, headers: dict[str, str] | None = None):
        meta = info(code)
        self.code = meta.code if code in ERRORS else code
        self.message = message or meta.message
        self.status = status or meta.http_status
        self.retryable = meta.retryable if retryable is None else retryable
        self.headers = headers or {}
        super().__init__(self.message)


class JobError(Exception):
    """Raised by worker/service code. Carries a stable code; messages are always safe."""

    def __init__(self, code: str, detail: str = "", retry_after: float | None = None):
        self.code = code
        self.detail = detail  # internal only, never returned to clients
        self.retry_after = retry_after
        self.retryable = is_retryable(code)
        super().__init__(code)
