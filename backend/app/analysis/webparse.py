"""Static extraction for HTML / CSS / JS / TS / Vue files. Text scanning only — nothing is parsed by a JS engine or executed.

Extracts: outgoing HTTP call sites (fetch / axios / XHR / jQuery / htmx / <form>), module imports, <script>/<link> references,
and a few DOM-injection sinks. URLs are classified honestly:
  literal   - a complete string literal                      template - literal with ${...} / 'a' + b placeholders
  dynamic   - computed at runtime (not resolvable)           relative  - no leading slash; depends on the page URL
  external  - absolute URL to another host
"""
from __future__ import annotations

import bisect
import itertools
import re
from typing import Any
from urllib.parse import urlsplit

from app.analysis.filters import count_lines
from app.analysis.secrets import scrub_text

WEB_EXTENSIONS = {".html": "html", ".htm": "html", ".css": "css", ".js": "js", ".mjs": "js", ".cjs": "js", ".jsx": "js", ".ts": "ts", ".tsx": "ts", ".vue": "vue"}
HTTP_VERBS = {"get", "post", "put", "patch", "delete", "head", "options"}
CLIENT_OBJECTS = r"(?:axios|\$http|http|httpClient|api|client|request|this\.http|this\.api|this\.client|ky|superagent)"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0"}
MAX_CALLS = 200


def language_for(path: str) -> str | None:
    dot = path.rfind(".")
    return WEB_EXTENSIONS.get(path[dot:].lower()) if dot != -1 else None


def strip_js_comments(src: str) -> str:
    """Blank out // and /* */ comments (keeping string/template contents and all newlines so offsets and line numbers stay valid)."""
    out: list[str] = []
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        nxt = src[i + 1] if i + 1 < n else ""
        if c in "'\"`":
            q, j = c, i + 1
            while j < n:
                if src[j] == "\\":
                    j += 2
                    continue
                if src[j] == q or (q != "`" and src[j] == "\n"):
                    break
                j += 1
            out.append(src[i:j + 1]); i = j + 1
        elif c == "/" and nxt == "/":
            j = src.find("\n", i)
            j = n if j == -1 else j
            out.append(" " * (j - i)); i = j
        elif c == "/" and nxt == "*":
            j = src.find("*/", i + 2)
            j = n if j == -1 else j + 2
            out.append("".join(ch if ch == "\n" else " " for ch in src[i:j])); i = j
        else:
            out.append(c); i += 1
    return "".join(out)


class _Lines:
    def __init__(self, text: str, base: int = 1):
        self.starts = [0] + [m.end() for m in re.finditer(r"\n", text)]
        self.base = base

    def at(self, offset: int) -> int:
        return bisect.bisect_right(self.starts, offset) + self.base - 1


def _balanced(text: str, open_idx: int, limit: int = 1500) -> str:
    """Text inside the parentheses that open at ``open_idx`` (string-aware, bounded)."""
    depth, i, n = 0, open_idx, min(len(text), open_idx + limit)
    start = open_idx + 1
    while i < n:
        c = text[i]
        if c in "'\"`":
            q, j = c, i + 1
            while j < n and text[j] != q:
                j += 2 if text[j] == "\\" else 1
            i = j
        elif c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
            if depth == 0:
                return text[start:i]
        i += 1
    return text[start:n]


_STR = r"""(?:'((?:[^'\\\n]|\\.)*)'|"((?:[^"\\\n]|\\.)*)"|`((?:[^`\\]|\\.)*)`)"""
_STR_RE = re.compile(r"^\s*" + _STR)
_CONCAT_RE = re.compile(r"^\s*(?:'((?:[^'\\\n]|\\.)*)'|\"((?:[^\"\\\n]|\\.)*)\")\s*\+")


def classify_url(arg: str) -> tuple[str | None, str, str]:
    """Return (path-or-None, url_kind, display_expr) for the first argument expression of an HTTP call."""
    expr = arg.strip()
    disp = scrub_text(expr[:90], 90)
    m = _STR_RE.match(expr)
    if m and (m.end() >= len(expr.rstrip()) or expr[m.end():].lstrip().startswith(",")):
        raw = m.group(1) if m.group(1) is not None else m.group(2) if m.group(2) is not None else m.group(3)
        kind = "literal"
        if m.group(3) is not None and "${" in raw:
            raw = re.sub(r"\$\{[^}]*\}", "{}", raw)
            kind = "template"
        return _norm_url(raw, kind, disp)
    c = _CONCAT_RE.match(expr)
    if c:  # 'literal' + variable  →  prefix with a placeholder segment
        raw = (c.group(1) if c.group(1) is not None else c.group(2)) + "{}"
        return _norm_url(raw, "template", disp)
    return None, "dynamic", disp


