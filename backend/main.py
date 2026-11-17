import hashlib
import io
import json
import os
import re
import zipfile
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from .input_documents import inspect_input, parse_input
from .ai.routes import router as ai_router, new_client
from .ai.settings_routes import router as settings_router
from .ai.review import review_plan
from .exporting import export_pair
from .registry import CATEGORIES, build_registry, reindex_after_edits, rescan, uid
from .revisions import patch_blocks, preview
from .store import LOCK, Store
from .project_lifecycle import ProjectOperationMiddleware
from .project_routes import router as project_router
from .operation_routes import router as operation_router, OperationMiddleware
from .explanation_routes import router as explanation_router

ROOT = Path(__file__).resolve().parents[1]
store = Store(os.environ.get('TERM_AGENT_DATA', ROOT / 'data' / 'projects'))
app = FastAPI(title='Protocol SAP Terminology Agent', version='0.2.0')
app.include_router(ai_router)
app.include_router(settings_router)
app.include_router(project_router)
app.include_router(operation_router)
app.include_router(explanation_router)
app.add_middleware(ProjectOperationMiddleware, store_getter=lambda: store)
app.add_middleware(OperationMiddleware, store_getter=lambda: store)


@app.exception_handler(ValueError)
async def invalid_request(request, exc):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=getattr(exc, 'status_code', 400), content={'detail': str(exc)})


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class ConceptEdit(Strict):
    revision: int
    name: str = Field(min_length=1, max_length=200)
    category: str
    aliases: list[str] = Field(default_factory=list, max_length=50)
    confirmed: bool = False
    note: str = Field(default='', max_length=2000)


class MentionEdit(Strict):
    revision: int
    concept_id: str
    status: str


class PlanRequest(Strict):
    revision: int
    concept_id: str
    mappings: dict[str, str]
    mode: str = 'ai'


class ApplyRequest(Strict):
    revision: int
    approved_ids: list[str]
    coverage_acknowledged: bool = False


class RestoreRequest(Strict):
    revision: int
    snapshot: int


def guard(project, revision):
    if project['revision'] != revision:
        raise ValueError('Project changed in another tab. Reload before saving.')


def load(pid):
    project = store.load(pid)
    store.validate_sources(project)
    return project


async def read_upload(file, max_size=50 * 1024 * 1024):
    content = await file.read(max_size + 1)
    if len(content) > max_size:
        raise ValueError('Upload exceeds size limit.')
    return content


@app.get('/api/health')
def health():
    return {'status': 'ok', 'version': app.version, 'engine': 'provider-ai-v1', 'model_calls_on_startup': False}


@app.post('/api/inspect')
async def inspect(file: UploadFile = File(...)):
    content = await read_upload(file)
    try:
        return inspect_input(content)
    except Exception as exc:
        raise ValueError('Could not inspect document. Use a valid unlocked PDF or macro-free DOCX.') from exc


@app.get('/api/projects')
def projects():
    return store.list()


@app.post('/api/projects')
async def create(name: str = Form(...), selections: str = Form(...), version_note: str = Form(''),
                 files: list[UploadFile] = File(...), engine: str = Form('ai')):
    if not name.strip() or len(name) > 200:
        raise ValueError('Enter a project name of 1 to 200 characters.')
    try:
        choices = json.loads(selections)
    except json.JSONDecodeError as exc:
        raise ValueError('Invalid document selections.') from exc
    if len(files) not in (1, 2) or len(choices) != 2 or {c['role'] for c in choices} != {'Protocol', 'SAP'}:
        raise ValueError('Select independent Protocol/SAP PDF or DOCX files, or nonoverlapping ranges in one combined PDF.')
    contents = [await read_upload(f) for f in files]
    documents, inputs = [], {}
    for choice in choices:
        index = choice['file_index']
        if type(index) is not int or not 0 <= index < len(contents):
            raise ValueError('Invalid input file selection.')
        if type(choice['start']) is not int or type(choice['end']) is not int:
            raise ValueError('Page bounds must be integers.')
        content = contents[index]
        try:
            doc = parse_input(content, choice['role'], choice['start'], choice['end'], Path(files[index].filename or 'input').name)
        except Exception as exc:
            raise ValueError(f"Could not parse {choice['role']}: {exc}") from exc
        source = hashlib.sha256(content).hexdigest()[:16] + '.' + doc['format']
        doc['source'] = source
        inputs[source] = content
        documents.append(doc)
    a, b = documents
    if a['source'] == b['source'] and max(a['start'], b['start']) <= min(a['end'], b['end']):
        raise ValueError('Protocol and SAP page ranges must not overlap in a combined file.')
    if engine not in ('ai', 'rules'):
        raise ValueError('Unknown registry engine.')
    if engine == 'rules' and any(not any(p['words'] for p in d['pages']) for d in documents):
        raise ValueError('A selected document has no extractable text. OCR is required before registry generation.')
    with LOCK:
        project = store.create(name.strip(), documents, inputs, version_note.strip())
        if engine == 'rules':
            build_registry(project)
            project['engine'] = 'rules-v1; explicit baseline'
            return store.save(project, 'Generated explicit rule baseline; no model calls or semantic linking')
        project['engine'] = 'pending-ai'
        return store.save(project, 'Ready for explicit AI generation; import made no model requests')


