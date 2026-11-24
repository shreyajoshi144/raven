"""Bounded, streaming reader for GitHub tarballs. Nothing is extracted to disk or executed."""
from __future__ import annotations

import io
import re
import tarfile
import time
import zlib
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from hashlib import sha256

from app.analysis.filters import InventoryStats, classify_path, count_lines, is_safe_member_path, looks_binary, looks_generated, looks_minified
from app.analysis.secrets import redact_secrets
from app.core.errors import JobError

_ENV_NAME = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=", re.M)
SUPPORT_MAX_BYTES = 256 * 1024
SUPPORT_STORE_CHARS = 64 * 1024


@dataclass
class Limits:
    max_files: int = 2000
    max_file_bytes: int = 1024 * 1024
    max_total_bytes: int = 20 * 1024 * 1024
    max_python_files: int = 1000
    max_archive_bytes: int = 60 * 1024 * 1024
    max_uncompressed_bytes: int = 400 * 1024 * 1024
    max_web_files: int = 300
    max_web_file_bytes: int = 256 * 1024
    max_web_total_bytes: int = 5 * 1024 * 1024


@dataclass
class ArchiveEntry:
    path: str
    kind: str  # python | support | other
    status: str  # analyzed | excluded | skipped_limit
    size: int
    excluded_reason: str | None = None
    content: str | None = None
    line_count: int = 0
    sha256: str | None = None
    has_secret_like: bool = False
    redaction_count: int = 0
    redaction_lines: list[int] = field(default_factory=list)


@dataclass
class ArchiveResult:
    entries: list[ArchiveEntry] = field(default_factory=list)
    stats: InventoryStats = field(default_factory=InventoryStats)
    warnings: list[str] = field(default_factory=list)
    partial: bool = False
    partial_reasons: list[str] = field(default_factory=list)


class _Decompressor(io.RawIOBase):
    """File-like object producing decompressed bytes from gzip chunks with an output cap."""

    def __init__(self, chunks: Iterator[bytes], max_out: int):
        self._chunks = chunks
        self._d = zlib.decompressobj(16 + zlib.MAX_WBITS)
        self._buf = bytearray()
        self._out = 0
        self._max = max_out
        self._eof = False
        self.truncated = False

    def readable(self) -> bool:
        return True

    def _fill(self, want: int) -> None:
        while len(self._buf) < want and not self._eof:
            pending = self._d.unconsumed_tail
            if not pending:
                try:
                    pending = next(self._chunks)
                except StopIteration:
                    self._eof = True
                    self._buf += self._d.flush()
                    return
            try:
                out = self._d.decompress(pending, 1 << 20)
            except zlib.error as exc:
                raise JobError("ARCHIVE_INVALID", f"zlib: {exc}") from None
            self._out += len(out)
            if self._out > self._max:
                self.truncated = True
                self._eof = True
                raise JobError("ARCHIVE_INVALID", "decompressed size limit exceeded")
            self._buf += out
            if self._d.eof:
                self._eof = True

    def read(self, n: int = -1) -> bytes:  # type: ignore[override]
        if n is None or n < 0:
            n = 1 << 20
        self._fill(n)
        data = bytes(self._buf[:n])
        del self._buf[:n]
        return data


def _capped(chunks: Iterable[bytes], limit: int, state: dict[str, bool]) -> Iterator[bytes]:
    total = 0
    for chunk in chunks:
        total += len(chunk)
        if total > limit:
            state["truncated"] = True
            return
        yield chunk


def env_template_text(raw: str) -> tuple[str, int]:
    names = []
    for m in _ENV_NAME.finditer(raw):
        if m.group(1) not in names:
            names.append(m.group(1))
    return "\n".join(f"{n}=" for n in names[:300]) + ("\n" if names else ""), len(names)


def read_archive(chunks: Iterable[bytes], limits: Limits, deadline: float | None = None) -> ArchiveResult:
    """Read a gzip tarball stream, enforcing resource limits. Raises JobError(ARCHIVE_INVALID|ANALYSIS_TIMEOUT)."""
    res = ArchiveResult()
    state = {"truncated": False}
    stream = _Decompressor(_capped(chunks, limits.max_archive_bytes, state), limits.max_uncompressed_bytes)
    try:
        tar = tarfile.open(fileobj=stream, mode="r|")  # type: ignore[call-overload]
    except (tarfile.TarError, EOFError) as exc:
        raise JobError("ARCHIVE_INVALID", str(exc)) from None
    seen_files = 0
    try:
        for member in tar:
            if deadline is not None and time.monotonic() > deadline:
                raise JobError("ANALYSIS_TIMEOUT", "deadline reached while reading archive")
            if not member.isfile():
                continue  # directories, symlinks, hardlinks, devices are never followed
            name = member.name
            if "/" not in name:
                continue
            path = name.split("/", 1)[1]
            if not is_safe_member_path(path):
                res.stats.exclude("unsafe_path")
                continue
            seen_files += 1
            if seen_files > limits.max_files:
                res.partial = True
                res.partial_reasons.append(f"File limit of {limits.max_files} reached; remaining files were not inspected")
                break
            res.stats.considered += 1
            _handle_member(tar, member, path, limits, res)
    except JobError:
        raise
    except (tarfile.TarError, EOFError, OSError) as exc:
        if state["truncated"]:
            res.partial = True
            res.partial_reasons.append(f"Archive exceeded {limits.max_archive_bytes // (1024 * 1024)} MiB; the rest was not read")
        else:
            raise JobError("ARCHIVE_INVALID", str(exc)) from None
    if state["truncated"] and not any("Archive exceeded" in r for r in res.partial_reasons):
        res.partial = True
        res.partial_reasons.append(f"Archive exceeded {limits.max_archive_bytes // (1024 * 1024)} MiB; the rest was not read")
    res.warnings.extend(res.partial_reasons)
    return res


