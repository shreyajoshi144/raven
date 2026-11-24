"""Incremental indexing: diff a new analysis against the owner's previous READY analysis of the same repository, so unchanged files
reuse their parsed facts (and unchanged graph nodes their embeddings). The graph itself is always rebuilt from all facts, which keeps
it consistent and duplicate-free; only the expensive per-file work is skipped. Strictly per-owner: another user's analysis is never a base."""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AnalysisFile, AnalysisJob


def find_base(db: Session, job: AnalysisJob) -> AnalysisJob | None:
    """Most recent READY analysis by the same owner of the same repository (same analyzer version) at another commit."""
    return db.execute(select(AnalysisJob).where(
        AnalysisJob.owner_id == job.owner_id, AnalysisJob.repository_id == job.repository_id, AnalysisJob.id != job.id,
        AnalysisJob.analyzer_version == job.analyzer_version, AnalysisJob.state == "READY", AnalysisJob.graph_complete.is_(True),
        AnalysisJob.commit_sha != job.commit_sha).order_by(AnalysisJob.created_at.desc(), AnalysisJob.id).limit(1)).scalar_one_or_none()


def diff_files(old: dict[str, str], new: dict[str, str]) -> dict[str, Any]:
    """path -> content sha256 maps in, change sets out. A rename is a removed path and an added path with identical, unambiguous content."""
    added = sorted(set(new) - set(old))
    deleted = sorted(set(old) - set(new))
    modified = sorted(p for p in set(old) & set(new) if old[p] != new[p])
    by_old: dict[str, list[str]] = {}
    for p in deleted:
        by_old.setdefault(old[p], []).append(p)
    by_new: dict[str, list[str]] = {}
    for p in added:
        by_new.setdefault(new[p], []).append(p)
    renamed = [{"from": by_old[h][0], "to": by_new[h][0]} for h in sorted(by_old) if len(by_old[h]) == 1 and len(by_new.get(h, [])) == 1]
    ren_from, ren_to = {r["from"] for r in renamed}, {r["to"] for r in renamed}
    return {"added": [p for p in added if p not in ren_to], "modified": modified, "deleted": [p for p in deleted if p not in ren_from],
            "renamed": renamed, "unchanged": sum(1 for p in set(old) & set(new) if old[p] == new[p])}


def file_hashes(db: Session, analysis_id: uuid.UUID) -> dict[str, str]:
    return {p: h for p, h in db.execute(select(AnalysisFile.path, AnalysisFile.content_sha256).where(
        AnalysisFile.analysis_id == analysis_id, AnalysisFile.content_sha256.is_not(None))).all()}


def plan(db: Session, job: AnalysisJob, new_hashes: dict[str, str], full: bool) -> dict[str, Any]:
    """The 'incremental' block stored in the job summary. `base_analysis_id` is None when everything is processed from scratch."""
    base = None if full else find_base(db, job)
    if base is None:
        return {"mode": "full", "reason": "full reindex requested" if full else "no earlier analysis of this repository", "base_analysis_id": None}
    d = diff_files(file_hashes(db, base.id), new_hashes)
    return {"mode": "incremental", "base_analysis_id": str(base.id), "base_commit": base.commit_sha,
            **{k: d[k] for k in ("added", "modified", "deleted", "renamed")}, "unchanged": d["unchanged"]}