@app.get('/api/projects/{pid}')
def project(pid: str):
    with LOCK:
        return load(pid)


@app.put('/api/projects/{pid}/concepts/{cid}')
def edit_concept(pid: str, cid: str, edit: ConceptEdit):
    with LOCK:
        p = load(pid)
        guard(p, edit.revision)
        if edit.category not in CATEGORIES or any(not a.strip() or len(a) > 200 for a in edit.aliases):
            raise ValueError('Invalid category or alias.')
        concept = next((c for c in p['concepts'] if c['id'] == cid), None)
        if not concept:
            raise ValueError('Unknown concept.')
        # Old standard name remains searchable after a metadata-only name correction.
        aliases = list(dict.fromkeys(a.strip() for a in edit.aliases))
        if edit.name.strip().casefold() != concept['name'].casefold() and concept['name'] not in aliases:
            aliases.append(concept['name'])
        concept.update(name=edit.name.strip(), category=edit.category, aliases=aliases,
                       confirmed=edit.confirmed, note=edit.note)
        rescan(p)
        return store.save(p, f"Corrected registry concept {cid}; document text unchanged")


@app.post('/api/projects/{pid}/concepts')
def add_concept(pid: str, edit: ConceptEdit):
    with LOCK:
        p = load(pid)
        guard(p, edit.revision)
        if edit.category not in CATEGORIES or not edit.name.strip() or any(not a.strip() or len(a) > 200 for a in edit.aliases):
            raise ValueError('Invalid concept or alias.')
        p['concepts'].append({'id': uid(), 'name': edit.name.strip(), 'category': edit.category,
                              'aliases': edit.aliases, 'confirmed': edit.confirmed, 'note': edit.note, 'evidence': 'Added by reviewer.'})
        rescan(p)
        return store.save(p, 'Added reviewer concept and indexed exact forms throughout selected documents')


@app.put('/api/projects/{pid}/mentions/{mid}')
def edit_mention(pid: str, mid: str, edit: MentionEdit):
    with LOCK:
        p = load(pid)
        guard(p, edit.revision)
        if edit.status not in ('confirmed', 'unresolved', 'preserve') or edit.concept_id not in {c['id'] for c in p['concepts']}:
            raise ValueError('Invalid concept association or review status.')
        mention = next((m for m in p['mentions'] if m['id'] == mid), None)
        if not mention:
            raise ValueError('Unknown occurrence.')
        mention.update(concept_id=edit.concept_id, status=edit.status, manual=True)
        if edit.concept_id not in mention['candidates']:
            mention['candidates'].append(edit.concept_id)
        return store.save(p, f'Corrected occurrence association {mid}; document text unchanged')


@app.post('/api/projects/{pid}/plans')
def make_plan(pid: str, request: PlanRequest):
    with LOCK:
        p = load(pid)
        guard(p, request.revision)
    if request.mode == 'ai':
        client = new_client(pid)
        plan = review_plan(p, request.concept_id, request.mappings, client)
        p.setdefault('ai_runs', []).append({'id': uid(), 'stage': 'rename_review', 'status': 'completed',
                                          'configuration': client.settings.provenance(), 'calls': client.records})
    elif request.mode == 'rules':
        plan = preview(p, request.concept_id, request.mappings)
        plan['engine'] = 'rules-v1; explicit baseline'
    else:
        raise ValueError('Unknown review mode.')
    with LOCK:
        guard(load(pid), request.revision)
        p['plans'].append(plan)
        # A preview is valid at the revision that contains it; persist once atomically.
        plan['base_revision'] = p['revision'] + 1
        return store.save(p, 'Created replacement preview with update, preserve and unresolved evidence')


