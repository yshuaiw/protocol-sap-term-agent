"""Offline cancellation tests use real persistence, concurrent HTTP and deliberately delayed transports."""
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from fastapi.testclient import TestClient

from backend import main
from backend.ai import routes
from backend.ai.request_limits import RequestLimiter
from backend.ai.schemas import Extraction
from backend.operations import CURRENT, OPERATIONS, Cancelled, Operation
from backend.store import Store
from tests.test_ai_offline import ScriptedGroq, fake_client, import_pair
from tests.test_project_deletion import snapshot


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(main, 'store', Store(tmp_path / 'projects'))
    with TestClient(main.app) as client:
        yield client
    assert not OPERATIONS.active()


@pytest.mark.parametrize('stop_at', ['linking', 'explanation_scan'])
def test_cancel_discards_partial_cache_register_history_and_late_response(app, monkeypatch, stop_at):
    project = import_pair(app)
    folder = main.store.folder(project['id'])
    (folder / 'ai-cache').mkdir()
    (folder / 'ai-cache' / 'existing.json').write_text('preserve existing cache')
    before = snapshot(folder)
    entered, release = threading.Event(), threading.Event()
    fixture, posted = ScriptedGroq(), []
    def delayed(request):
        payload = json.loads(json.loads(request.content)['messages'][1]['content'])
        stage = 'explanation_scan' if 'explanation_targets' in payload else 'linking' if 'ledger' in payload else 'discovery'
        posted.append(stage)
        if stage == stop_at:
            entered.set()
            assert release.wait(5)
        return fixture(request)
    monkeypatch.setattr(routes, 'new_client', lambda pid=None: fake_client(delayed, cache_dir=folder / 'ai-cache'))
    with ThreadPoolExecutor() as pool:
        future = pool.submit(app.post, f"/api/projects/{project['id']}/ai/generate", json={'revision': project['revision']})
        try:
            assert entered.wait(5)
            active = app.get('/api/operations').json()
            assert len(active) == 1 and active[0]['project_id'] == project['id']
            # A different/refreshed client can discover the operation without restarting it.
            assert app.get(f"/api/projects/{project['id']}").json()['revision'] == project['revision']
            assert snapshot(folder) == before
            assert app.post('/api/operations/cancel', json={'ids': [active[0]['id']]}).json()['accepted'][active[0]['id']]
            assert app.get('/api/operations').json()[0]['status'] == 'cancelling'
            release.set()
            response = future.result(5)
        finally:
            release.set()
        assert response.status_code == 200 and response.json()['cancelled']
        assert snapshot(folder) == before
        assert not app.get('/api/operations').json()
        assert app.post('/api/operations/cancel', json={'ids': [active[0]['id']]}).json()['accepted'][active[0]['id']] is False


def test_cancel_delete_waits_then_removes_and_never_resurrects(app, monkeypatch):
    project, neighbor = import_pair(app), import_pair(app)
    folder = main.store.folder(project['id'])
    untouched = snapshot(main.store.folder(neighbor['id']))
    entered, release = threading.Event(), threading.Event()
    fixture = ScriptedGroq()
    def delayed(request):
        entered.set()
        assert release.wait(5)
        return fixture(request)
    monkeypatch.setattr(routes, 'new_client', lambda pid=None: fake_client(delayed, cache_dir=folder / 'ai-cache'))
    with ThreadPoolExecutor() as pool:
        run = pool.submit(app.post, f"/api/projects/{project['id']}/ai/generate", json={'revision': project['revision']})
        try:
            assert entered.wait(5)
            preview = app.get(f"/api/projects/{project['id']}/deletion").json()
            assert preview['active_llm']
            deletion = pool.submit(app.post, f"/api/projects/{project['id']}/cancel-delete", json={'revision': preview['revision'], 'confirmed': True})
            deadline = time.monotonic() + 3
            while app.get('/api/operations').json()[0]['status'] != 'cancelling':
                assert time.monotonic() < deadline
                time.sleep(.01)
            assert not deletion.done() and folder.exists()
            assert app.post(f"/api/projects/{project['id']}/ai/generate", json={'revision': project['revision']}).status_code == 409
            release.set()
            assert run.result(5).json()['cancelled']
            assert deletion.result(5).json()['deleted']
        finally:
            release.set()
    assert not folder.exists()
    assert snapshot(main.store.folder(neighbor['id'])) == untouched
    assert app.get(f"/api/projects/{project['id']}").status_code == 404


def test_unrelated_activity_or_stale_confirmation_does_not_cancel(app):
    project = import_pair(app)
    op = OPERATIONS.start(project['id'], 'test')
    try:
        with main.store.activity.operation(project['id']):
            response = app.post(f"/api/projects/{project['id']}/cancel-delete", json={'revision': project['revision'], 'confirmed': True})
            assert response.status_code == 409 and not op.cancelled.is_set()
        response = app.post(f"/api/projects/{project['id']}/cancel-delete", json={'revision': project['revision'] - 1, 'confirmed': True})
        assert response.status_code == 409 and not op.cancelled.is_set()
        assert app.post('/api/operations/cancel', json={'ids':[op.id]}, headers={'origin':'https://other.invalid'}).status_code == 403
    finally:
        OPERATIONS.finish(op)


def test_cancel_interrupts_shared_rpm_wait_preserving_usage():
    limiter = RequestLimiter()
    limiter.acquire('groq', 'fixture', 1)
    op = Operation(None, 'test')
    entered = threading.Event()
    def waiting():
        token = CURRENT.set(op)
        try:
            entered.set()
            with pytest.raises(Cancelled):
                limiter.acquire('groq', 'fixture', 1)
        finally:
            CURRENT.reset(token)
    with ThreadPoolExecutor() as pool:
        task = pool.submit(waiting)
        assert entered.wait(2)
        op.cancel()
        task.result(2)
    assert len(limiter.buckets[('groq','fixture')]['events']) == 1


