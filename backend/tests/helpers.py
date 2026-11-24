"""Run the real ingestion → parse → graph → readiness pipeline in memory on a dict of files."""
from __future__ import annotations

from app.analysis.archive import Limits, read_archive
from app.analysis.graph import FileFacts, build_graph
from app.analysis.pyparse import extract_facts
from app.analysis.readiness import build_readiness
from app.analysis.webparse import extract_web_facts
from tests.fixtures.sample_repo import SAMPLE_FILES, make_tarball


def analyze(files=None, limits: Limits | None = None, partial: bool = False):
    res = read_archive(iter([make_tarball(files if files is not None else SAMPLE_FILES)]), limits or Limits())
    py, web, paths, support, red, lines = [], [], [], {}, {}, {}
    for e in res.entries:
        if e.status == "excluded":
            continue
        paths.append(e.path)
        lines[e.path] = e.line_count
        if e.kind == "support":
            support[e.path] = e.content
        if e.redaction_lines:
            red[e.path] = e.redaction_lines
        if e.kind == "python" and e.status == "analyzed":
            try:
                py.append(FileFacts(e.path, extract_facts(e.content, e.path), e.line_count))
            except SyntaxError:
                py.append(FileFacts(e.path, None))
        elif e.kind == "web" and e.status == "analyzed":
            web.append(FileFacts(e.path, extract_web_facts(e.path, e.content), e.line_count))
    g = build_graph("owner/sample", py, paths, support, web)
    r = build_readiness(py, web, g, support, red, partial)
    return g, r, res, lines