def verify_patch_delta(before, after, plan, approved):
    from collections import defaultdict
    changes = defaultdict(list)
    for item in plan['items']:
        if item['id'] in approved:
            changes[item['block_id']].append(item)
    new_blocks = {b['id']: b['text'] for d in after['documents'] for b in d['blocks']}
    for doc in before['documents']:
        for block in doc['blocks']:
            text, cursor, pieces = block['text'], 0, []
            for item in sorted(changes[block['id']], key=lambda i: i['start']):
                pieces.extend((text[cursor:item['start']], item['new']))
                cursor = item['end']
            pieces.append(text[cursor:])
            expected = ''.join(pieces)
            if new_blocks[block['id']] != expected or re.findall(r'\d+', text) != re.findall(r'\d+', expected):
                raise ValueError('Unexpected difference or numerical change detected; nothing committed.')


@app.post('/api/projects/{pid}/plans/{plan_id}/apply')
def apply(pid: str, plan_id: str, request: ApplyRequest):
    with LOCK:
        p = load(pid)
        guard(p, request.revision)
        if not request.coverage_acknowledged:
            raise ValueError('Acknowledge coverage and reconstruction limits before export.')
        plan = next((r for r in p['plans'] if r['id'] == plan_id), None)
        if not plan:
            raise ValueError('Unknown preview.')
        before = store.clone(p)
        log = patch_blocks(p, plan, request.approved_ids)
        verify_patch_delta(before, p, plan, set(request.approved_ids))
        reindex_after_edits(p, plan, set(request.approved_ids))
        result = export_pair(p, store.folder(pid), log, uid())
        changed = {i['block_id'] for i in log}
        result['before_blocks'] = {b['id']: b['text'] for d in before['documents'] for b in d['blocks'] if b['id'] in changed}
        result['after_blocks'] = {b['id']: b['text'] for d in p['documents'] for b in d['blocks'] if b['id'] in changed}
        result['verification']['approved_delta_match'] = True
        report_path = store.folder(pid) / 'exports' / result['id'] / 'verification.json'
        report_path.write_text(json.dumps(result['verification'], indent=2, ensure_ascii=False), encoding='utf-8')
        p['exports'].append(result)
        return store.save(p, f"Applied {len(log)} individually approved changes; verified both Word outputs")


@app.get('/api/projects/{pid}/exports/{export_id}/{filename}')
def download_export(pid: str, export_id: str, filename: str):
    p = load(pid)
    result = next((r for r in p['exports'] if r['id'] == export_id), None)
    if not result or filename not in result['files']:
        raise HTTPException(404, 'Export not found.')
    return FileResponse(store.folder(pid) / 'exports' / export_id / filename, filename=filename)


@app.get('/api/projects/{pid}/documents/{doc_id}/source')
def source(pid: str, doc_id: str):
    p = load(pid)
    doc = next((d for d in p['documents'] if d['id'] == doc_id), None)
    if not doc:
        raise ValueError('Unknown document.')
    media = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' if doc.get('format') == 'docx' else 'application/pdf'
    return FileResponse(store.folder(pid) / 'inputs' / doc['source'], media_type=media, filename=doc['name'])


@app.get('/api/projects/{pid}/bundle')
def bundle(pid: str):
    with LOCK:
        load(pid)
        return Response(store.bundle(pid), media_type='application/zip', headers={'Content-Disposition': f'attachment; filename="project-{pid}.zip"'})


@app.post('/api/bundles')
async def import_bundle(file: UploadFile = File(...)):
    content = await read_upload(file, 200 * 1024 * 1024)
    try:
        with LOCK:
            return store.import_bundle(content)
    except (zipfile.BadZipFile, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError('Invalid project archive.') from exc


@app.post('/api/projects/{pid}/restore')
def restore(pid: str, request: RestoreRequest):
    with LOCK:
        guard(load(pid), request.revision)
        return store.restore(pid, request.snapshot)


@app.get('/api/projects/{pid}/registry.json')
def registry_download(pid: str):
    p = load(pid)
    return Response(json.dumps({'concepts': p['concepts'], 'mentions': p['mentions']}, indent=2, ensure_ascii=False),
                    media_type='application/json', headers={'Content-Disposition': 'attachment; filename="registry.json"'})


dist = ROOT / 'frontend' / 'dist'
if dist.exists():
    app.mount('/', StaticFiles(directory=dist, html=True), name='frontend')