@pytest.mark.parametrize('status', [429, 503, 400])
def test_cancellation_prevents_retries_after_an_inflight_response(status):
    op = Operation(None, 'test')
    calls = []
    def transport(request):
        calls.append(request)
        op.cancel()
        return httpx.Response(status, json={'error':{'code':'json_validate_failed'}}, headers={'retry-after':'1'})
    token = CURRENT.set(op)
    try:
        with pytest.raises(Cancelled):
            fake_client(transport).complete('discovery', {}, Extraction)
    finally:
        CURRENT.reset(token)
    assert len(calls) == 1


def test_cancel_and_commit_have_one_ordering_point(tmp_path):
    store = Store(tmp_path / 'store')
    project = store.create('fixture', [], {}, '')
    before = snapshot(store.folder(project['id']))
    op = Operation(project['id'], 'test')
    token = CURRENT.set(op)
    try:
        op.cancel()
        with pytest.raises(Cancelled):
            store.save(project, 'must not persist')
        assert snapshot(store.folder(project['id'])) == before
    finally:
        CURRENT.reset(token)

    op = Operation(project['id'], 'test')
    token = CURRENT.set(op)
    try:
        saved = store.save(project, 'success won before cancellation')
        assert op.cancel() is False
        assert store.load(project['id'])['revision'] == saved['revision']
    finally:
        CURRENT.reset(token)


@pytest.mark.parametrize('action', ['interpret', 'explanations', 'plans', 'audit'])
def test_all_project_llm_actions_can_cancel_without_saving(app, monkeypatch, action):
    monkeypatch.setattr(routes, 'new_client', lambda pid=None: fake_client())
    p = import_pair(app)
    p = app.post(f"/api/projects/{p['id']}/ai/generate", json={'revision': p['revision']}).json()
    bid = p['documents'][0]['blocks'][0]['id']
    text = p['documents'][0]['blocks'][0]['text']
    p['exports'] = [{'id':'export-fixture', 'verification':{'approved_changes':[{'block_id':bid}]},
                     'after_blocks':{bid:text}, 'before_blocks':{bid:text}}]
    p = main.store.save(p, 'Synthetic export audit fixture')
    before = snapshot(main.store.folder(p['id']))
    entered, release = threading.Event(), threading.Event()
    fixture = ScriptedGroq()
    def delayed(request):
        entered.set()
        assert release.wait(5)
        return fixture(request)
    new = lambda pid=None: fake_client(delayed, cache_dir=main.store.folder(pid) / 'ai-cache')
    monkeypatch.setattr(routes, 'new_client', new)
    monkeypatch.setattr(main, 'new_client', new)
    payload = {'revision':p['revision']}
    suffix = '/ai/' + action
    if action == 'interpret': payload['text'] = 'Rename Arm A.'
    if action == 'audit': payload['export_id'] = 'export-fixture'
    if action == 'plans':
        suffix = '/plans'
        payload.update(concept_id=p['concepts'][0]['id'], mode='ai', mappings={'Arm A':'Investigational Arm A'})
    with ThreadPoolExecutor() as pool:
        future = pool.submit(app.post, f"/api/projects/{p['id']}"+suffix, json=payload)
        try:
            assert entered.wait(5)
            ops = app.get('/api/operations').json()
            app.post('/api/operations/cancel', json={'ids':[ops[0]['id']]})
            release.set()
            assert future.result(5).json()['cancelled']
        finally:
            release.set()
    assert snapshot(main.store.folder(p['id'])) == before


def test_llm_origin_denial_is_403_and_creates_no_operation(app):
    p = import_pair(app)
    response = app.post(f"/api/projects/{p['id']}/ai/generate", json={'revision':p['revision']}, headers={'origin':'https://other.invalid'})
    assert response.status_code == 403 and not OPERATIONS.active()


def test_preimport_boundary_suggestions_are_cancellable(app, monkeypatch):
    from tests.test_boundaries import combined_pdf, BoundaryTransport
    entered, release = threading.Event(), threading.Event()
    scripted = BoundaryTransport()
    def delayed(request):
        entered.set()
        assert release.wait(5)
        return scripted(request)
    monkeypatch.setattr(routes, 'new_client', lambda pid=None: fake_client(delayed))
    with ThreadPoolExecutor() as pool:
        future = pool.submit(app.post, '/api/inspect/ai', files={'file':('combined.pdf',combined_pdf(),'application/pdf')})
        try:
            assert entered.wait(5)
            ops = app.get('/api/operations').json()
            assert len(ops)==1 and ops[0]['project_id'] is None
            app.post('/api/operations/cancel',json={'ids':[ops[0]['id']]})
            release.set()
            assert future.result(5).json()['cancelled']
        finally:
            release.set()
    assert not main.store.list() and not OPERATIONS.active()


def test_cancel_during_final_write_reports_success_won(tmp_path):
    store = Store(tmp_path/'projects')
    p = store.create('fixture',[],{},'')
    op = Operation(p['id'],'fixture')
    entered, release = threading.Event(), threading.Event()
    def save():
        token = CURRENT.set(op)
        try:
            def persist():
                entered.set()
                assert release.wait(5)
                return store._save(p,'Final write won')
            return op.commit(persist)
        finally:
            CURRENT.reset(token)
    with ThreadPoolExecutor() as pool:
        saving = pool.submit(save)
        try:
            assert entered.wait(5)
            cancelling = pool.submit(op.cancel)
            assert not cancelling.done()
            release.set()
            assert saving.result(5)['revision']==2
            assert cancelling.result(5) is False
        finally:
            release.set()
    assert store.load(p['id'])['revision']==2
