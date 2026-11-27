from __future__ import annotations

from datetime import date
from hashlib import sha256
import json
from pathlib import PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def digest(value: Any) -> str:
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def record_source_id(course_id, scope, content_hash):
    return 'src_' + digest([course_id, scope.model_dump(mode='json'), content_hash])


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


DocumentKind = Literal["lecture", "exam", "formula_sheet", "tutorial_feedback", "practice", "mock_exam", "exam_guidance", "exam_solution", "primary_source", "literary_text", "assessment_rubric", "textbook", "unknown"]


class PaperSelection(Model):
    """File roles proposed for one lookup; the snapshot manifest remains authoritative."""
    exam_year: int = Field(strict=True, ge=1900, le=2199)
    paper_id: str = Field(strict=True, min_length=1, max_length=256)
    solution_id: str | None = Field(default=None, strict=True, min_length=1, max_length=256)


class Document(Model):
    id: str
    relative_path: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    kind: DocumentKind
    pages: int = Field(ge=1)
    exam_year: int | None = None
    document_date: date | None = None
    available_from: date | None = None
    teaching_year: str | None = None
    date_evidence: str | None = None
    asset: str | None = None

    def availability(self, received_on_utc):
        if self.available_from is None:
            return None
        day = self.available_from.isoformat()
        return {'known_by':day, 'basis':'project_receipt' if day == received_on_utc else 'manifest_date',
                'file_sha256':self.sha256}

    @field_validator("relative_path", "asset")
    @classmethod
    def safe_relative(cls, value):
        if value is None:
            return value
        value = value.replace("\\", "/")
        if PurePosixPath(value).is_absolute() or ".." in PurePosixPath(value).parts or ":" in value:
            raise ValueError("relative asset paths only")
        return value


class Manifest(Model):
    schema_version: str = "course-manifest-v1"
    course_key: str
    course_name: str
    aliases: list[str] = Field(default_factory=list)
    documents: list[Document]

    @model_validator(mode="after")
    def unique(self):
        if len({d.id for d in self.documents}) != len(self.documents):
            raise ValueError("duplicate document identity")
        return self


class SourceRef(Model):
    document_id: str
    page: int = Field(ge=1)
    block_id: str | None = None
    bbox: tuple[float, float, float, float] | None = None

    @field_validator("bbox")
    @classmethod
    def valid_box(cls, box):
        if box is not None and not (0 <= box[0] < box[2] <= 1 and 0 <= box[1] < box[3] <= 1):
            raise ValueError("invalid normalized box")
        return box


Review = Literal["candidate", "machine_checked", "agent_source_checked", "expert_checked"]


class Record(Model):
    id: str
    kind: Literal["block", "concept", "formula", "example", "question", "answer", "proof", "claim", "interpretation", "event", "rubric"]
    title: str
    text: str
    refs: list[SourceRef] = Field(min_length=1)
    parent_id: str | None = None
    topic: str | None = None
    aliases: list[str] = Field(default_factory=list)
    visibility: Literal["visible", "notes", "hidden"] = "visible"
    review: Review = "candidate"
    details: dict[str, Any] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)


class Relation(Model):
    id: str
    source: str
    target: str
    kind: Literal["explains", "assesses", "uses_formula", "prerequisite", "related", "has_answer", "supports", "contradicts", "interprets", "precedes"]
    refs: list[SourceRef] = Field(min_length=1)
    origin: Literal["explicit", "inferred"] = "inferred"
    review: Review = "candidate"


class Page(Model):
    document_id: str
    number: int = Field(ge=1)
    text: str
    notes: str = ""
    hidden: bool = False
    image_count: int | None = Field(default=None, ge=0)
    visual_status: Literal["not_reviewed", "agent_reviewed", "expert_reviewed"] = "not_reviewed"
    status: Literal["text_extracted", "partial", "failed"] = "partial"
    issues: list[str] = Field(default_factory=list)
    assets: list[str] = Field(default_factory=list)
    render: dict[str, Any] | None = None
    visual_review: dict[str, Any] | None = None
    supplement: dict[str, Any] | None = None


class Scope(Model):
    workspace: str
    course: str
    snapshot: str
    allowed_sources: list[str]
    cutoff: date | None = None
    strict_history: bool = False

    @model_validator(mode="after")
    def cutoff_required(self):
        if self.strict_history and self.cutoff is None:
            raise ValueError("strict historical queries require cutoff")
        return self


class Bundle(Model):
    snapshot: str
    records: list[Record] = Field(default_factory=list)
    relations: list[Relation] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    mode: str = "structured"
    sufficiency: Literal["unassessed", "insufficient"] = "unassessed"
    elapsed_ms: float = 0
