"""Pydantic models shared by the engine and the backend. See docs/CONTRACT.md."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

SCHEMA_VERSION = "1.0"

FileType = Literal["csv", "xlsx"]
InferredType = Literal[
    "integer", "decimal", "date", "datetime", "boolean", "category", "text", "id", "empty"
]
Severity = Literal["high", "medium", "low"]
Mode = Literal["auto", "suggest", "flag"]

# Quality score weights (CONTRACT.md section 4.1).
WEIGHTS: dict[str, float] = {
    "completeness": 0.25,
    "validity": 0.25,
    "consistency": 0.20,
    "uniqueness": 0.15,
    "conformity": 0.15,
}


class SourceInfo(BaseModel):
    filename: str
    file_type: FileType
    encoding: str | None = None
    delimiter: str | None = None
    sheet: str | None = None
    header_row: int = 0


class ColumnQuality(BaseModel):
    score: float
    completeness: float
    validity: float
    consistency: float
    uniqueness: float
    conformity: float


class QualityScore(BaseModel):
    overall: float
    completeness: float
    validity: float
    consistency: float
    uniqueness: float
    conformity: float


class TopValue(BaseModel):
    value: str
    count: int


class FormatPattern(BaseModel):
    pattern: str
    count: int


class Issue(BaseModel):
    code: str
    severity: Severity
    message: str
    count: int


class ColumnProfile(BaseModel):
    name: str
    source_name: str
    position: int
    inferred_type: InferredType
    type_confidence: float
    row_count: int
    null_count: int
    null_pct: float
    distinct_count: int
    distinct_pct: float
    is_key_candidate: bool
    min: str | None = None
    max: str | None = None
    mean: float | None = None
    median: float | None = None
    min_length: int | None = None
    max_length: int | None = None
    top_values: list[TopValue] = Field(default_factory=list)
    samples: list[str] = Field(default_factory=list)
    format_patterns: list[FormatPattern] = Field(default_factory=list)
    issues: list[Issue] = Field(default_factory=list)
    quality: ColumnQuality


class ProposalSample(BaseModel):
    row_id: int | None = None
    before: str | None = None
    after: str | None = None


class Proposal(BaseModel):
    id: str
    rule_id: str
    rule_version: str
    column: str | None = None
    mode: Mode
    severity: Severity
    is_destructive: bool
    confidence: float | None = None
    title: str
    description: str
    rows_affected: int
    params: dict[str, Any] = Field(default_factory=dict)
    editable_params: list[str] = Field(default_factory=list)
    samples: list[ProposalSample] = Field(default_factory=list)


class DatasetProfile(BaseModel):
    schema_version: str = SCHEMA_VERSION
    source: SourceInfo
    row_count: int
    column_count: int
    duplicate_row_count: int
    empty_row_count: int
    quality: QualityScore
    columns: list[ColumnProfile]
    proposals: list[Proposal] = Field(default_factory=list)


class SheetInspection(BaseModel):
    name: str | None = None
    row_count_estimate: int
    detected_header_row: int
    preview: list[list[str]]


class FileInspection(BaseModel):
    filename: str
    file_type: FileType
    size_bytes: int
    sheets: list[SheetInspection]


# --------------------------------------------------------------------------- plan and results

class EditedProposal(BaseModel):
    id: str
    params: dict[str, Any] = Field(default_factory=dict)


class Decisions(BaseModel):
    approved: list[str] = Field(default_factory=list)
    rejected: list[str] = Field(default_factory=list)
    edited: list[EditedProposal] = Field(default_factory=list)   # editing implies approval


class PlanStep(BaseModel):
    rule_id: str
    rule_version: str
    column: str | None = None
    action: Literal["auto", "approved"]
    params: dict[str, Any] = Field(default_factory=dict)
    proposal_id: str | None = None


class ApprovedPlan(BaseModel):
    source: SourceInfo
    steps: list[PlanStep]


class ColumnScoreChange(BaseModel):
    name: str
    before: ColumnQuality | None = None
    after: ColumnQuality | None = None


class RuleSummary(BaseModel):
    rule_id: str
    action: Literal["auto", "approved"]
    changes: int
    columns: list[str] = Field(default_factory=list)


class ChangeSummary(BaseModel):
    total_changes: int
    cells_changed: int
    rows_removed: int
    columns_removed: int
    columns_added: int
    rows_before: int
    rows_after: int
    columns_before: int
    columns_after: int
    by_rule: list[RuleSummary] = Field(default_factory=list)


class CleanResult(BaseModel):
    run_id: str
    before: QualityScore
    after: QualityScore
    columns: list[ColumnScoreChange]
    summary: ChangeSummary
    files: dict[str, str]
    warnings: list[str] = Field(default_factory=list)
