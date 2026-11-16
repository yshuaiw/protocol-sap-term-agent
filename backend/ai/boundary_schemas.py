from typing import Literal

from pydantic import Field

from .schemas import Strict, VisualSegment

Role = Literal['Protocol', 'SAP', 'unknown']
Kind = Literal['independent_document', 'embedded_section', 'reference', 'uncertain']
Confidence = Literal['high', 'medium', 'low']


class BoundaryCandidate(Strict):
    source_id: str
    role: Role
    kind: Kind
    confidence: Confidence
    reason: str = Field(min_length=1, max_length=600)


class BoundaryStarts(Strict):
    candidates: list[BoundaryCandidate] = Field(max_length=16)
    limitations: list[str] = Field(max_length=12)


class BoundaryRange(BoundaryCandidate):
    candidate_id: str
    end: int


class BoundaryRanges(Strict):
    documents: list[BoundaryRange] = Field(max_length=20)
    compatibility_note: str = Field(max_length=2000)


class BoundaryVisualPage(Strict):
    page: int
    segments: list[VisualSegment] = Field(max_length=60)
    limitations: list[str] = Field(max_length=12)


class BoundaryVisuals(Strict):
    pages: list[BoundaryVisualPage] = Field(max_length=3)
