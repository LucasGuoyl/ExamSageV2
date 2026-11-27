"""Validated model answer contract; source locations are always server supplied."""
from typing import Literal
from pydantic import Field
from .domain import Model


class Paragraph(Model):
    text: str = Field(min_length=1, max_length=10000)
    kind: Literal['source', 'derivation', 'assumption', 'insufficient']
    citations: list[str] = Field(default_factory=list, max_length=40)


class ModelAnswer(Model):
    paragraphs: list[Paragraph] = Field(min_length=1, max_length=30)
    limitations: list[str] = Field(default_factory=list, max_length=40)

