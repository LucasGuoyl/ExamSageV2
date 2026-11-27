"""Source-bound learning notes; never a claim of expert verification."""
from typing import Literal

from pydantic import Field, StrictInt, field_validator, model_validator

from .domain import Model, SourceRef


class ReviewEvidence(Model):
    document_id: str = Field(min_length=1)
    page: StrictInt = Field(ge=1)
    source_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')


class SourceReview(Model):
    id: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,80}$')
    origin: Literal['user_note', 'agent_note']
    summary: str = Field(min_length=1, max_length=4000)
    targets: list[SourceRef] = Field(min_length=1, max_length=10)
    evidence: list[ReviewEvidence] = Field(min_length=1, max_length=20)
    review: Literal['unverified_note'] = 'unverified_note'

    @field_validator('summary')
    @classmethod
    def clean_summary(cls, value):
        if not value.strip() or '\0' in value:
            raise ValueError('Empty or invalid review summary')
        return value.strip()

    @model_validator(mode='after')
    def bound_targets(self):
        targets = {(r.document_id, r.page) for r in self.targets}
        evidence = {(r.document_id, r.page) for r in self.evidence}
        if (not targets <= evidence or len(targets) != len(self.targets)
                or len(evidence) != len(self.evidence)
                or any(r.block_id is not None or r.bbox is not None for r in self.targets)):
            raise ValueError('Notes require unique whole-page targets bound to evidence')
        return self


class SourceReviewRequest(Model):
    schema_version: Literal['source-review-request-v1']
    course_id: str
    workspace: str
    snapshot: str
    scope_digest: str = Field(pattern=r'^[a-f0-9]{64}$')
    pack_digest: str = Field(pattern=r'^[a-f0-9]{64}$')
    reviews: list[SourceReview] = Field(min_length=1, max_length=100)


def validate_reviews(reviews, manifest):
    if len({r.id for r in reviews}) != len(reviews):
        raise ValueError('Duplicate review identity')
    docs = {d.id: d for d in manifest.documents}
    for review in reviews:
        for ref in review.evidence:
            doc = docs.get(ref.document_id)
            if doc is None or ref.page > doc.pages or ref.source_sha256 != doc.sha256:
                raise ValueError('Review evidence does not match the source manifest')


def scoped_reviews(record, permitted):
    """Fail closed if any supporting source is unavailable or note is malformed."""
    result = []
    raw = record.details.get('source_reviews', [])
    if not isinstance(raw, list):
        return result
    for value in raw:
        try:
            note = SourceReview.model_validate(value)
        except ValueError:
            continue
        if (all(r.document_id in permitted for r in [*note.targets, *note.evidence])
                and any((r.document_id, r.page) in {(p.document_id, p.page) for p in record.refs}
                        for r in note.targets)):
            result.append(note.model_dump(mode='json'))
    return result


def collect_reviews(records):
    return list({r['id']: r for record in records
                 for r in record.details.get('source_reviews', [])}.values())


def review_warnings(reviews):
    return ['学习注记（尚未经独立学术核查）：' + r['summary'] for r in reviews]
