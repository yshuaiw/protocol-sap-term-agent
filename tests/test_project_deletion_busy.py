import threading
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.concurrency import run_in_threadpool

from backend import main
from backend.ai import routes
from backend.store import Store
from tests.test_ai_offline import ScriptedGroq, fake_client, import_pair


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(main, 'store', Store(tmp_path / 'projects'))
    monkeypatch.setattr(main, 'new_client', lambda pid=None: fake_client())
    monkeypatch.setattr(routes, 'new_client', lambda pid=None: fake_client())
    return TestClient(main.app)


def prepared(app, with_plan=False, with_export=False):
    p = import_pair(app)
    path = f"/api/projects/{p['id']}"
    p = app.post(path + '/ai/generate', json={'revision': p['revision']}).json()
    c = p['concepts'][0]
    p = app.put(path + '/concepts/' + c['id'], json={'revision': p['revision'], 'name': c['name'],
                'category': c['category'], 'aliases': c['aliases'], 'confirmed': True}).json()
    if with_plan or with_export:
        p = app.post(path + '/plans', json={'revision': p['revision'], 'concept_id': c['id'], 'mode': 'rules',
                                          'mappings': {'Arm A': 'Investigational Arm A'}}).json()
    if with_export:
        plan = p['plans'][-1]
        p = app.post(path + '/plans/' + plan['id'] + '/apply', json={'revision': p['revision'],
            'approved_ids': [i['id'] for i in plan['items'] if i['proposal'] == 'update'], 'coverage_acknowledged': True}).json()
    assert 'id' in p, p
    return p


@pytest.mark.parametrize('operation', ['generate', 'interpret', 'audit', 'review', 'export', 'failed_generate'])
def test_active_operation_refuses_deletion_from_another_request(app, monkeypatch, operation):
    p = prepared(app, with_plan=operation == 'export', with_export=operation == 'audit')
    path = f"/api/projects/{p['id']}"
    entered, release = threading.Event(), threading.Event()
    script = ScriptedGroq()
    def blocked(request):
        entered.set()
        assert release.wait(10), 'Test operation was not released'
        if operation == 'failed_generate':
            raise httpx.ReadTimeout('Fixture network failure', request=request)
        return script(request)
    monkeypatch.setattr(main, 'new_client', lambda pid=None: fake_client(blocked))
    monkeypatch.setattr(routes, 'new_client', lambda pid=None: fake_client(blocked))
    if operation == 'export':
        real_export = main.export_pair
        def export(*args):
            entered.set()
            assert release.wait(10), 'Test export was not released'
            return real_export(*args)
        monkeypatch.setattr(main, 'export_pair', export)
        route, body = '/plans/' + p['plans'][-1]['id'] + '/apply', {
            'approved_ids': [i['id'] for i in p['plans'][-1]['items'] if i['proposal'] == 'update'], 'coverage_acknowledged': True}
    elif operation == 'audit':
        route, body = '/ai/audit', {'export_id': p['exports'][-1]['id']}
    elif operation == 'interpret':
        route, body = '/ai/interpret', {'text': 'Rename Arm A to Investigational Arm A.'}
    elif operation == 'review':
        route, body = '/plans', {'concept_id': p['concepts'][0]['id'], 'mode': 'ai', 'mappings': {'Arm A': 'Investigational Arm A'}}
    else:
        route, body = '/ai/generate', {'replace_registry': True}
    with ThreadPoolExecutor(max_workers=2) as pool:
        task = pool.submit(app.post, path + route, json={'revision': p['revision'], **body})
        try:
            assert entered.wait(5), 'Operation did not reach its blocking point'
            deletion = pool.submit(app.request, 'DELETE', path, json={'revision': p['revision'], 'confirmed': True})
            response = deletion.result(timeout=2)
            assert response.status_code == 409 and 'active operation' in response.json()['detail']
            assert main.store.folder(p['id']).exists()
        finally:
            release.set()
        assert task.result(timeout=10).status_code == (400 if operation == 'failed_generate' else 200)
    latest = app.get(path).json()
    assert app.request('DELETE', path, json={'revision': latest['revision'], 'confirmed': True}).status_code == 200
    assert not main.store.folder(p['id']).exists()


def test_source_response_stays_busy_until_response_body_finishes(app):
    p = import_pair(app)
    path = f"/api/projects/{p['id']}"
    source_path = path + '/documents/' + p['documents'][0]['id'] + '/source'
    entered, release = threading.Event(), threading.Event()
    async def slow_response(scope, receive, send):
        async def delayed_send(message):
            if scope.get('path') == source_path and message['type'] == 'http.response.body':
                entered.set()
                assert await run_in_threadpool(release.wait, 10)
            await send(message)
        await main.app(scope, receive, delayed_send)
    downloading = TestClient(slow_response)
    with ThreadPoolExecutor() as pool:
        task = pool.submit(downloading.get, source_path)
        try:
            assert entered.wait(5)
            assert app.request('DELETE', path, json={'revision': p['revision'], 'confirmed': True}).status_code == 409
        finally:
            release.set()
        assert task.result(timeout=5).status_code == 200
    assert app.request('DELETE', path, json={'revision': p['revision'], 'confirmed': True}).status_code == 200


def test_duplicate_delete_and_late_requests_cannot_recreate_project(app, monkeypatch):
    p = import_pair(app)
    path = f"/api/projects/{p['id']}"
    entered, release = threading.Event(), threading.Event()
    from backend import project_deletion
    real_remove = project_deletion.shutil.rmtree
    def blocked_remove(folder):
        entered.set()
        assert release.wait(10)
        real_remove(folder)
    monkeypatch.setattr(project_deletion.shutil, 'rmtree', blocked_remove)
    with ThreadPoolExecutor() as pool:
        deletion = pool.submit(app.request, 'DELETE', path, json={'revision': p['revision'], 'confirmed': True})
        try:
            assert entered.wait(5)
            assert app.request('DELETE', path, json={'revision': p['revision'], 'confirmed': True}).status_code == 409
            assert app.post(path + '/ai/generate', json={'revision': p['revision'], 'replace_registry': True}).status_code == 409
        finally:
            release.set()
        assert deletion.result(timeout=5).status_code == 200
    assert app.post(path + '/ai/generate', json={'revision': p['revision']}).status_code == 404
    assert not main.store.folder(p['id']).exists()
