from app.services.qa import confidence_label

EV = [{"path": "a.py", "start_line": 10, "end_line": 30, "reason": "matches symbol `f`"},
      {"path": "b.py", "start_line": 1, "end_line": 20, "reason": "related to `f` via imports"},
      {"path": "c.py", "start_line": 5, "end_line": 9, "reason": "source text matches question terms"}]


def cite(path, s, e):
    return [{"path": path, "start_line": s, "end_line": e}]


def test_high_requires_direct_evidence_overlap_and_no_inferred_claims():
    assert confidence_label("sufficient", cite("a.py", 12, 14), EV, False) == "high"
    assert confidence_label("sufficient", cite("a.py", 12, 14), EV, True) == "medium"      # inferred claims cap it
    assert confidence_label("sufficient", cite("b.py", 2, 3), EV, False) == "medium"       # only a related neighbour
    assert confidence_label("sufficient", cite("c.py", 5, 6), EV, False) == "medium"       # only a text match
    assert confidence_label("sufficient", cite("a.py", 40, 41), EV, False) == "medium"     # cited lines outside the direct hit


def test_low_when_insufficient_or_uncited():
    assert confidence_label("insufficient", cite("a.py", 12, 14), EV, False) == "low"
    assert confidence_label("sufficient", [], EV, False) == "low"
