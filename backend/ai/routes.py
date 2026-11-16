from fastapi import APIRouter, File, UploadFile
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from .client import ModelClient, ModelError
from .config import Settings
from .review import audit_export, interpret_request
from .boundaries import suggest_boundaries
from .vision import enrich_visual_text
from .workflow import generate_registry
from ..input_documents import inspect_input
from ..registry import uid
from ..store import LOCK, now

router = APIRouter(prefix='/api')


class RunRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    revision: int
    replace_registry: bool = False
    pdf_mode: Literal['vision', 'text', 'native'] | None = None


class InterpretRequest(RunRequest):
    text: str = Field(min_length=1, max_length=3000)


class AuditRequest(RunRequest):
    export_id: str


def new_client(pid=None):
    from .. import main
    cache = main.store.folder(pid) / 'ai-cache' if pid else None
    return ModelClient(Settings.load(), cache_dir=cache)


def failed_run(pid, run, client):
    from .. import main
    with LOCK:
        current = main.load(pid)
        run.update(status='failed', finished=now(), calls=list(client.records))
        current.setdefault('ai_runs', []).append(run)
        main.store.save(current, 'AI operation failed; existing document text and register retained')


@router.post('/projects/{pid}/ai/generate')
def generate(pid: str, request: RunRequest):
    from .. import main
    with LOCK:
        original = main.load(pid)
        main.guard(original, request.revision)
        if original['concepts'] and not request.replace_registry:
            raise ModelError('Confirm registry replacement; previous corrections remain recoverable in history.')
        working = main.store.clone(original)
    client = new_client(pid)
    if request.pdf_mode:
        client.settings.pdf_mode = request.pdf_mode
    run = {'id': uid(), 'stage': 'registry_generation', 'started': now(), 'base_revision': request.revision}
    run['configuration'] = client.settings.provenance()
    try:
        enrich_visual_text(working, main.store.folder(pid), client, run)
        generate_registry(working, client, run)
        if not any(d['blocks'] for d in working['documents']):
            raise ModelError('No readable native or visually transcribed content was produced.')
        if run['coverage_gaps']:
            run['status'] = 'completed_with_gaps'
        run.update(finished=now(), calls=list(client.records))
        working.setdefault('ai_runs', []).append(run)
        working['plans'] = []
        with LOCK:
            main.guard(main.load(pid), request.revision)
            return main.store.save(working, 'Generated evidence-validated AI register and semantic links; reviewer confirmation required')
    except (ValueError, ModelError) as exc:
        run['error'] = str(exc)
        failed_run(pid, run, client)
        raise


@router.post('/projects/{pid}/ai/interpret')
def interpret(pid: str, request: InterpretRequest):
    from .. import main
    with LOCK:
        p = main.load(pid)
        main.guard(p, request.revision)
    client = new_client(pid)
    result = interpret_request(p, request.text, client)
    with LOCK:
        main.guard(main.load(pid), request.revision)
        p['last_interpretation'] = {**result, 'id': uid(), 'request': request.text}
        p.setdefault('ai_runs', []).append({'id': uid(), 'stage': 'interpretation', 'status': 'completed',
                                          'configuration': client.settings.provenance(), 'calls': client.records})
        return main.store.save(p, 'Interpreted natural-language naming request; proposed mappings require review')


@router.post('/projects/{pid}/ai/audit')
def semantic_audit(pid: str, request: AuditRequest):
    from .. import main
    with LOCK:
        p = main.load(pid)
        main.guard(p, request.revision)
    result = audit_export(p, request.export_id, new_client(pid))
    with LOCK:
        main.guard(main.load(pid), request.revision)
        p.setdefault('semantic_audits', []).append(result)
        return main.store.save(p, 'Saved advisory AI semantic audit; deterministic verification remains separate')


@router.post('/inspect/ai')
async def inspect_with_ai(file: UploadFile = File(...)):
    from .. import main
    content = await main.read_upload(file)
    info = inspect_input(content, include_boundary_context=True)
    inventory = info.pop('_boundary_inventory')
    client = new_client()
    result = await run_in_threadpool(suggest_boundaries, inventory, client, content)
    return {**info, 'ai_suggestion': result, 'model_calls': client.records,
            'notice': 'Model suggestion only. Verify independent documents and version compatibility manually.'}
