"""Versioned curriculum metadata, separate from subject knowledge and user state."""
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, JsonValue, StringConstraints, model_validator

from .domain import Model, SourceRef

Identifier = Annotated[str, StringConstraints(pattern=r'^[a-z0-9_-]{1,80}$')]
Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]

CURRICULUM_LABELS = {'curriculum_system':'体系', 'institution':'学校', 'stage':'学段',
                     'syllabus_version':'大纲', 'language':'语言'}


def course_registration(store, scope):
    """Only identifying labels, never outcomes, citations or review details."""
    profile = (store.metadata(scope) or {}).get('course_profile') or {}
    return {key: profile[key] for key in CURRICULUM_LABELS
            if isinstance(profile.get(key), str) and profile[key] not in ('', 'unspecified')}


class Outcome(Model):
    id: Identifier
    description: Label
    refs: list[SourceRef] = Field(min_length=1)
    record_ids: list[str] = Field(min_length=1)


class CourseProfile(Model):
    schema_version: Literal['course-profile-v1'] = 'course-profile-v1'
    course_id: Identifier
    curriculum_system: Label
    institution: Label | None
    stage: Label
    language: Label
    syllabus_version: Label
    disciplines: list[Label] = Field(min_length=1)
    material_status: Literal['demonstration', 'imported_course_material']
    outcomes: list[Outcome] = Field(default_factory=list)

    @model_validator(mode='after')
    def unique_outcomes(self):
        if len({o.id for o in self.outcomes}) != len(self.outcomes):
            raise ValueError('Duplicate learning outcome')
        return self

    def summary(self):
        # Outcomes may contain restricted source content; catalogue metadata does not.
        return self.model_dump(mode='json', exclude={'outcomes'})

    def scoped(self, store, scope):
        permitted = store.permitted_documents(scope)
        outcomes = [o.model_dump(mode='json') for o in self.outcomes
                    if all(r.document_id in permitted for r in o.refs)
                    and all(store.get(scope, rid) is not None for rid in o.record_ids)]
        report = (store.metadata(scope) or {}).get('import_report') or {}
        pages = [dict(p) for p in report.get('page_reviews', []) if p['document_id'] in permitted]
        source_review = None if 'page_reviews' not in report else {
            'pages': len(pages), 'failed_pages': sum(p['status'] == 'failed' for p in pages),
            'partial_pages': sum(p['status'] == 'partial' for p in pages),
            'hidden_pages': sum(p['hidden'] for p in pages),
            'page_reviews': pages, 'semantic_review': 'pending'}
        return {**self.summary(), 'outcomes': outcomes, 'source_review': source_review,
                'unavailable_outcomes': len(self.outcomes) - len(outcomes),
                'validation': 'source_locations_only_not_curriculum_accreditation'}


class DerivationStep(Model):
    text: Label
    refs: list[SourceRef] = Field(min_length=1)


class AcademicAnnotation(Model):
    nature: Literal['source_text', 'author_claim', 'interpretation', 'derivation', 'marking_guide']
    assumptions: list[Label] = Field(default_factory=list)
    evidence_record_ids: list[str] = Field(default_factory=list)
    counter_record_ids: list[str] = Field(default_factory=list)
    steps: list[DerivationStep] = Field(default_factory=list)

    @model_validator(mode='after')
    def evidence_required(self):
        if self.nature in {'author_claim', 'interpretation'} and not self.evidence_record_ids:
            raise ValueError('Claims and interpretations need explicit evidence records')
        if self.nature == 'derivation' and not self.steps:
            raise ValueError('Derivation needs ordered steps with source references')
        return self


class PackRecordDetails(Model):
    """Only versioned fields may enter code-consumed details through an import.

    Arbitrary course metadata belongs under extensions, which retrieval does not
    interpret as its own audit/recovery/visibility protocol.
    """
    model_config = ConfigDict(extra='forbid', strict=True, allow_inf_nan=False)
    academic: AcademicAnnotation | None = None
    exam_year: int | None = None
    number: str | None = None
    part: str | None = None
    extensions: dict[str, JsonValue] = Field(default_factory=dict)
