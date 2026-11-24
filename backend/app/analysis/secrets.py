"""Best-effort secret screening and redaction.

Screening is heuristic and NOT perfect detection; public repositories may contain
accidentally committed secrets that these patterns do not recognize.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

REDACTED = "[REDACTED]"

# High-confidence token formats: a hit marks the whole file as secret-bearing.
_HIGH_CONFIDENCE = [
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{22,}\b"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"),
    re.compile(r"\b(?:sk|rk)_live_[0-9a-zA-Z]{16,}\b"),
    re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}\b"),
    re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{40,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    re.compile(r"\b[a-z]+://[^\s:/@'\"]+:[^\s@'\"/]{6,}@[^\s'\"]+"),  # URL with embedded password
]
_PEM_BEGIN = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
_PEM_END = re.compile(r"-----END [A-Z ]*PRIVATE KEY-----")

# Medium confidence: quoted literal assigned to a secret-looking name. Value is redacted in place.
_ASSIGN = re.compile(
    r"""(?ix)
    (?P<pre>\b[\w.]*(?:password|passwd|secret|api[_-]?key|auth[_-]?token|access[_-]?token|private[_-]?key|client[_-]?secret)[\w]*
        ["']?\s*[:=]\s*)
    (?P<q>["'])(?P<val>[^"'\s]{8,})(?P=q)
    """
)
_PLACEHOLDER = re.compile(
    r"(?i)^(your[-_ ]|my[-_ ]|example|sample|test|dummy|placeholder|changeme|change[-_]me|replace|insert|xxx|\*{3,}|<|\$\{|%\(|none$|null$|secret$|password$)"
)


@dataclass
class RedactionResult:
    text: str
    count: int
    high_confidence: bool
    lines: list[int] = field(default_factory=list)


def redact_secrets(text: str) -> RedactionResult:
    """Return text with likely secrets replaced. Line count and line numbers are preserved."""
    out: list[str] = []
    count = 0
    high = False
    in_pem = False
    hit_lines: list[int] = []
    for lineno, line in enumerate(text.split("\n"), 1):
        before = count
        if in_pem:
            count += 1
            if _PEM_END.search(line):
                in_pem = False
            out.append("# " + REDACTED + " (private key material)")
            if len(hit_lines) < 50 and (not hit_lines or hit_lines[-1] != lineno):
                hit_lines.append(lineno)
            continue
        if _PEM_BEGIN.search(line):
            high = True
            count += 1
            in_pem = not _PEM_END.search(line)
            out.append("# " + REDACTED + " (private key material)")
            if len(hit_lines) < 50:
                hit_lines.append(lineno)
            continue
        new = line
        for pat in _HIGH_CONFIDENCE:
            new, n = pat.subn(REDACTED, new)
            if n:
                high = True
                count += n

        def _sub(m: re.Match[str]) -> str:
            nonlocal count
            val = m.group("val")
            if _PLACEHOLDER.match(val) or val.startswith("os.") or "environ" in val:
                return m.group(0)
            count += 1
            q = m.group("q")
            return f"{m.group('pre')}{q}{REDACTED}{q}"

        new = _ASSIGN.sub(_sub, new)
        if count > before and len(hit_lines) < 50:
            hit_lines.append(lineno)
        out.append(new)
    return RedactionResult("\n".join(out), count, high, hit_lines)


def scrub_text(text: str, limit: int = 2000) -> str:
    """Redact and bound a short free-text value (docstrings, log fields, model output)."""
    return redact_secrets(text[: limit * 2]).text[:limit]
