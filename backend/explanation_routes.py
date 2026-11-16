"""Reviewer decisions on individual sourced explanation claims."""
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from .ai.explanations import evidence_current
from .local_access import local_mutation
from .store import LOCK

router = APIRouter(prefix='/api/projects')


class ClaimReview(BaseModel):
    model_config = ConfigDict(extra='forbid')
    revision: int
    claim_id: str
    decision: Literal['pending', 'accepted', 'rejected']
    note: str = Field(default='', max_length=2000)


@router.put('/{pid}/explanations/{cid}')
def review(pid: str, cid: str, body: ClaimReview, request: Request):
    from . import main
    local_mutation(request)
    with LOCK:
        project = main.load(pid)
        main.guard(project, body.revision)
        concept = next((c for c in project['concepts'] if c['id'] == cid), None)
        claim = next((c for c in (concept or {}).get('explanation', {}).get('claims', []) if c['id'] == body.claim_id), None)
        if not claim:
            raise ValueError('Unknown sourced explanation claim.')
        if body.decision == 'accepted' and not evidence_current(claim, project['documents']):
            raise ValueError('Explanation evidence changed. Update explanations before accepting this claim.')
        claim.update(review=body.decision, review_note=body.note)
        return main.store.save(project, 'Reviewed a sourced explanation claim; document text unchanged')
