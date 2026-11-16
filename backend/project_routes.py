from typing import Literal
import asyncio

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

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


@router.post('/{pid}/cancel-delete')
async def cancel_delete(pid: str, body: DeleteRequest, request: Request):
    from . import main
    from .operations import OPERATIONS
    from .project_deletion import delete
    from .project_lifecycle import ProjectStateError
    from .store import LOCK
    local_mutation(request)
    def validate_revision():
        with LOCK:
            current = main.store.load(pid)
            if current['revision'] != body.revision:
                raise ProjectStateError('Project changed. Refresh its details and confirm deletion again.')
    # Reserve first: reject unrelated activity before cancelling anything and prevent new work.
    with main.store.activity.deletion(pid, cancel_llm=True):
        await run_in_threadpool(validate_revision)
        ids = [op['id'] for op in OPERATIONS.active(pid)]
        await run_in_threadpool(OPERATIONS.cancel, ids)
        while main.store.activity.active_count(pid) or OPERATIONS.active(pid):
            await asyncio.sleep(.05)
        # No late worker may recreate files; revision is checked again after the wait.
        return await run_in_threadpool(delete, main.store, pid, body.revision, reserved=True)
