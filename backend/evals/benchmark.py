"""Benchmark manifest + ground truth: schema, loading and consistency validation.

The JSON files under benchmarks/<version>/ are the source of truth. Validation catches stale labels: every evidence span must
lie inside its file and contain its anchor text, every referenced path must exist, and impact expectations must equal the
closure over the labelled import edges.
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ROOT = Path(__file__).resolve().parent / "benchmarks"
TOOL_CACHE_DIRS = {"__pycache__", ".ruff_cache", ".pytest_cache", ".mypy_cache"}  # local tool output, never benchmark content


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Span(_M):
    path: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    anchor: str = ""


class Route(_M):
    method: str
    path: str
    handler_file: str
    decorator_line: int
    def_line: int
    dynamic_prefix: str | None = None


class Named(_M):
    name: str
    path: str
    line: int


class LabelSet(_M):
    exhaustive: bool
    items: list
    notes: str | None = None
    semantics: str | None = None


class GraphTruth(_M):
    routes: LabelSet
    data_models: LabelSet
    orm_models: LabelSet
    internal_imports: LabelSet
    entry_points: LabelSet


class QAItem(_M):
    id: str
    category: str
    question: str
    answerable: bool
    expected_answer: str
    key_facts: list[list[str]]  # all groups must match; any alternative within a group (case-insensitive substring)
    evidence: list[Span]


class ExpectedFinding(_M):
    rule: str
    evidence: list[Span]


class ReadinessTruth(_M):
    assessed_rules: list[str]
    expected: list[ExpectedFinding]
    notes: str | None = None


class ChangedFile(_M):
    path: str
    status: Literal["added", "modified", "removed", "renamed"]
    additions: int = 0
    deletions: int = 0


class ImpactCase(_M):
    id: str
    description: str
    changed: list[ChangedFile]
    expected: dict[str, LabelSet]


class Verification(_M):
    method: str
    by: str
    date: str
    independent_review: bool
    anchors: str


class GroundTruth(_M):
    repo: str
    verification: Verification
    graph: GraphTruth
    qa: list[QAItem]
    readiness: ReadinessTruth
    impact: list[ImpactCase]


class Upstream(_M):
    url: str
    commit: str
    subset: str
    license: str


class RepoEntry(_M):
    id: str
    kind: Literal["hermetic", "real"]
    full_name: str
    source_dir: str
    ground_truth: str
    content_sha256: str
    description: str
    upstream: Upstream | None = None


class Manifest(_M):
    name: str
    version: str
    created: str
    description: str
    repos: list[RepoEntry]
    smoke_repos: list[str]


class Benchmark:
    def __init__(self, version: str = "v1", root: Path = ROOT):
        self.dir = root / version
        self.manifest = Manifest.model_validate_json((self.dir / "benchmark.json").read_text())
        self.truth = {r.id: GroundTruth.model_validate_json((self.dir / r.ground_truth).read_text()) for r in self.manifest.repos}

    def repo(self, rid: str) -> RepoEntry:
        return next(r for r in self.manifest.repos if r.id == rid)

    def source_dir(self, rid: str) -> Path:
        return self.dir / self.repo(rid).source_dir

    def files(self, rid: str) -> dict[str, bytes]:
        return read_tree(self.source_dir(rid))

    def fingerprint(self) -> str:
        """Hash of the manifest, every label file and every source file (not documentation), so a results file names exactly what it was scored against."""
        h = hashlib.sha256()
        for p in sorted(self.dir.rglob("*")):
            rel = p.relative_to(self.dir)
            if p.is_file() and rel.parts[0] in ("benchmark.json", "ground_truth", "repos") and not TOOL_CACHE_DIRS & set(rel.parts):
                h.update(str(p.relative_to(self.dir)).encode() + b"\0" + hashlib.sha256(p.read_bytes()).digest())
        return h.hexdigest()


def read_tree(base: Path) -> dict[str, bytes]:
    out = {}
    for p in sorted(base.rglob("*")):
        if p.is_file() and p.name != "PROVENANCE.md" and not TOOL_CACHE_DIRS & set(p.relative_to(base).parts):
            out[str(p.relative_to(base).as_posix())] = p.read_bytes()
    return out


def content_sha256(files: dict[str, bytes]) -> str:
    """Stable hash over sorted `path\\0sha256(content)\\n` lines (independent of archive byte layout)."""
    h = hashlib.sha256()
    for path in sorted(files):
        h.update(path.encode() + b"\0" + hashlib.sha256(files[path]).hexdigest().encode() + b"\n")
    return h.hexdigest()


def is_test_path(path: str) -> bool:
    p = PurePosixPath(path)
    return any(part in {"tests", "test"} for part in p.parts[:-1]) or p.name.startswith("test_") or p.name.endswith("_test.py") or p.name == "conftest.py"


def is_test_file(path: str) -> bool:
    """A file that contains tests (fixtures/helpers such as conftest.py or tests/utils/*.py are not)."""
    n = PurePosixPath(path).name
    return n.startswith("test_") or n.endswith("_test.py")


def import_closure(edges: list[list[str]], changed: set[str]) -> set[str]:
    rev: dict[str, set[str]] = defaultdict(set)
    for s, t in edges:
        rev[t].add(s)
    seen: set[str] = set()
    stack = list(changed)
    while stack:
        cur = stack.pop()
        for s in rev[cur]:
            if s not in seen and s not in changed:
                seen.add(s)
                stack.append(s)
    return seen


def _check_span(problems: list[str], rid: str, text: dict[str, list[str]], where: str, s: Span) -> None:
    lines = text.get(s.path)
    if lines is None:
        problems.append(f"{rid}:{where}: missing file {s.path}")
        return
    if not (1 <= s.start_line <= s.end_line <= len(lines)):
        problems.append(f"{rid}:{where}: lines {s.start_line}-{s.end_line} outside {s.path} ({len(lines)} lines)")
        return
    if s.anchor and s.anchor not in "\n".join(lines[s.start_line - 1:s.end_line]):
        problems.append(f"{rid}:{where}: anchor {s.anchor!r} not found in {s.path}:{s.start_line}-{s.end_line}")


def validate(bm: Benchmark) -> list[str]:
    """Return a list of problems (empty = benchmark is internally consistent)."""
    problems: list[str] = []
    ids: set[str] = set()
    for entry in bm.manifest.repos:
        rid = entry.id
        files = bm.files(rid)
        if content_sha256(files) != entry.content_sha256:
            problems.append(f"{rid}: content_sha256 mismatch (source changed without updating benchmark.json)")
        text = {p: b.decode("utf-8", "replace").split("\n") for p, b in files.items()}
        gt = bm.truth[rid]

        def span_ok(where: str, sp: Span, _rid: str = rid, _text: dict[str, list[str]] = text) -> None:
            _check_span(problems, _rid, _text, where, sp)

        for q in gt.qa:
            if q.id in ids:
                problems.append(f"duplicate question id {q.id}")
            ids.add(q.id)
            if q.answerable and (not q.evidence or not q.key_facts):
                problems.append(f"{rid}:{q.id}: answerable question needs evidence and key_facts")
            if not q.answerable and q.evidence:
                problems.append(f"{rid}:{q.id}: unanswerable question must not list evidence")
            for s in q.evidence:
                span_ok(q.id, s)
        for f in gt.readiness.expected:
            if f.rule not in gt.readiness.assessed_rules:
                problems.append(f"{rid}: expected rule {f.rule} is not in assessed_rules")
            for s in f.evidence:
                span_ok(f.rule, s)
        for r in gt.graph.routes.items:
            route = Route.model_validate(r)
            span_ok(f"route {route.method} {route.path}", Span(path=route.handler_file, start_line=route.decorator_line, end_line=route.def_line, anchor="def "))
        for m in gt.graph.data_models.items + gt.graph.orm_models.items:
            nm = Named.model_validate(m)
            span_ok(f"model {nm.name}", Span(path=nm.path, start_line=nm.line, end_line=nm.line, anchor=f"class {nm.name}"))
        for s, t in gt.graph.internal_imports.items:
            for p in (s, t):
                if p not in files:
                    problems.append(f"{rid}: import edge references missing file {p}")
        for case in gt.impact:
            changed = {c.path for c in case.changed if c.status != "removed"}
            aff = import_closure(gt.graph.internal_imports.items, changed)
            mods = sorted(p for p in aff if not is_test_path(p))
            if sorted(case.expected["affected_modules"].items) != mods:
                problems.append(f"{rid}:{case.id}: affected_modules differ from the closure over internal_imports")
            routes = sorted(f"{r['method']} {r['path']}" for r in gt.graph.routes.items if r["handler_file"] in changed | aff)
            if sorted(case.expected["routes"].items) != routes:
                problems.append(f"{rid}:{case.id}: routes differ from the handler files in changed ∪ affected")
            for t in case.expected["relevant_tests"].items:
                if t not in files or not is_test_file(t):
                    problems.append(f"{rid}:{case.id}: relevant test {t} is not a test file in the repository")
    for rid in bm.manifest.smoke_repos:
        if rid not in bm.truth:
            problems.append(f"smoke repo {rid} not in manifest")
    return problems


def load_json(path: Path) -> dict:
    return json.loads(path.read_text())