def _handle_member(tar: tarfile.TarFile, member: tarfile.TarInfo, path: str, limits: Limits, res: ArchiveResult) -> None:
    st = res.stats
    decision = classify_path(path)
    size = member.size
    if decision.kind == "excluded":
        st.exclude(decision.reason or "excluded")
        res.entries.append(ArchiveEntry(path, "other", "excluded", size, decision.reason))
        return
    if decision.kind == "other":
        res.entries.append(ArchiveEntry(path, "other", "analyzed", size))
        return

    if decision.kind == "python":
        st.python_found += 1
        if size > limits.max_file_bytes:
            st.exclude("too_large")
            res.entries.append(ArchiveEntry(path, "python", "skipped_limit", size, "too_large"))
            res.partial_reasons.append("One or more Python files exceed the per-file size limit and were skipped") if not any(
                "per-file size" in r for r in res.partial_reasons) else None
            return
        if st.python_analyzed >= limits.max_python_files:
            st.exclude("python_file_limit")
            res.entries.append(ArchiveEntry(path, "python", "skipped_limit", size, "python_file_limit"))
            res.partial = True
            if not any("Python file limit" in r for r in res.partial_reasons):
                res.partial_reasons.append(f"Python file limit of {limits.max_python_files} reached; additional files were skipped")
            return
        if st.total_source_bytes + size > limits.max_total_bytes:
            st.exclude("total_size_limit")
            res.entries.append(ArchiveEntry(path, "python", "skipped_limit", size, "total_size_limit"))
            res.partial = True
            if not any("aggregate source" in r for r in res.partial_reasons):
                res.partial_reasons.append("Aggregate source size limit reached; additional files were skipped")
            return
    elif decision.kind == "web":
        st.web_found += 1
        reason = None
        if size > limits.max_web_file_bytes:
            reason = "too_large"
        elif st.web_analyzed >= limits.max_web_files:
            reason = "web_file_limit"
        elif st.web_bytes + size > limits.max_web_total_bytes:
            reason = "web_total_size_limit"
        if reason:
            st.exclude(reason)
            res.entries.append(ArchiveEntry(path, "web", "skipped_limit", size, reason))
            res.partial = True
            msg = {"too_large": "One or more frontend files exceed the per-file size limit and were skipped", "web_file_limit": f"Frontend file limit of {limits.max_web_files} reached; additional files were skipped",
                   "web_total_size_limit": "Aggregate frontend source size limit reached; additional files were skipped"}[reason]
            if msg not in res.partial_reasons:
                res.partial_reasons.append(msg)
            return
    else:  # support / env_template
        if size > SUPPORT_MAX_BYTES:
            st.exclude("too_large")
            res.entries.append(ArchiveEntry(path, "other", "excluded", size, "too_large"))
            return

    fobj = tar.extractfile(member)
    data = fobj.read(size + 1) if fobj else b""
    if looks_binary(data):
        st.exclude("binary")
        res.entries.append(ArchiveEntry(path, "other", "excluded", size, "binary"))
        return
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        st.exclude("binary")
        res.entries.append(ArchiveEntry(path, "other", "excluded", size, "binary"))
        return
    if text.startswith("\ufeff"):
        text = text[1:]
    if decision.kind == "web" and (looks_minified(text) or looks_generated(text)):
        st.exclude("generated")
        res.entries.append(ArchiveEntry(path, "web", "excluded", size, "generated"))
        return
    if decision.kind == "python" and looks_generated(text):
        st.exclude("generated")
        res.entries.append(ArchiveEntry(path, "python", "excluded", size, "generated"))
        return

    if decision.kind == "env_template":
        content, n = env_template_text(text)
        res.entries.append(ArchiveEntry(path, "support", "analyzed", size, content=content, line_count=n, sha256=sha256(data).hexdigest()))
        return

    red = redact_secrets(text)
    content = red.text
    if decision.kind == "support":
        content = content[:SUPPORT_STORE_CHARS]
    entry = ArchiveEntry(
        path, decision.kind if decision.kind in ("python", "web") else "support", "analyzed", size, content=content,
        line_count=count_lines(content), sha256=sha256(data).hexdigest(), has_secret_like=red.high_confidence,
        redaction_count=red.count, redaction_lines=red.lines,
    )
    if decision.kind == "web":
        st.web_analyzed += 1
        st.web_bytes += size
    if decision.kind == "python":
        st.python_analyzed += 1
        st.total_source_bytes += size
    res.entries.append(entry)
