from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from .local_access import local_mutation

router = APIRouter(prefix='/api/projects')


class DeleteRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    revision: int = Field(ge=1)
    confirmed: Literal[True]


@router.get('/{pid}/deletion')
def deletion_preview(pid: str):
    from . import main
    return main.store.deletion_summary(pid)


@router.delete('/{pid}')
def delete_project(pid: str, body: DeleteRequest, request: Request):
    from . import main
    local_mutation(request)
    return main.store.delete(pid, body.revision)
