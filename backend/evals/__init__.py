"""Raven evaluation harness: deterministic metrics against a versioned, hand-labelled benchmark, plus optional LLM-as-judge (DeepEval).

Run from `backend/`:  python -m evals --help
Never imported by the Raven application; excluded from the runtime image (.dockerignore).
"""
HARNESS_VERSION = "1.0.0"
