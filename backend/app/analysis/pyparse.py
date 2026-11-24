"""Static extraction of Python facts using only ``ast`` (repository code is never imported or run).

The extractor returns JSON-serializable per-file facts. Resolution across files happens in graph.py.
Anything that cannot be resolved statically is recorded explicitly (dynamic paths, dynamic imports...).
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from typing import Any

from app.analysis.filters import count_lines
from app.analysis.secrets import REDACTED, scrub_text

HTTP_METHODS = {"get", "post", "put", "delete", "patch", "options", "head", "trace"}
MAX_CALLS_PER_FUNCTION = 300
MAX_REFS_PER_SCOPE = 200
_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")
FACTORY_NAMES = {"create_app", "create_application", "get_application", "build_app", "make_app", "app_factory", "get_app"}
AUTH_CTORS = {
    "OAuth2PasswordBearer", "OAuth2AuthorizationCodeBearer", "HTTPBearer", "HTTPBasic", "HTTPDigest",
    "APIKeyHeader", "APIKeyQuery", "APIKeyCookie", "OAuth2PasswordRequestForm",
}
LOG_METHODS = {"debug", "info", "warning", "warn", "error", "exception", "critical", "fatal", "log"}
_SECRETY = re.compile(r"(?i)(secret|passw(?:or)?d|token|api_?key|private_?key|credential)")
_NOT_SECRET_NAME = re.compile(r"(?i)(url|uri|path|endpoint|header|name|type|algorithm|expire|prefix|_env$|env_|field|label|hint|regex|pattern|length|ttl|minutes|seconds)")
_PLACEHOLDER = re.compile(r"(?i)^(change|replace|your|example|dummy|test|xxx|todo|secret$|password$|<|\$\{|none$)")
_SQLISH = re.compile(r"(?i)\b(select|insert\s+into|update|delete\s+from|drop\s+table|create\s+table|alter\s+table|where)\b")
AUTH_MODULES = {"jwt", "jose", "passlib", "authlib", "fastapi_users", "itsdangerous", "bcrypt", "argon2"}


def _trunc(s: str, n: int = 160) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def _unparse(node: ast.AST | None, n: int = 160) -> str:
    if node is None:
        return ""
    try:
        return scrub_text(_trunc(ast.unparse(node), n), n)
    except Exception:  # noqa: BLE001
        return "<unparseable>"


def _dotted(node: ast.AST) -> str | None:
    """Return 'a.b.c' for a Name/Attribute chain, else None."""
    parts: list[str] = []
    cur: ast.AST = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
        return ".".join(reversed(parts))
    return None


def module_name_for(path: str) -> tuple[str, bool]:
    """Return (dotted module name from repo root, is_package)."""
    p = path[:-3] if path.endswith(".py") else path
    parts = p.split("/")
    is_pkg = parts[-1] == "__init__"
    if is_pkg:
        parts = parts[:-1]
    return ".".join(parts) if parts else "", is_pkg


@dataclass
class _Scope:
    kind: str  # function | class
    qualname: str
    name: str


class FactsExtractor(ast.NodeVisitor):
    def __init__(self, source: str, path: str):
        self.path = path
        self.source = source
        self.module, self.is_package = module_name_for(path)
        self.tree, self.parse_issues = parse_tolerant(source, path)
        self.scopes: list[_Scope] = []
        self.bindings: dict[str, str] = {}
        self.import_stmts: list[dict[str, Any]] = []
        self.dynamic_imports: list[dict[str, Any]] = []
        self.functions: list[dict[str, Any]] = []
        self.classes: list[dict[str, Any]] = []
        self.apps: list[dict[str, Any]] = []
        self.routers: list[dict[str, Any]] = []
        self.routes: list[dict[str, Any]] = []
        self.includes: list[dict[str, Any]] = []
        self.mounts: list[dict[str, Any]] = []
        self.handler_deps: dict[str, list[dict[str, Any]]] = {}
        self.handler_annotations: dict[str, list[dict[str, Any]]] = {}  # plain annotation names (may be Annotated[..., Depends()] aliases)
        self.dep_aliases: dict[str, list[dict[str, Any]]] = {}  # module-level `Name = Annotated[..., Depends(f)]`
        self.calls: dict[str, dict[str, int]] = {}
        self.refs: dict[str, set[str]] = {}
        self.env_vars: list[dict[str, Any]] = []
        self.background: list[dict[str, Any]] = []
        self.auth_hints: list[dict[str, Any]] = []
        self.sa_bases: list[dict[str, Any]] = []
        self.constants: dict[str, str] = {}
        self.entry: dict[str, Any] = {"main_guard": None, "uvicorn_run": None, "uvicorn_target": None, "factories": []}
        self.bg_params: dict[str, set[str]] = {}
        self._in_deco = False
        self.excepts: list[dict[str, Any]] = []
        self.risky: list[dict[str, Any]] = []
        self.prints: list[int] = []
        self.secret_defaults: list[dict[str, Any]] = []
        self.logger_calls = 0
        self.hooks: list[dict[str, Any]] = []
        self._collect_imports()
        self._collect_constants()

    # ---------------------------------------------------------------- imports
    def _package(self) -> str:
        return self.module if self.is_package else self.module.rpartition(".")[0]

    def _abs_from(self, level: int, module: str | None) -> str | None:
        if level == 0:
            return module or ""
        pkg_parts = [p for p in self._package().split(".") if p]
        up = level - 1
        if up > len(pkg_parts):
            return None
        base = pkg_parts[: len(pkg_parts) - up]
        if module:
            base = base + module.split(".")
        return ".".join(base)

    def _collect_imports(self) -> None:
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                names = []
                for a in node.names:
                    names.append({"name": a.name, "asname": a.asname})
                    local = a.asname or a.name.split(".")[0]
                    self.bindings[local] = a.name if a.asname else a.name.split(".")[0]
                self.import_stmts.append({
                    "kind": "import", "module": None, "level": 0, "names": names,
                    "line": node.lineno, "end_line": node.end_lineno or node.lineno,
                    "in_function": False,
                })
            elif isinstance(node, ast.ImportFrom):
                names = [{"name": a.name, "asname": a.asname} for a in node.names]
                absmod = self._abs_from(node.level, node.module)
                for a in node.names:
                    if a.name == "*":
                        continue
                    local = a.asname or a.name
                    if absmod is None:
                        continue
                    self.bindings[local] = f"{absmod}.{a.name}" if absmod else a.name
                self.import_stmts.append({
                    "kind": "from", "module": node.module, "level": node.level, "abs_module": absmod,
                    "names": names, "line": node.lineno, "end_line": node.end_lineno or node.lineno,
                })

    def _collect_constants(self) -> None:
        for node in self.tree.body:
            target = value = None
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                target, value = node.targets[0].id, node.value
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
                target, value = node.target.id, node.value
            if target and isinstance(value, ast.Constant) and isinstance(value.value, str) and len(value.value) <= 200:
                self.constants[target] = value.value

    def resolve_dotted(self, node: ast.AST) -> str | None:
        d = _dotted(node)
        if d is None:
            return None
        head, _, rest = d.partition(".")
        base = self.bindings.get(head)
        if base is None:
            return None
        return f"{base}.{rest}" if rest else base

    # ------------------------------------------------------------ scope helpers
    def _qual(self, name: str) -> str:
        return ".".join([s.name for s in self.scopes] + [name])

    @property
    def _cur(self) -> str | None:
        return self.scopes[-1].qualname if self.scopes else None

    @property
    def _cur_func(self) -> str | None:
        for s in reversed(self.scopes):
            if s.kind == "function":
                return s.qualname
        return None

    def _add_ref(self, text: str) -> None:
        q = self._cur
        if q is None:
            return
        bucket = self.refs.setdefault(q, set())
        if len(bucket) < MAX_REFS_PER_SCOPE:
            bucket.add(text)

    # ------------------------------------------------------------------ helpers
    def _str_arg(self, node: ast.AST | None) -> tuple[str | None, str]:
        """Return (value, status) where status in literal|constant|dynamic|none."""
        if node is None:
            return None, "none"
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value, "literal"
        if isinstance(node, ast.Name) and node.id in self.constants:
            return self.constants[node.id], "constant"
        return None, "dynamic"

    @staticmethod
    def _kw(call: ast.Call, name: str) -> ast.AST | None:
        for k in call.keywords:
            if k.arg == name:
                return k.value
        return None

    def _depends_in(self, node: ast.AST | None) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        if node is None:
            return out
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call):
                fn = _dotted(sub.func) or ""
                if fn.split(".")[-1] in {"Depends", "Security"} and sub.args:
                    arg = sub.args[0]
                    expr = _dotted(arg)
                    if expr is None and isinstance(arg, ast.Call):
                        expr = _dotted(arg.func)
                        kind = "call"
                    else:
                        kind = "name"
                    out.append({"expr": expr, "kind": kind, "text": _unparse(arg, 80), "line": sub.lineno})
        return out

    # ------------------------------------------------------------------ visitors
    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:  # noqa: N802
        qual = self._qual(node.name)
        enclosing_class = next((s.name for s in reversed(self.scopes) if s.kind == "class"), None) if (
            self.scopes and self.scopes[-1].kind == "class") else None
        decos = [_unparse(d, 120) for d in node.decorator_list]
        params = [a.arg for a in (node.args.posonlyargs + node.args.args + node.args.kwonlyargs)]
        if node.args.vararg:
            params.append("*" + node.args.vararg.arg)
        if node.args.kwarg:
            params.append("**" + node.args.kwarg.arg)
        doc = ast.get_docstring(node)
        self.functions.append({
            "name": node.name, "qualname": qual, "line": node.lineno, "end_line": node.end_lineno or node.lineno,
            "decorator_start": min([d.lineno for d in node.decorator_list], default=node.lineno),
            "async": isinstance(node, ast.AsyncFunctionDef), "decorators": decos,
            "doc": scrub_text(doc, 300) if doc else None, "class": enclosing_class, "params": params[:20],
            "returns": _unparse(node.returns, 80) if node.returns else None, "complexity": self._complexity(node),
        })
        if node.name in FACTORY_NAMES and not self.scopes:
            self.entry["factories"].append({"name": node.name, "line": node.lineno})

        self.scopes.append(_Scope("function", qual, node.name))
        # signature: annotations + defaults (Depends lives here)
        deps: list[dict[str, Any]] = []
        ann_names: list[dict[str, Any]] = []
        bg_names: set[str] = set()
        all_args = node.args.posonlyargs + node.args.args + node.args.kwonlyargs
        defaults = [None] * (len(node.args.posonlyargs + node.args.args) - len(node.args.defaults)) + list(node.args.defaults)
        defaults += list(node.args.kw_defaults)
        for arg, default in zip(all_args, defaults):
            if arg.annotation is not None:
                self.visit(arg.annotation)
                deps.extend(self._depends_in(arg.annotation))
                ann = _dotted(arg.annotation) or ""
                if ann:
                    ann_names.append({"name": ann, "line": arg.lineno})
                if ann.split(".")[-1] == "BackgroundTasks":
                    bg_names.add(arg.arg)
            if default is not None:
                self.visit(default)
                deps.extend(self._depends_in(default))
        if node.returns is not None:
            self.visit(node.returns)
        for d in node.decorator_list:
            self._handle_route_decorator(d, node, qual)
            self._handle_background_decorator(d, node)
            if isinstance(d, ast.Call):
                self._in_deco = True
                self.visit(d)  # collect refs inside decorator arguments (not call-graph edges)
                self._in_deco = False
        if deps:
            self.handler_deps[qual] = deps
        if ann_names:
            self.handler_annotations[qual] = ann_names
        if bg_names:
            self.bg_params[qual] = bg_names
            self.background.append({"kind": "fastapi_background_tasks", "target": None, "line": node.lineno,
                                    "scope": qual, "param": sorted(bg_names)[0]})
        for stmt in node.body:
            self.visit(stmt)
        self.scopes.pop()

    visit_AsyncFunctionDef = visit_FunctionDef  # noqa: N815

    @staticmethod
    def _complexity(fn: ast.AST) -> int:
        c = 1
        for n in ast.walk(fn):
            if isinstance(n, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler, ast.IfExp, ast.Assert, ast.comprehension)):
                c += 1
            elif isinstance(n, ast.BoolOp):
                c += len(n.values) - 1
            elif isinstance(n, ast.match_case):
                c += 1
        return c

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:  # noqa: N802
        names = [_dotted(e) for e in (node.type.elts if isinstance(node.type, ast.Tuple) else [node.type])] if node.type is not None else []
        kind = "bare" if node.type is None else ("broad" if any(n in ("Exception", "BaseException") for n in names if n) else "specific")
        body = node.body
        swallowed = all(isinstance(b, (ast.Pass, ast.Continue)) or (isinstance(b, ast.Expr) and isinstance(b.value, ast.Constant)) for b in body)
        reraises = any(isinstance(n, ast.Raise) for b in body for n in ast.walk(b))
        logs = any(isinstance(n, ast.Call) and self._is_log_call(n) for b in body for n in ast.walk(b))
        self.excepts.append({"kind": kind, "line": node.lineno, "end_line": node.end_lineno or node.lineno, "swallowed": swallowed, "reraises": reraises, "logs": logs,
                             "type": _unparse(node.type, 60) if node.type is not None else None, "scope": self._cur_func})
        self.generic_visit(node)

    @staticmethod
    def _is_log_call(n: ast.Call) -> bool:
        d = _dotted(n.func) or ""
        return d.split(".")[-1] in LOG_METHODS and "log" in d.lower()

    def _record_secret_default(self, name: str, value: ast.AST | None, line: int) -> None:
        if not (isinstance(value, ast.Constant) and isinstance(value.value, str)) or len(value.value) < 4:
            return
        if value.value.startswith(REDACTED):  # redaction already matched a credential pattern on this assignment before parsing
            if _SECRETY.search(name) and len(self.secret_defaults) < 40:
                self.secret_defaults.append({"name": name[:80], "line": line, "placeholder": False, "scope": "class" if self.scopes and self.scopes[-1].kind == "class" else ("function" if self._cur_func else "module")})
            return
        if not _SECRETY.search(name) or _NOT_SECRET_NAME.search(name) or value.value.startswith(("/", "http", "$")) or value.value.isupper():
            return
        if len(self.secret_defaults) < 40:  # the literal is never stored
            self.secret_defaults.append({"name": name[:80], "line": line, "placeholder": bool(_PLACEHOLDER.match(value.value)),
                                         "scope": "class" if self.scopes and self.scopes[-1].kind == "class" else ("function" if self._cur_func else "module")})

    def _risk(self, kind: str, node: ast.AST, **extra: Any) -> None:
        if len(self.risky) < 120:
            self.risky.append({"kind": kind, "line": getattr(node, "lineno", 0), "text": _unparse(node, 90), "scope": self._cur_func, **extra})

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        qual = self._qual(node.name)
        bases = [_unparse(b, 80) for b in node.bases]
        resolved = [self.resolve_dotted(b) for b in node.bases]
        kws = {k.arg: _unparse(k.value, 40) for k in node.keywords if k.arg}
        fields: list[dict[str, Any]] = []
        columns: list[dict[str, Any]] = []
        tablename = None
        methods: list[str] = []
        for stmt in node.body:
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                fields.append({"name": stmt.target.id, "type": _unparse(stmt.annotation, 80), "line": stmt.lineno,
                               "has_default": stmt.value is not None})
                if stmt.value is not None and isinstance(stmt.value, ast.Call):
                    fn = (_dotted(stmt.value.func) or "").split(".")[-1]
                    if fn in {"mapped_column", "Column", "relationship"}:
                        columns.append({"name": stmt.target.id, "line": stmt.lineno, "kind": fn})
            elif isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
                tname = stmt.targets[0].id
                if tname == "__tablename__" and isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
                    tablename = stmt.value.value[:80]
                elif isinstance(stmt.value, ast.Call):
                    fn = (_dotted(stmt.value.func) or "").split(".")[-1]
                    if fn in {"Column", "mapped_column", "relationship"}:
                        columns.append({"name": tname, "line": stmt.lineno, "kind": fn})
            elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                methods.append(stmt.name)
        doc = ast.get_docstring(node)
        self.classes.append({
            "name": node.name, "qualname": qual, "line": node.lineno, "end_line": node.end_lineno or node.lineno,
            "bases": bases, "resolved_bases": [r for r in resolved if r], "keywords": kws,
            "decorators": [_unparse(d, 80) for d in node.decorator_list],
            "doc": scrub_text(doc, 300) if doc else None,
            "fields": fields[:60], "columns": columns[:60], "tablename": tablename, "methods": methods[:60],
        })
        self.scopes.append(_Scope("class", qual, node.name))
        for b in node.bases:
            self.visit(b)
        for k in node.keywords:
            self.visit(k.value)
        for stmt in node.body:
            self.visit(stmt)
        self.scopes.pop()

    def visit_Name(self, node: ast.Name) -> None:  # noqa: N802
        if isinstance(node.ctx, ast.Load):
            self._add_ref(node.id)

    def visit_Attribute(self, node: ast.Attribute) -> None:  # noqa: N802
        d = _dotted(node)
        if d and d.count(".") <= 3:
            self._add_ref(d)
        self.generic_visit(node)

    def visit_If(self, node: ast.If) -> None:  # noqa: N802
        t = node.test
        if (
            isinstance(t, ast.Compare) and isinstance(t.left, ast.Name) and t.left.id == "__name__"
            and len(t.comparators) == 1 and isinstance(t.comparators[0], ast.Constant)
            and t.comparators[0].value == "__main__"
        ):
            self.entry["main_guard"] = node.lineno
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:  # noqa: N802
        d = _dotted(node.value)
        if d in {"os.environ", "environ"} and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
            self.env_vars.append({"name": node.slice.value[:100], "line": node.lineno, "how": "os.environ[...]",
                                  "scope": self._cur_func, "has_default": False})
        self.generic_visit(node)

    def _record_dep_alias(self, target: ast.expr, value: ast.expr | None) -> None:
        if not self.scopes and isinstance(target, ast.Name) and isinstance(value, ast.Subscript) and (_dotted(value.value) or "").split(".")[-1] == "Annotated":
            deps = self._depends_in(value)
            if deps:
                self.dep_aliases[target.id] = deps

    def visit_Assign(self, node: ast.Assign) -> None:  # noqa: N802
        for t in node.targets:
            if isinstance(t, ast.Name):
                self._record_secret_default(t.id, node.value, node.lineno)
            self._record_dep_alias(t, node.value)
        self._handle_assign(node.targets, node.value, node)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:  # noqa: N802
        if isinstance(node.target, ast.Name):
            self._record_secret_default(node.target.id, node.value, node.lineno)
        self._record_dep_alias(node.target, node.value)
        if node.value is not None:
            self._handle_assign([node.target], node.value, node)
        self.generic_visit(node)

    def _handle_assign(self, targets: list[ast.expr], value: ast.expr, node: ast.stmt) -> None:
        if not isinstance(value, ast.Call):
            return
        names = [t.id for t in targets if isinstance(t, ast.Name)]
        if not names:
            return
        var = names[0]
        resolved = self.resolve_dotted(value.func) or ""
        short = (_dotted(value.func) or "").split(".")[-1]
        via_import = bool(resolved)
        if short == "FastAPI" and (not via_import or resolved.startswith("fastapi")):
            lifespan = self._kw(value, "lifespan")
            self.apps.append({"var": var, "line": node.lineno, "via_import": via_import,
                              "scope": self._cur_func, "has_lifespan": lifespan is not None,
                              "title": self._str_arg(self._kw(value, "title"))[0]})
            if lifespan is not None:
                self.background.append({"kind": "lifespan", "target": _unparse(lifespan, 60), "line": node.lineno, "scope": self._cur_func})
            for d in self._depends_in(self._kw(value, "dependencies")):
                self.apps[-1].setdefault("dependencies", []).append(d)
        elif short == "APIRouter" and (not via_import or resolved.startswith("fastapi")):
            prefix, status = self._str_arg(self._kw(value, "prefix"))
            self.routers.append({"var": var, "line": node.lineno, "prefix": prefix, "prefix_status": status,
                                 "prefix_expr": _unparse(self._kw(value, "prefix"), 60) if status == "dynamic" else None,
                                 "scope": self._cur_func, "via_import": via_import,
                                 "dependencies": self._depends_in(self._kw(value, "dependencies"))})
        elif short in {"declarative_base"} or resolved.endswith("declarative_base"):
            self.sa_bases.append({"var": var, "line": node.lineno})
        elif short == "Celery" and (not via_import or resolved.startswith("celery")):
            self.background.append({"kind": "celery_app", "target": var, "line": node.lineno, "scope": self._cur_func})
        elif short in {"BackgroundScheduler", "AsyncIOScheduler", "BlockingScheduler"} and (not via_import or "apscheduler" in resolved):
            self.background.append({"kind": "apscheduler", "target": var, "line": node.lineno, "scope": self._cur_func})
        elif short in {"OAuth2PasswordBearer", "HTTPBearer", "HTTPBasic", "APIKeyHeader", "APIKeyQuery", "APIKeyCookie",
                       "OAuth2AuthorizationCodeBearer"}:
            self.auth_hints.append({"kind": short, "line": node.lineno, "var": var})

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        func_d = _dotted(node.func)
        resolved = self.resolve_dotted(node.func) or ""
        last = func_d.split(".")[-1] if func_d else (node.func.attr if isinstance(node.func, ast.Attribute) else "")

        # env var access
        if func_d in {"os.getenv", "getenv", "os.environ.get", "environ.get", "os.environ.setdefault"} and node.args:
            a0 = node.args[0]
            if isinstance(a0, ast.Constant) and isinstance(a0.value, str):
                has_default = len(node.args) >= 2 or any(k.arg == "default" for k in node.keywords)
                self.env_vars.append({"name": a0.value[:100], "line": node.lineno, "how": func_d, "scope": self._cur_func, "has_default": has_default})
        elif func_d in {"config", "env", "env.str", "env.int", "env.bool", "env.get", "Env"} and node.args:
            a0 = node.args[0]
            if isinstance(a0, ast.Constant) and isinstance(a0.value, str) and _ENV_NAME.match(a0.value):
                self.env_vars.append({"name": a0.value[:100], "line": node.lineno, "how": func_d, "scope": self._cur_func,
                                      "has_default": len(node.args) >= 2 or any(k.arg == "default" for k in node.keywords)})

        self._detect_risks(node, func_d, resolved)

        # app.include_router / router.include_router / mount / add_api_route
        if isinstance(node.func, ast.Attribute):
            owner = _dotted(node.func.value)
            if node.func.attr == "include_router" and owner and node.args:
                prefix, status = self._str_arg(self._kw(node, "prefix"))
                self.includes.append({
                    "parent": owner, "child": _dotted(node.args[0]), "child_text": _unparse(node.args[0], 60),
                    "prefix": prefix, "prefix_status": status,
                    "prefix_expr": _unparse(self._kw(node, "prefix"), 60) if status == "dynamic" else None,
                    "line": node.lineno, "end_line": node.end_lineno or node.lineno, "scope": self._cur_func,
                    "dependencies": self._depends_in(self._kw(node, "dependencies")),
                })
            elif node.func.attr == "add_exception_handler":
                self.hooks.append({"kind": "exception_handler", "line": node.lineno})
            elif node.func.attr == "mount" and owner and node.args:
                path, status = self._str_arg(node.args[0])
                self.mounts.append({"parent": owner, "path": path, "status": status,
                                    "target": _unparse(node.args[1], 60) if len(node.args) > 1 else None, "line": node.lineno})
            elif node.func.attr == "add_api_route" and owner and node.args:
                path, status = self._str_arg(node.args[0])
                handler = node.args[1] if len(node.args) > 1 else self._kw(node, "endpoint")
                methods = self._methods_from(self._kw(node, "methods")) or ["GET"]
                self.routes.append({
                    "owner": owner, "methods": methods, "path": path, "path_status": status,
                    "path_expr": _unparse(node.args[0], 60) if status == "dynamic" else None,
                    "handler": None, "handler_expr": _dotted(handler) if handler is not None else None,
                    "line": node.lineno, "decorator_line": node.lineno, "end_line": node.end_lineno or node.lineno,
                    "response_model": _unparse(self._kw(node, "response_model"), 80) or None,
                    "dependencies": self._depends_in(self._kw(node, "dependencies")), "websocket": False,
                    "summary": None, "via": "add_api_route",
                })
            elif node.func.attr == "add_task" and owner:
                cur_params = set()
                for s in self.scopes:
                    cur_params |= self.bg_params.get(s.qualname, set())
                if owner in cur_params and node.args:
                    self.background.append({"kind": "fastapi_background_tasks", "target": _dotted(node.args[0]), "line": node.lineno,
                                            "scope": self._cur_func, "add_task": True})
            elif node.func.attr == "enqueue" and "rq" in resolved.split(".")[0:1] or (
                    node.func.attr == "enqueue" and any(v.startswith("rq") for v in self.bindings.values())):
                self.background.append({"kind": "rq_enqueue", "target": _dotted(node.args[0]) if node.args else None,
                                        "line": node.lineno, "scope": self._cur_func})

        # uvicorn.run
        if func_d in {"uvicorn.run", "run"} and (resolved.startswith("uvicorn") or func_d == "uvicorn.run"):
            self.entry["uvicorn_run"] = node.lineno
            if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                self.entry["uvicorn_target"] = node.args[0].value[:100]

        # dynamic imports
        if func_d in {"importlib.import_module", "import_module", "__import__"}:
            if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                self.dynamic_imports.append({"literal": node.args[0].value[:200], "line": node.lineno})
            else:
                self.dynamic_imports.append({"literal": None, "expr": _unparse(node.args[0], 60) if node.args else "", "line": node.lineno})

        # workers
        if last in {"Thread", "Process"} and (resolved.startswith(("threading", "multiprocessing")) or func_d in {"threading.Thread", "multiprocessing.Process"}):
            tgt = self._kw(node, "target")
            self.background.append({"kind": "thread" if last == "Thread" else "process", "target": _dotted(tgt) if tgt is not None else None,
                                    "line": node.lineno, "scope": self._cur_func})
        elif func_d in {"asyncio.create_task", "asyncio.ensure_future"} or (last == "create_task" and func_d and func_d.endswith("loop.create_task")):
            self.background.append({"kind": "asyncio_task", "target": _unparse(node.args[0], 60) if node.args else None,
                                    "line": node.lineno, "scope": self._cur_func})
        if last in AUTH_CTORS and not any(a["line"] == node.lineno for a in self.auth_hints):
            self.auth_hints.append({"kind": last, "line": node.lineno, "var": None})

        # call graph candidates (function scope only)
        cf = self._cur_func
        if cf and func_d and func_d.count(".") <= 2 and not self._in_deco:
            bucket = self.calls.setdefault(cf, {})
            if func_d not in bucket and len(bucket) < MAX_CALLS_PER_FUNCTION:
                bucket[func_d] = node.lineno
        self.generic_visit(node)

    def _detect_risks(self, node: ast.Call, func_d: str | None, resolved: str) -> None:
        d = resolved or func_d or ""
        kw = {k.arg: k.value for k in node.keywords if k.arg}
        if self._is_log_call(node):
            self.logger_calls += 1
        if isinstance(node.func, ast.Name):
            if node.func.id == "print":
                if len(self.prints) < 60:
                    self.prints.append(node.lineno)
            elif node.func.id in ("eval", "exec") and node.args and not isinstance(node.args[0], ast.Constant):
                self._risk("dynamic_code_exec", node, fn=node.func.id)
        if d == "os.system" or func_d == "os.system":
            self._risk("os_system", node)
        if d.startswith("subprocess.") and isinstance(kw.get("shell"), ast.Constant) and kw["shell"].value is True:
            self._risk("subprocess_shell", node)
        if d in ("pickle.loads", "pickle.load", "cPickle.loads", "marshal.loads", "dill.loads", "dill.load"):
            self._risk("unsafe_deserialization", node, fn=d)
        if d.endswith("yaml.load") and "Loader" not in kw and len(node.args) < 2:
            self._risk("yaml_unsafe_load", node)
        if d in ("hashlib.md5", "hashlib.sha1"):
            self._risk("weak_hash", node, fn=d)
        if isinstance(kw.get("verify"), ast.Constant) and kw["verify"].value is False:
            self._risk("tls_verify_disabled", node)
        if (func_d or "").endswith("jwt.decode") or d.endswith("jwt.decode"):
            opts = kw.get("options")
            if isinstance(opts, ast.Dict) and any(isinstance(k, ast.Constant) and k.value == "verify_signature" and isinstance(v, ast.Constant) and v.value is False for k, v in zip(opts.keys, opts.values)):
                self._risk("jwt_verify_disabled", node)
        if isinstance(node.func, ast.Attribute) and node.func.attr in ("execute", "executemany", "exec_driver_sql") and node.args:
            a0 = node.args[0]
            built = isinstance(a0, ast.JoinedStr) or (isinstance(a0, ast.BinOp) and isinstance(a0.op, (ast.Mod, ast.Add))) or (
                isinstance(a0, ast.Call) and isinstance(a0.func, ast.Attribute) and a0.func.attr == "format")
            if built and _SQLISH.search(" ".join(str(c.value) for c in ast.walk(a0) if isinstance(c, ast.Constant) and isinstance(c.value, str))):
                self._risk("sql_string_building", node)
        if isinstance(kw.get("debug"), ast.Constant) and kw["debug"].value is True:
            self._risk("debug_enabled", node)
        if isinstance(node.func, ast.Attribute) and node.func.attr == "add_middleware" and node.args and (_dotted(node.args[0]) or "").endswith("CORSMiddleware"):
            origins = kw.get("allow_origins")
            if isinstance(origins, (ast.List, ast.Tuple)) and any(isinstance(e, ast.Constant) and e.value == "*" for e in origins.elts):
                self._risk("cors_wildcard", node, credentials=isinstance(kw.get("allow_credentials"), ast.Constant) and kw["allow_credentials"].value is True)

    # ---------------------------------------------------------- decorator helpers
    @staticmethod
    def _methods_from(node: ast.AST | None) -> list[str]:
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            return [str(e.value).upper() for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
        return []

    def _handle_route_decorator(self, dec: ast.expr, fn: ast.FunctionDef | ast.AsyncFunctionDef, qual: str) -> None:
        if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)):
            return
        attr = dec.func.attr
        owner = _dotted(dec.func.value)
        if owner is None:
            return
        if attr in HTTP_METHODS:
            methods, ws = [attr.upper()], False
        elif attr == "api_route":
            methods, ws = self._methods_from(self._kw(dec, "methods")) or ["GET"], False
        elif attr == "websocket":
            methods, ws = ["WEBSOCKET"], True
        else:
            return
        path_node = dec.args[0] if dec.args else self._kw(dec, "path")
        path, status = self._str_arg(path_node)
        rm = self._kw(dec, "response_model")
        self.routes.append({
            "owner": owner, "methods": methods, "path": path, "path_status": status,
            "path_expr": _unparse(path_node, 60) if status == "dynamic" else None,
            "handler": qual, "handler_expr": None, "line": fn.lineno, "decorator_line": dec.lineno,
            "end_line": fn.end_lineno or fn.lineno,
            "response_model": _unparse(rm, 80) if rm is not None else None,
            "dependencies": self._depends_in(self._kw(dec, "dependencies")), "websocket": ws,
            "summary": self._str_arg(self._kw(dec, "summary"))[0], "via": "decorator",
        })

    def _handle_background_decorator(self, dec: ast.expr, fn: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        target = dec.func if isinstance(dec, ast.Call) else dec
        d = _dotted(target) or ""
        last = d.split(".")[-1]
        if last in {"task", "shared_task"} and ("celery" in d.lower() or d == "shared_task" or last == "task" and d.count(".") == 1):
            self.background.append({"kind": "celery_task", "target": fn.name, "line": fn.lineno, "scope": None})
        elif last == "actor" and "dramatiq" in d.lower() + " ".join(self.bindings.values()).lower():
            self.background.append({"kind": "dramatiq_actor", "target": fn.name, "line": fn.lineno, "scope": None})
        elif last == "exception_handler":
            self.hooks.append({"kind": "exception_handler", "line": fn.lineno})
        elif last == "on_event" and isinstance(dec, ast.Call) and dec.args and isinstance(dec.args[0], ast.Constant):
            self.background.append({"kind": "startup_hook" if dec.args[0].value == "startup" else "shutdown_hook",
                                    "target": fn.name, "line": fn.lineno, "scope": None})

    def _toplevel_assigned(self) -> list[str]:
        """Names bound at module level by assignments (also inside if/try/with/for), e.g. ``settings = Settings()``."""
        names: list[str] = []

        def targets(t: ast.AST) -> None:
            if isinstance(t, ast.Name):
                names.append(t.id)
            elif isinstance(t, (ast.Tuple, ast.List)):
                for e in t.elts:
                    targets(e)
            elif isinstance(t, ast.Starred):
                targets(t.value)

        def walk(body: list[ast.stmt]) -> None:
            for st in body:
                if isinstance(st, ast.Assign):
                    for t in st.targets:
                        targets(t)
                elif isinstance(st, (ast.AnnAssign, ast.AugAssign)):
                    targets(st.target)
                elif isinstance(st, (ast.If, ast.For, ast.While, ast.With, ast.AsyncWith, ast.AsyncFor)):
                    walk(st.body)
                    walk(getattr(st, "orelse", []))
                elif isinstance(st, ast.Try):
                    walk(st.body)
                    for h in st.handlers:
                        walk(h.body)
                    walk(st.orelse)
                    walk(st.finalbody)
        walk(self.tree.body)
        return sorted(set(names))[:500]

    # ------------------------------------------------------------------- output
    def _todos(self) -> list[int]:
        return [i for i, ln in enumerate(self.source.split("\n"), 1) if re.search(r"#\s*(TODO|FIXME|HACK|XXX)\b", ln)][:40]

    def facts(self) -> dict[str, Any]:
        self.visit(self.tree)
        calls = {q: [{"expr": e, "line": ln} for e, ln in sorted(c.items(), key=lambda kv: kv[1])] for q, c in self.calls.items()}
        return {
            "module": self.module, "is_package": self.is_package, "path": self.path,
            "bindings": self.bindings, "imports": self.import_stmts, "dynamic_imports": self.dynamic_imports[:50],
            "functions": self.functions, "classes": self.classes, "apps": self.apps, "routers": self.routers,
            "routes": self.routes, "includes": self.includes, "mounts": self.mounts,
            "handler_deps": self.handler_deps, "handler_annotations": self.handler_annotations, "dep_aliases": self.dep_aliases, "calls": calls,
            "refs": {q: sorted(r) for q, r in self.refs.items()},
            "env_vars": self.env_vars[:200], "background": self.background[:100], "auth_hints": self.auth_hints[:30],
            "sa_bases": self.sa_bases, "constants": self.constants, "entry": self.entry, "assigned": self._toplevel_assigned(),
            "excepts": self.excepts[:150], "risky": self.risky, "prints": self.prints, "secret_defaults": self.secret_defaults,
            "logger_calls": self.logger_calls, "hooks": self.hooks[:20], "todos": self._todos(),
            "line_count": count_lines(self.source), "parse_issues": self.parse_issues,
            "module_doc": scrub_text(ast.get_docstring(self.tree) or "", 300) or None,
        }


# Python 3.14 (PEP 758) allows `except A, B:` without parentheses; it means exactly `except (A, B):` (no `as` clause allowed).
_PEP758_EXCEPT = re.compile(r"^(?P<ind>\s*)except(?P<star>\*?)\s+(?P<types>[^(\s:#][^:#]*?,[^:#]*?)\s*:(?P<rest>.*)$")
_CONTINUATION = re.compile(r"(else|elif|except|finally)\b|[)\]}]")
MAX_PARSE_RECOVERIES = 20


def _is_statement_start(line: str) -> bool:
    return bool(line) and line[0] not in " \t#" and not _CONTINUATION.match(line)


def _top_level_span(lines: list[str], ln: int) -> tuple[int, int]:
    """1-based inclusive line range of the top-level statement (with its decorators) that contains line ``ln``."""
    start = ln
    while start > 1 and not _is_statement_start(lines[start - 1]):
        start -= 1
    while start > 1 and lines[start - 2].startswith("@"):
        start -= 1
    end = ln
    while end < len(lines) and not _is_statement_start(lines[end]):
        end += 1
    while end > start and not lines[end - 1].strip():
        end -= 1
    return start, end


def parse_tolerant(source: str, path: str) -> tuple[ast.Module, list[dict[str, Any]]]:
    """Parse with line-preserving recovery, so syntax the running Python does not support cannot silently drop a whole file.

    1. Syntax with an exact older equivalent (PEP 758 `except A, B:`) is rewritten on that line only.
    2. Otherwise the top-level statement containing the error is blanked (its lines become empty), and parsing is retried.
    Line numbers of everything else are unchanged. Every recovery is returned as an issue so callers can report it.
    Raises the original SyntaxError when nothing parseable remains or recovery does not converge."""
    try:
        return ast.parse(source, filename=path), []
    except SyntaxError as exc:
        original = exc
    lines = source.split("\n")
    issues: list[dict[str, Any]] = []
    for _ in range(MAX_PARSE_RECOVERIES):
        try:
            tree = ast.parse("\n".join(lines), filename=path)
        except SyntaxError as exc:
            ln = exc.lineno
            if not ln or not 1 <= ln <= len(lines):
                raise original from None
            m = _PEP758_EXCEPT.match(lines[ln - 1])
            if m and " as " not in m["types"]:
                lines[ln - 1] = f"{m['ind']}except{m['star']} ({m['types'].strip()}):{m['rest']}"
                issues.append({"kind": "compat_rewrite", "start_line": ln, "end_line": ln,
                               "detail": "Python 3.14 unparenthesised `except A, B:` read as `except (A, B):` (same meaning; line numbers unchanged)"})
                continue
            start, end = _top_level_span(lines, ln)
            if not any(lines[i].strip() for i in range(start - 1, end)):
                raise original from None
            for i in range(start - 1, end):
                lines[i] = ""
            issues.append({"kind": "skipped", "start_line": start, "end_line": end, "detail": f"SyntaxError at line {ln}: {_trunc(str(exc.msg), 80)}"})
            continue
        if not tree.body and any(i["kind"] == "skipped" for i in issues):
            raise original
        return tree, issues
    raise original


def parse_issue_warning(issues: list[dict[str, Any]]) -> str | None:
    """One honest sentence for AnalysisFile.parse_warning (<= 300 chars)."""
    skipped = [i for i in issues if i["kind"] == "skipped"]
    compat = [i for i in issues if i["kind"] == "compat_rewrite"]
    if skipped:
        spans = ", ".join(f"{i['start_line']}-{i['end_line']}" if i["end_line"] != i["start_line"] else str(i["start_line"]) for i in skipped[:6])
        return _trunc(f"Partially parsed: lines {spans} could not be parsed and were left out of the analysis ({skipped[0]['detail']})."
                      + (f" {len(compat)} line(s) read with a Python 3.14 compatibility rewrite." if compat else ""), 300)
    if compat:
        return _trunc("Parsed with a compatibility rewrite for Python 3.14 syntax (`except A, B:`) on line(s) " + ", ".join(str(i["start_line"]) for i in compat[:10]) + ".", 300)
    return None


def extract_facts(source: str, path: str) -> dict[str, Any]:
    """Parse ``source`` and return facts. Raises SyntaxError/ValueError/RecursionError/MemoryError to the caller.
    Recovered syntax problems are listed in ``facts["parse_issues"]`` (see parse_tolerant)."""
    return FactsExtractor(source, path).facts()


def parse_warning_for(exc: BaseException) -> str:
    if isinstance(exc, SyntaxError):
        return f"SyntaxError at line {exc.lineno or '?'}: {_trunc(str(exc.msg), 80)}"
    if isinstance(exc, RecursionError):
        return "Source too deeply nested to parse"
    if isinstance(exc, MemoryError):
        return "Source too large to parse safely"
    return f"{type(exc).__name__}: could not parse"
