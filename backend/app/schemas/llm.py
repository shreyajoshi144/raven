"""Pydantic schemas for every model response (validated before use)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class Citation(BaseModel):
    path: str = Field(min_length=1, max_length=1000)
    start_line: int = Field(ge=1, le=10_000_000)
    end_line: int = Field(ge=1, le=10_000_000)

    @field_validator("path")
    @classmethod
    def _no_traversal(cls, v: str) -> str:
        if v.startswith("/") or ".." in v.split("/") or "\\" in v or "\x00" in v:
            raise ValueError("invalid path")
        return v


class SymbolExplanation(BaseModel):
    qualname: str = Field(min_length=1, max_length=300)
    summary: str = Field(min_length=1, max_length=400)


class FileExplanation(BaseModel):
    path: str = Field(min_length=1, max_length=1000)
    summary: str = Field(min_length=1, max_length=700)
    responsibilities: list[str] = Field(default_factory=list, max_length=5)
    symbols: list[SymbolExplanation] = Field(default_factory=list, max_length=10)
    citations: list[Citation] = Field(default_factory=list, max_length=5)

    @field_validator("responsibilities")
    @classmethod
    def _bounded(cls, v: list[str]) -> list[str]:
        return [x[:200] for x in v]


class ExplainBatch(BaseModel):
    explanations: list[FileExplanation] = Field(max_length=40)


class Overview(BaseModel):
    overview: str = Field(min_length=1, max_length=2000)
    key_flows: list[str] = Field(default_factory=list, max_length=5)
    citations: list[Citation] = Field(default_factory=list, max_length=8)

    @field_validator("key_flows")
    @classmethod
    def _bounded(cls, v: list[str]) -> list[str]:
        return [x[:300] for x in v]


class QAAnswer(BaseModel):
    answer: str = Field(min_length=1, max_length=5000)
    citations: list[Citation] = Field(default_factory=list, max_length=12)
    evidence_sufficiency: Literal["sufficient", "insufficient"]
    inferred: list[str] = Field(default_factory=list, max_length=5)
    limitations: list[str] = Field(default_factory=list, max_length=5)

    @field_validator("limitations", "inferred")
    @classmethod
    def _bounded(cls, v: list[str]) -> list[str]:
        return [x[:300] for x in v]
