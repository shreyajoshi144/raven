"""Plain-language architecture areas. One place decides which part of the system a file belongs to, so the Map, the pull-request
review and the guide describe the same structure."""
from __future__ import annotations

import re
from pathlib import PurePosixPath

AREAS: dict[str, dict[str, str]] = {
    "frontend": {"label": "Frontend", "blurb": "What users see and click: pages, components and the code that calls the backend.", "tier": "0"},
    "api": {"label": "API & routes", "blurb": "The doors into the backend: the app's entry point and the endpoints that receive requests.", "tier": "1"},
    "logic": {"label": "Business logic", "blurb": "Where the real work happens: services and helpers that endpoints call.", "tier": "2"},
    "data": {"label": "Data & models", "blurb": "How information is shaped and stored: database models, schemas and data access.", "tier": "3"},
    "jobs": {"label": "Background jobs", "blurb": "Work that runs outside a request: workers, tasks and schedulers.", "tier": "2"},
    "config": {"label": "Config & setup", "blurb": "Settings, database connections and start-up code.", "tier": "3"},
    "shared": {"label": "Shared code", "blurb": "Utilities and modules used by several other parts.", "tier": "2"},
    "tools": {"label": "Scripts & tooling", "blurb": "Helper scripts, load tests, benchmarks and examples that support the project but are not the app itself.", "tier": "4"},
    "tests": {"label": "Tests", "blurb": "Automated checks that exercise the code.", "tier": "4"},
    "external": {"label": "External packages", "blurb": "Third-party libraries the project imports.", "tier": "4"},
}
ROLE_TO_AREA = {"frontend": "frontend", "entry": "api", "router": "api", "service": "logic", "model": "data", "worker": "jobs", "config": "config", "test": "tests", "external": "external"}
_PATH_HINTS = [
    (re.compile(r"(^|/)(scripts?|tools?|loadtests?|load_tests?|benchmarks?|e2e|evals?|evaluation|examples?|demos?|samples?|notebooks?|tooling)(/|$)", re.I), "tools"),
    (re.compile(r"(^|/)(routes?|routers?|endpoints?|api|views|controllers?|handlers?)(/|$)", re.I), "api"),
    (re.compile(r"(^|/)(models?|schemas?|db|database|orm|entities|migrations?|alembic)(/|$)", re.I), "data"),
    (re.compile(r"(^|/)(workers?|tasks?|jobs?|celery|schedulers?|queues?)(/|$)", re.I), "jobs"),
    (re.compile(r"(^|/)(services?|usecases?|use_cases|domain|managers?|logic|core|crud|repositories|repository)(/|$)", re.I), "logic"),
    (re.compile(r"(^|/)(config|settings|conf)(/|\.py$)", re.I), "config"),
    # flat projects keep everything in one folder, so the file name has to carry the hint
    (re.compile(r"(^|/)[\w-]*(_api|api_|router|routes|endpoints?)[\w-]*\.py$", re.I), "api"),
    (re.compile(r"(^|/)([\w-]*_)?(models?|schemas?|db|database|orm|entities|migrations?)(_[\w-]*)?\.py$", re.I), "data"),
    (re.compile(r"(^|/)[\w-]*(_worker|worker_|_tasks?|tasks?_|_jobs?|scheduler|celery)[\w-]*\.py$", re.I), "jobs"),
    (re.compile(r"(^|/)[\w-]*(_service|service_|_manager|_engine|_planner|_pipeline|_handler)[\w-]*\.py$", re.I), "logic"),
]


def is_test_path(p: str) -> bool:
    name = PurePosixPath(p).name
    return p.startswith("tests/") or "/tests/" in p or "/test/" in p or p.startswith("test/") or name.startswith("test_") or name.endswith("_test.py")


def area_of(path: str, role: str | None = None, web: bool = False) -> str:
    """Area id for a file. A specific analyser role wins; otherwise the folder and file names decide."""
    if is_test_path(path):
        return "tests"
    if web or role == "frontend":
        return "frontend"
    if role in (None, "module", "entry") and _PATH_HINTS[0][0].search(path):
        return "tools"
    if role in ROLE_TO_AREA and role != "module":
        return ROLE_TO_AREA[role]
    for rx, area in _PATH_HINTS:
        if rx.search(path):
            return area
    return "shared"


def _words(stem: str) -> str:
    first = re.split(r"[_\-.]", re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", stem))[0]
    return first.lower()


def group_files(paths: list[str]) -> dict[str, list[str]]:
    """Split one area's files into a handful of named groups: by the first folder below the shared prefix, else by file-name prefix."""
    if not paths:
        return {}
    parts = [PurePosixPath(p).parent.parts for p in paths]
    common = 0
    while all(len(x) > common for x in parts) and len({x[common] for x in parts}) == 1:
        common += 1
    groups: dict[str, list[str]] = {}
    for p, d in zip(paths, parts):
        groups.setdefault(d[common] if len(d) > common else "", []).append(p)
    if len(groups) == 1:  # one flat folder: group by the first word of the file name (auth_*, user_* ...)
        by: dict[str, list[str]] = {}
        for p in paths:
            by.setdefault(_words(PurePosixPath(p).stem), []).append(p)
        shared = {k: v for k, v in by.items() if len(v) > 1}
        if shared or len(by) <= 12:
            groups = {k: v for k, v in by.items()}
    if len(groups) > 14:  # keep the 13 biggest, fold the rest into "other"
        big = sorted(groups, key=lambda k: -len(groups[k]))[:13]
        rest = [p for k, v in groups.items() if k not in big for p in v]
        groups = {k: groups[k] for k in big}
        groups["other"] = rest
    return groups