def _norm_url(raw: str, kind: str, disp: str) -> tuple[str | None, str, str]:
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", raw):
        parts = urlsplit(raw.replace("{}", "x"))
        if (parts.hostname or "") in LOCAL_HOSTS:
            raw = parts.path + ("" if "{}" not in raw else "")
            raw = urlsplit(raw).path or "/"
        else:
            return raw.split("?")[0][:200], "external", disp
    raw = raw.split("#")[0].split("?")[0]
    if not raw.startswith("/"):
        return raw[:200], "relative", disp
    return re.sub(r"/{2,}", "/", raw)[:200], kind, disp


def _method_from_options(text: str) -> str | None:
    m = re.search(r"""\b(?:method|type)\s*:\s*['"`](\w+)['"`]""", text)
    return m.group(1).upper() if m else None


def _url_from_options(text: str) -> str | None:
    m = re.search(r"\burl\s*:\s*", text)
    return text[m.end():] if m else None


def _first_arg(inner: str) -> str:
    depth, i = 0, 0
    while i < len(inner):
        c = inner[i]
        if c in "'\"`":
            q, j = c, i + 1
            while j < len(inner) and inner[j] != q:
                j += 2 if inner[j] == "\\" else 1
            i = j
        elif c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif c == "," and depth == 0:
            return inner[:i]
        i += 1
    return inner


SINK_PATTERNS = [
    ("innerHTML assignment", re.compile(r"\.(?:inner|outer)HTML\s*(?:\+)?=(?!=)")), ("document.write", re.compile(r"\bdocument\.write(?:ln)?\s*\(")),
    ("insertAdjacentHTML", re.compile(r"\.insertAdjacentHTML\s*\(")), ("dangerouslySetInnerHTML", re.compile(r"dangerouslySetInnerHTML")),
    ("eval", re.compile(r"(?<![\w.])eval\s*\(")), ("new Function", re.compile(r"\bnew\s+Function\s*\(")), ("v-html", re.compile(r"\bv-html\s*=")),
]


def _js_facts(text: str, line_base: int = 1) -> dict[str, list[dict[str, Any]]]:
    clean = strip_js_comments(text)
    L = _Lines(clean, line_base)
    calls: list[dict[str, Any]] = []
    imports: list[dict[str, Any]] = []
    sinks: list[dict[str, Any]] = []

    def add_call(method: str | None, arg: str, client: str, off: int) -> None:
        if len(calls) >= MAX_CALLS:
            return
        url, kind, disp = classify_url(arg)
        calls.append({"method": method, "url": url, "url_kind": kind, "expr": disp, "line": L.at(off), "client": client})

    for m in re.finditer(r"(?<![\w.$])fetch\s*\(", clean):
        if len(calls) >= MAX_CALLS:
            break
        inner = _balanced(clean, m.end() - 1)
        add_call((_method_from_options(inner[len(_first_arg(inner)):]) or "GET"), _first_arg(inner), "fetch", m.start())
    for m in re.finditer(rf"(?<![\w$]){CLIENT_OBJECTS}\s*\.\s*(get|post|put|patch|delete|head|options)\s*(?:<[^>()]{{0,200}}>)?\s*\(", clean):
        if len(calls) >= MAX_CALLS:
            break
        inner = _balanced(clean, m.end() - 1)
        arg = _first_arg(inner)
        url, kind, _ = classify_url(arg)
        if kind in ("dynamic",) or (url and (url.startswith("/") or kind == "external")):  # skip e.g. map.get('key')
            add_call(m.group(1).upper(), arg, "axios" if "axios" in m.group(0) or "http" in m.group(0).lower() or "ky" in m.group(0) else "http-client", m.start())
    for m in itertools.islice(re.finditer(r"(?<![\w.$])axios\s*(?:\.\s*request\s*)?\(\s*(?=\{)", clean), 300):
        if len(calls) >= MAX_CALLS:
            break
        inner = _balanced(clean, m.end() - 1 + clean[m.end() - 1:].find("(") + 0) if False else _balanced(clean, clean.rfind("(", m.start(), m.end()))
        u = _url_from_options(inner)
        if u is not None:
            add_call(_method_from_options(inner) or "GET", _first_arg(u), "axios", m.start())
    for m in itertools.islice(re.finditer(r"""\.open\s*\(\s*['"`](GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)['"`]\s*,""", clean, re.I), 300):
        inner = _balanced(clean, clean.find("(", m.start()))
        add_call(m.group(1).upper(), inner.split(",", 1)[1] if "," in inner else "", "xhr", m.start())
    for m in itertools.islice(re.finditer(r"(?<![\w.])(?:\$|jQuery)\s*\.\s*(get|post|getJSON|ajax)\s*\(", clean), 300):
        inner = _balanced(clean, m.end() - 1)
        verb = m.group(1)
        if verb == "ajax":
            u = _url_from_options(inner) or (inner if inner.lstrip()[:1] in "'\"`" else None)
            if u is not None:
                add_call(_method_from_options(inner) or "GET", _first_arg(u), "jquery", m.start())
        else:
            add_call("POST" if verb == "post" else "GET", _first_arg(inner), "jquery", m.start())
    for m in re.finditer(r"""\b(?:import|export)\s+(?:type\s+)?(?:[\w*${}\s,]+?\s+from\s+)?['"]([^'"\n]+)['"]""", clean):
        imports.append({"spec": m.group(1)[:200], "line": L.at(m.start()), "kind": "import"})
    for m in re.finditer(r"""(?<![\w.$])require\s*\(\s*['"]([^'"\n]+)['"]\s*\)""", clean):
        imports.append({"spec": m.group(1)[:200], "line": L.at(m.start()), "kind": "require"})
    for m in re.finditer(r"""(?<![\w.$])import\s*\(\s*['"]([^'"\n]+)['"]\s*\)""", clean):
        imports.append({"spec": m.group(1)[:200], "line": L.at(m.start()), "kind": "dynamic"})
    for label, rx in SINK_PATTERNS:
        for m in rx.finditer(clean):
            if len(sinks) < 40:
                sinks.append({"kind": label, "line": L.at(m.start())})
    return {"calls": calls, "imports": imports, "sinks": sinks}


