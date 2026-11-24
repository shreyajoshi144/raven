"""Deterministic metrics. Pure functions over plain data (no database, no LLM) so they are unit-testable.

Conventions
- Every metric is a dict with `value` (float, or None when undefined), `n` (sample count) and the raw counts behind it.
- Precision is reported only for exhaustive label sets; otherwise `value` is None and `status` says why.
- Undefined ratios (0/0) are None, never 0 or 1, so an empty category cannot inflate or deflate a score.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from evals.benchmark import GroundTruth, ImpactCase, QAItem, Route, Span, is_test_file

QA_ANSWER_SOURCES = {"ai", "retrieval_only"}
QA_CONFIDENCE = {"high", "medium", "low"}
QA_SUFFICIENCY = {"sufficient", "insufficient"}


def ratio(num: float, den: float) -> float | None:
    return round(num / den, 4) if den else None


def f1(precision: float | None, recall: float | None) -> float | None:
    if precision is None or recall is None:
        return None
    return round(2 * precision * recall / (precision + recall), 4) if precision + recall else 0.0


def prf(pred: Iterable[Any], gold: Iterable[Any], exhaustive: bool = True) -> dict[str, Any]:
    p, g = set(pred), set(gold)
    tp, fp, fn = len(p & g), len(p - g), len(g - p)
    precision = ratio(tp, tp + fp) if exhaustive else None
    recall = ratio(tp, tp + fn)
    return {"tp": tp, "fp": fp if exhaustive else None, "fn": fn, "precision": precision, "recall": recall, "f1": f1(precision, recall), "n_pred": len(p), "n_gold": len(g),
            "exhaustive": exhaustive, "missing": sorted(map(str, g - p))[:50], "extra": sorted(map(str, p - g))[:50] if exhaustive else []}


def micro(parts: list[dict[str, Any]]) -> dict[str, Any]:
    """Micro-average several prf() results (sums counts; precision only over exhaustive parts)."""
    tp = sum(x["tp"] for x in parts)
    fn = sum(x["fn"] for x in parts)
    ex = [x for x in parts if x["exhaustive"]]
    tp_ex, fp_ex = sum(x["tp"] for x in ex), sum(x["fp"] for x in ex)
    precision = ratio(tp_ex, tp_ex + fp_ex) if ex else None
    recall = ratio(tp, tp + fn)
    return {"tp": tp, "fp": fp_ex, "fn": fn, "precision": precision, "recall": recall, "f1": f1(precision, recall), "n_gold": tp + fn, "parts": len(parts)}


def overlaps(path: str, start: int, end: int, span: Span) -> bool:
    return path == span.path and not (end < span.start_line or start > span.end_line)


_DYN = re.compile(r"^/\{\?[^}]*\}")


def norm_route_path(path: str | None) -> str:
    """Strip a leading unresolved dynamic prefix segment such as `/{?settings.API_V1_STR}` and collapse slashes."""
    p = _DYN.sub("", path or "")
    p = re.sub(r"/{2,}", "/", p)
    return p or "/"


# ------------------------------------------------------------------ graph
def score_graph(gt: GroundTruth, nodes: list[dict[str, Any]], edges: list[dict[str, Any]], entry_points: list[dict[str, Any]]) -> dict[str, Any]:
    g = gt.graph
    by_id = {n["id"]: n for n in nodes}
    pred_routes, route_lines = set(), {}
    for n in nodes:
        if n["type"] == "route":
            key = (n["meta"].get("method"), norm_route_path(n["meta"].get("full_path")), n["path"])
            pred_routes.add(key)
            route_lines[key] = n["start_line"]
    gold_routes = {}
    for r in g.routes.items:
        rt = Route.model_validate(r)
        gold_routes[(rt.method, norm_route_path(rt.path), rt.handler_file)] = rt
    routes = prf(pred_routes, gold_routes, g.routes.exhaustive)
    matched = [k for k in gold_routes if k in pred_routes]
    line_ok = sum(1 for k in matched if gold_routes[k].decorator_line <= (route_lines.get(k) or 0) <= gold_routes[k].def_line)
    routes["line_accuracy"] = ratio(line_ok, len(matched))

    models = [n for n in nodes if n["type"] == "model"]
    data_models = prf({(n["name"], n["path"]) for n in models}, {(m["name"], m["path"]) for m in g.data_models.items}, g.data_models.exhaustive)
    orm = prf({(n["name"], n["path"]) for n in models if n["meta"].get("model_kind") == "sqlalchemy"}, {(m["name"], m["path"]) for m in g.orm_models.items}, g.orm_models.exhaustive)

    pred_imports, resolution = set(), {}
    for e in edges:
        s, t = by_id.get(e["source"]), by_id.get(e["target"])
        if e["relation"] == "imports" and s and t and s["type"] in ("module", "test") and t["type"] in ("module", "test") and s["path"] and t["path"]:
            pred_imports.add((s["path"], t["path"]))
            resolution[(s["path"], t["path"])] = e["resolution"]
    gold_imports = {tuple(x) for x in g.internal_imports.items}
    imports = prf(pred_imports, gold_imports, g.internal_imports.exhaustive)
    hit = [k for k in gold_imports if k in pred_imports]
    imports["verified_static_share"] = ratio(sum(1 for k in hit if resolution.get(k) == "verified_static"), len(hit))
    entry = prf({e["path"] for e in entry_points}, set(g.entry_points.items), g.entry_points.exhaustive)
    return {"routes": routes, "data_models": data_models, "orm_models": orm, "internal_imports": imports, "entry_points": entry}


# ------------------------------------------------------------------ readiness
def score_readiness(gt: GroundTruth, findings: list[dict[str, Any]]) -> dict[str, Any]:
    rt = gt.readiness
    assessed = set(rt.assessed_rules)
    found = [f for f in findings if f["rule"] in assessed]
    pred_rules = {f["rule"] for f in found}
    gold_rules = {e.rule for e in rt.expected}
    rule_level = prf(pred_rules, gold_rules, True)
    rule_level["tn"] = len(assessed - pred_rules - gold_rules)
    rule_level["assessed"] = len(assessed)
    # location level: only rules whose expected entry carries evidence spans, plus every predicted location of an assessed rule
    gold_spans = [(e.rule, s) for e in rt.expected for s in e.evidence]
    absence_like = {e.rule for e in rt.expected if not e.evidence}
    pred_locs = [(f["rule"], ev["path"], ev["start_line"]) for f in found if f["rule"] not in absence_like for ev in f.get("evidence", [])]
    matched_gold, fp_locs = set(), []
    for rule, path, line in pred_locs:
        hits = [i for i, (r, s) in enumerate(gold_spans) if r == rule and overlaps(path, line, line, s)]
        if hits:
            matched_gold.update(hits)
        else:
            fp_locs.append(f"{rule} {path}:{line}")
    tp = len(matched_gold)
    fn_locs = [f"{r} {s.path}:{s.start_line}" for i, (r, s) in enumerate(gold_spans) if i not in matched_gold]
    truncated = [f["rule"] for f in found if f.get("evidence_total", 0) > len(f.get("evidence", []))]
    loc = {"tp": tp, "fp": len(fp_locs), "fn": len(fn_locs), "precision": ratio(tp, tp + len(fp_locs)), "recall": ratio(tp, tp + len(fn_locs)),
           "false_positives": fp_locs[:50], "false_negatives": fn_locs[:50], "rules_with_truncated_evidence": truncated}
    per_rule = {r: ("TP" if r in pred_rules and r in gold_rules else "FP" if r in pred_rules else "FN" if r in gold_rules else "TN") for r in sorted(assessed)}
    return {"rule_level": rule_level, "location_level": loc, "per_rule": per_rule, "unassessed_findings": sorted({f["rule"] for f in findings} - assessed)}


# ------------------------------------------------------------------ impact
def score_impact(case: ImpactCase, result: dict[str, Any]) -> dict[str, Any]:
    exp = case.expected
    mods = prf({a["path"] for a in result.get("affected", [])}, exp["affected_modules"].items, exp["affected_modules"].exhaustive)
    routes = prf({f"{r['method']} {norm_route_path(r['path'])}" for r in result.get("routes", [])},
                 {f"{x.split(' ', 1)[0]} {norm_route_path(x.split(' ', 1)[1])}" for x in exp["routes"].items}, exp["routes"].exhaustive)
    listed = [t["path"] for t in result.get("tests", [])]
    tests = prf({p for p in listed if is_test_file(p)}, exp["relevant_tests"].items, exp["relevant_tests"].exhaustive)
    tests["ignored_non_test_files"] = sorted(p for p in listed if not is_test_file(p))
    return {"affected_modules": mods, "routes": routes, "relevant_tests": tests}


# ------------------------------------------------------------------ retrieval
def score_retrieval(q: QAItem, evidence: list[dict[str, Any]]) -> dict[str, Any]:
    if not q.answerable:
        return {"answerable": False, "n_retrieved": len(evidence), "empty": not evidence}
    rel = [any(overlaps(e["path"], e["start_line"], e["end_line"], s) for s in q.evidence) for e in evidence]
    covered = [any(overlaps(e["path"], e["start_line"], e["end_line"], s) for e in evidence) for s in q.evidence]
    first = next((i for i, r in enumerate(rel) if r), None)
    return {"answerable": True, "n_retrieved": len(evidence), "span_recall": ratio(sum(covered), len(covered)),
            "hit@1": bool(rel[:1] and rel[0]), "hit@3": any(rel[:3]), "hit@5": any(rel[:5]), "hit@all": any(rel),
            "reciprocal_rank": round(1 / (first + 1), 4) if first is not None else 0.0, "snippet_precision": ratio(sum(rel), len(rel)),
            "missed_spans": [f"{s.path}:{s.start_line}-{s.end_line}" for s, c in zip(q.evidence, covered) if not c]}


def aggregate_retrieval(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ans = [r for r in rows if r["answerable"]]
    un = [r for r in rows if not r["answerable"]]
    mean = lambda k: ratio(sum(r[k] for r in ans if r[k] is not None), len([r for r in ans if r[k] is not None]))  # noqa: E731
    return {"n_answerable": len(ans), "n_unanswerable": len(un), "span_recall": mean("span_recall"), "mrr": mean("reciprocal_rank"),
            "hit@1": ratio(sum(r["hit@1"] for r in ans), len(ans)), "hit@3": ratio(sum(r["hit@3"] for r in ans), len(ans)),
            "hit@5": ratio(sum(r["hit@5"] for r in ans), len(ans)), "hit@all": ratio(sum(r["hit@all"] for r in ans), len(ans)),
            "snippet_precision": mean("snippet_precision"), "unanswerable_empty_retrieval_rate": ratio(sum(r["empty"] for r in un), len(un))}


# ------------------------------------------------------------------ Q&A (deterministic)
def structure_problems(msg: dict[str, Any]) -> list[str]:
    p = []
    if msg.get("status") != "complete":
        p.append(f"status={msg.get('status')}")
    if msg.get("answer_source") not in QA_ANSWER_SOURCES:
        p.append(f"answer_source={msg.get('answer_source')!r}")
    if msg.get("confidence") not in QA_CONFIDENCE:
        p.append(f"confidence={msg.get('confidence')!r}")
    if msg.get("evidence_sufficiency") not in QA_SUFFICIENCY:
        p.append(f"evidence_sufficiency={msg.get('evidence_sufficiency')!r}")
    if not isinstance(msg.get("content"), str) or not msg["content"].strip():
        p.append("empty content")
    if not isinstance(msg.get("inferred"), list) or not all(isinstance(x, str) for x in msg["inferred"]):
        p.append("inferred is not a list of strings")
    for c in msg.get("citations") or []:
        if not (isinstance(c.get("path"), str) and isinstance(c.get("start_line"), int) and isinstance(c.get("end_line"), int)):
            p.append("malformed citation")
            break
    if msg.get("answer_source") == "retrieval_only" and msg.get("inferred"):
        p.append("retrieval-only answer carries inferred claims")
    return p


def key_fact_recall(q: QAItem, text: str) -> float | None:
    if not q.key_facts:
        return None
    low = text.lower()
    return ratio(sum(1 for group in q.key_facts if any(alt.lower() in low for alt in group)), len(q.key_facts))


def score_answer(q: QAItem, msg: dict[str, Any], line_counts: dict[str, int]) -> dict[str, Any]:
    cites = msg.get("citations") or []
    valid = [c for c in cites if c.get("path") in line_counts and 1 <= c["start_line"] <= c["end_line"] <= max(line_counts[c["path"]], 1)]
    ai = msg.get("answer_source") == "ai"
    abstained = msg.get("evidence_sufficiency") == "insufficient"
    row: dict[str, Any] = {"id": q.id, "answerable": q.answerable, "answer_source": msg.get("answer_source"), "confidence": msg.get("confidence"),
                           "abstained": abstained, "n_citations": len(cites), "structure_problems": structure_problems(msg),
                           "citation_validity": ratio(len(valid), len(cites)), "n_inferred": len(msg.get("inferred") or []), "error_code": msg.get("error_code")}
    if q.answerable:
        support = [any(overlaps(c["path"], c["start_line"], c["end_line"], s) for s in q.evidence) for c in valid]
        covered = [any(overlaps(c["path"], c["start_line"], c["end_line"], s) for c in valid) for s in q.evidence]
        row["citation_support_precision"] = ratio(sum(support), len(cites))  # invalid citations count as unsupported
        row["citation_recall"] = ratio(sum(covered), len(covered))
        row["key_fact_recall"] = key_fact_recall(q, msg.get("content") or "") if ai else None
        row["correct_deterministic"] = bool(ai and not abstained and row["key_fact_recall"] == 1.0 and (row["citation_support_precision"] or 0) > 0)
    else:
        row["correct_deterministic"] = bool(ai and abstained)
    return row


def aggregate_answers(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ai = [r for r in rows if r["answer_source"] == "ai"]
    ai_ans = [r for r in ai if r["answerable"]]
    ai_un = [r for r in ai if not r["answerable"]]
    with_cites = [r for r in rows if r["n_citations"]]

    def mean(rs: list[dict[str, Any]], k: str) -> float | None:
        vals = [r[k] for r in rs if r.get(k) is not None]
        return ratio(sum(vals), len(vals))
    by_conf = {}
    for label in ("high", "medium", "low"):
        rs = [r for r in ai_ans if r["confidence"] == label]
        by_conf[label] = {"n": len(rs), "deterministic_accuracy": ratio(sum(r["correct_deterministic"] for r in rs), len(rs))}
    return {
        "n": len(rows), "n_answerable": sum(1 for r in rows if r["answerable"]), "n_with_citations": len(with_cites), "n_ai": len(ai), "n_retrieval_only": sum(1 for r in rows if r["answer_source"] == "retrieval_only"),
        "structured_output_valid_rate": ratio(sum(1 for r in rows if not r["structure_problems"]), len(rows)),
        "citation_validity": mean(with_cites, "citation_validity"),
        "citation_support_precision": mean([r for r in rows if r["answerable"] and r["n_citations"]], "citation_support_precision"),
        "citation_recall": mean([r for r in rows if r["answerable"]], "citation_recall"),
        "key_fact_recall_ai": mean(ai_ans, "key_fact_recall"),
        "deterministic_accuracy_ai": ratio(sum(r["correct_deterministic"] for r in ai), len(ai)),
        "abstention_recall_ai": ratio(sum(r["abstained"] for r in ai_un), len(ai_un)),
        "false_abstention_rate_ai": ratio(sum(r["abstained"] for r in ai_ans), len(ai_ans)),
        "accuracy_by_confidence_ai": by_conf,
        "llm_error_codes": sorted({r["error_code"] for r in rows if r["error_code"]}),
    }
