from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


Category = Literal['treatment', 'visit', 'endpoint', 'label']


class ExtractedMention(Strict):
    block_id: str
    term_text: str = Field(min_length=1, max_length=300,
        description='Only the verbatim term name, alias or abbreviation; never copy the entire source block or sentence unless it is itself the term.')
    context_quote: str = Field(min_length=1, max_length=2000,
        description='A verbatim quotation from this same block containing term_text exactly once; include enough context to distinguish repetitions.')
    canonical_name: str = Field(min_length=1, max_length=200)
    category: Category
    definition: str = Field(max_length=1500)
    reason: str = Field(min_length=1, max_length=1500)


class Extraction(Strict):
    mentions: list[ExtractedMention] = Field(max_length=250)


class DiscoveryRepair(Strict):
    rejected_id: str
    action: Literal['corrected', 'out_of_scope', 'unresolved']
    mentions: list[ExtractedMention] = Field(max_length=250)
    reason: str = Field(min_length=1, max_length=1500)


class DiscoveryRepairs(Strict):
    decisions: list[DiscoveryRepair] = Field(max_length=250)


class Link(Strict):
    candidate_id: str = Field(description='Copy the exact supplied candidate reference, such as C1.')
    group_id: str = Field(description='Use an exact existing ledger reference such as L1, or new: followed by a new group label. Never invent an existing ledger reference.')
    canonical_name: str = Field(min_length=1, max_length=200)
    category: Category
    definition: str = Field(max_length=1500)
    reason: str = Field(min_length=1, max_length=1500)
    ambiguous: bool


class Links(Strict):
    assignments: list[Link] = Field(max_length=40)


class Decision(Strict):
    mention_id: str
    decision: Literal['update', 'preserve', 'unresolved']
    reason: str = Field(min_length=1, max_length=1500)
    evidence: str = Field(min_length=1, max_length=3000)
    semantic_risk: bool


class Decisions(Strict):
    decisions: list[Decision] = Field(max_length=40)


class Interpretation(Strict):
    concept_id: str
    mappings: list['Mapping'] = Field(max_length=50)
    reason: str = Field(min_length=1, max_length=1500)
    semantic_risk: bool


class Mapping(Strict):
    old: str = Field(min_length=1, max_length=200)
    new: str = Field(min_length=1, max_length=200)


class VisualSegment(Strict):
    text: str = Field(min_length=1, max_length=6000)
    region: Literal['body', 'heading', 'table', 'header', 'footer', 'footnote_candidate', 'image_text']


class VisionResult(Strict):
    segments: list[VisualSegment] = Field(max_length=100)
    limitations: list[str] = Field(max_length=30)


class Boundary(Strict):
    role: Literal['Protocol', 'SAP', 'unknown']
    start: int = Field(ge=1)
    end: int = Field(ge=1)
    evidence: str = Field(min_length=1, max_length=3000)


class Boundaries(Strict):
    documents: list[Boundary] = Field(max_length=20)
    compatibility_note: str = Field(max_length=2000)


class AuditItem(Strict):
    block_id: str
    concern: str = Field(min_length=1, max_length=2000)
    evidence: str = Field(min_length=1, max_length=3000)


class SemanticAudit(Strict):
    findings: list[AuditItem] = Field(max_length=100)
    note: str = Field(max_length=2000)