_TAG_RE = re.compile(r"<(form|script|link|[a-zA-Z][\w-]*)\b([^>]{0,2000})>", re.S)
_ATTR_RE = re.compile(r"""([\w:@.-]+)\s*(?:=\s*("[^"]*"|'[^']*'|[^\s>]+))?""")


def _attrs(s: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for m in _ATTR_RE.finditer(s):
        v = m.group(2) or ""
        out[m.group(1).lower()] = v[1:-1] if v[:1] in "'\"" else v
    return out


def _html_facts(text: str) -> dict[str, list[dict[str, Any]]]:
    L = _Lines(text)
    calls: list[dict[str, Any]] = []
    imports: list[dict[str, Any]] = []
    sinks: list[dict[str, Any]] = []
    # inline scripts
    for m in itertools.islice(re.finditer(r"<script\b([^>]{0,2000})>(.{0,200000}?)</script\s*>", text, re.S | re.I), 200):
        a = _attrs(m.group(1))
        if "src" in a:
            imports.append({"spec": a["src"][:200], "line": L.at(m.start()), "kind": "script"})
        elif m.group(2).strip():
            sub = _js_facts(m.group(2), L.at(m.start(2)))
            calls += sub["calls"]; imports += sub["imports"]; sinks += sub["sinks"]
    for m in itertools.islice(_TAG_RE.finditer(text), 20000):
        tag, raw = m.group(1).lower(), m.group(2)
        a = _attrs(raw)
        line = L.at(m.start())
        if tag == "link" and a.get("rel", "").lower() in ("stylesheet", "modulepreload", "preload") and a.get("href"):
            imports.append({"spec": a["href"][:200], "line": line, "kind": "link"})
        if tag == "form" and "action" in a and "hx-post" not in a:
            url, kind, disp = classify_url(f'"{a["action"]}"' if "{{" not in a["action"] else "x")
            calls.append({"method": a.get("method", "GET").upper(), "url": url, "url_kind": kind if "{{" not in a["action"] else "dynamic", "expr": scrub_text(a["action"][:90], 90), "line": line, "client": "form"})
        for hx, verb in (("hx-get", "GET"), ("hx-post", "POST"), ("hx-put", "PUT"), ("hx-patch", "PATCH"), ("hx-delete", "DELETE")):
            if hx in a and len(calls) < MAX_CALLS:
                url, kind, disp = classify_url(f'"{a[hx]}"')
                calls.append({"method": verb, "url": url, "url_kind": kind, "expr": scrub_text(a[hx][:90], 90), "line": line, "client": "htmx"})
        for k in a:
            if k in ("v-html",):
                sinks.append({"kind": "v-html", "line": line})
    return {"calls": calls[:MAX_CALLS], "imports": imports[:300], "sinks": sinks[:40]}


def _css_facts(text: str) -> dict[str, list[dict[str, Any]]]:
    L = _Lines(text)
    imports = [{"spec": (m.group(1) or m.group(2) or m.group(3))[:200], "line": L.at(m.start()), "kind": "css_import"}
               for m in re.finditer(r"""@import\s+(?:url\(\s*['"]?([^'")]+)['"]?\s*\)|'([^']+)'|"([^"]+)")""", text)]
    return {"calls": [], "imports": imports[:100], "sinks": []}


def extract_web_facts(path: str, text: str) -> dict[str, Any]:
    lang = language_for(path) or "js"
    if lang == "html":
        body = _html_facts(text)
    elif lang == "css":
        body = _css_facts(text)
    else:
        body = _js_facts(text)
    return {"web": True, "language": lang, "path": path, "line_count": count_lines(text), **body}
