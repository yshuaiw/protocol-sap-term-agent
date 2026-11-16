import hashlib
import os
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend import main
from backend.ai.schemas import Extraction
from backend.project_lifecycle import ProjectMissing
from backend.store import Store
from tests.test_ai_offline import fake_client, import_pair


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(main, 'store', Store(tmp_path / 'projects'))
    return TestClient(main.app)


def snapshot(folder):
    return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in folder.rglob('*') if p.is_file()}


def fill_project(project):
    project['concepts'] = [{'id': 'example', 'name': 'Arm A', 'aliases': ['Treatment A']}]
    project['mentions'] = [{'id': 'mention', 'concept_id': 'example'}]
    project['plans'] = [{'id': 'plan', 'approval': 'fixture'}]
    project['ai_runs'] = [{'id': 'run', 'status': 'completed'}]
    project['exports'] = [{'id': 'export', 'files': ['Protocol_revised.docx']}]
    project = main.store.save(project, 'Synthetic populated registry and approvals')
    folder = main.store.folder(project['id'])
    for name in ('ai-cache/fixture.json', 'exports/export/Protocol_revised.docx', 'exports/export/verification.json'):
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('fixture-project-data')
    return project


def test_delete_removes_all_internal_data_and_keeps_independent_copies(app, tmp_path):
    project = fill_project(import_pair(app))
    # Same name and source hashes still identify two independent projects.
    neighbor = import_pair(app)
    before = snapshot(main.store.folder(neighbor['id']))
    external = tmp_path / 'downloaded-project.zip'
    external.write_bytes(b'external-download')
    settings = tmp_path / '.env.providers.json'
    settings.write_text('private-machine-settings')
    external_source = tmp_path / 'original.docx'
    external_source.write_bytes(b'external-original')
    summary = app.get(f"/api/projects/{project['id']}/deletion").json()
    assert summary['id'] == project['id'] and summary['concepts'] == 1 and summary['occurrences'] == 1
    assert len(summary['documents']) == 2 and summary['snapshots'] >= 3
    response = app.request('DELETE', f"/api/projects/{project['id']}", json={'revision': summary['revision'], 'confirmed': True})
    assert response.status_code == 200 and response.json()['deleted'] is True
    assert not main.store.folder(project['id']).exists()
    assert snapshot(main.store.folder(neighbor['id'])) == before
    assert external.read_bytes() == b'external-download' and settings.read_text() == 'private-machine-settings'
    assert external_source.read_bytes() == b'external-original'
    assert [p['id'] for p in app.get('/api/projects').json()] == [neighbor['id']]
    assert app.get(f"/api/projects/{project['id']}").status_code == 404
    assert app.post(f"/api/projects/{project['id']}/restore", json={'revision': project['revision'], 'snapshot': 1}).status_code == 404
    with pytest.raises(ProjectMissing):
        main.store.save(project, 'Stale save after deletion')
    assert not main.store.folder(project['id']).exists()


def test_delete_requires_confirmation_fresh_revision_and_local_origin(app):
    project = import_pair(app)
    route = f"/api/projects/{project['id']}"
    before = snapshot(main.store.folder(project['id']))
    for payload in ({'revision': project['revision']}, {'revision': project['revision'], 'confirmed': False}):
        assert app.request('DELETE', route, json=payload).status_code == 422
    assert app.request('DELETE', route, json={'revision': project['revision'] - 1, 'confirmed': True}).status_code == 409
    assert app.request('DELETE', route, json={'revision': project['revision'], 'confirmed': True}, headers={'origin': 'https://other.example'}).status_code == 403
    assert snapshot(main.store.folder(project['id'])) == before


def test_missing_sources_do_not_prevent_deleting_project(app):
    project = import_pair(app)
    for path in (main.store.folder(project['id']) / 'inputs').iterdir():
        path.unlink()
    assert app.get(f"/api/projects/{project['id']}/deletion").status_code == 200
    assert app.request('DELETE', f"/api/projects/{project['id']}", json={'revision': project['revision'], 'confirmed': True}).status_code == 200


def test_partial_deletion_failure_keeps_retryable_manifest(app, monkeypatch):
    project = import_pair(app)
    folder = main.store.folder(project['id'])
    from backend import project_deletion
    real_remove = project_deletion.shutil.rmtree
    monkeypatch.setattr(project_deletion.shutil, 'rmtree', lambda path: (_ for _ in ()).throw(PermissionError('Fixture locked file')))
    response = app.request('DELETE', f"/api/projects/{project['id']}", json={'revision': project['revision'], 'confirmed': True})
    assert response.status_code == 409 and 'did not finish' in response.json()['detail']
    assert (folder / 'project.json').exists()
    assert app.get(f"/api/projects/{project['id']}/deletion").status_code == 200
    monkeypatch.setattr(project_deletion.shutil, 'rmtree', real_remove)
    assert app.request('DELETE', f"/api/projects/{project['id']}", json={'revision': project['revision'], 'confirmed': True}).status_code == 200


def directory_link(link, outside):
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        if os.name != 'nt' or subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(outside)],
                                             capture_output=True).returncode != 0:
            pytest.skip('Directory links are unavailable on this configuration.')


def remove_directory_link(link):
    if link.is_junction():
        link.rmdir()  # Remove the junction itself, never recursively traverse its target.
    else:
        link.unlink()


def test_linked_project_cannot_delete_outside_store(app, tmp_path):
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'keep.txt').write_text('external file')
    pid = 'a' * 32
    link = main.store.root / pid
    directory_link(link, outside)
    try:
        response = app.request('DELETE', f'/api/projects/{pid}', json={'revision': 1, 'confirmed': True})
        assert response.status_code == 400 and (outside / 'keep.txt').read_text() == 'external file'
    finally:
        remove_directory_link(link)


def test_linked_descendant_refuses_deletion_before_removing_any_data(app, tmp_path):
    p = import_pair(app)
    folder = main.store.folder(p['id'])
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'keep.txt').write_text('external data')
    before = snapshot(folder)
    link = folder / 'linked-files'
    directory_link(link, outside)
    try:
        response = app.request('DELETE', f"/api/projects/{p['id']}", json={'revision': p['revision'], 'confirmed': True})
        assert response.status_code == 400
        assert (outside / 'keep.txt').read_text() == 'external data'
    finally:
        remove_directory_link(link)
    assert snapshot(folder) == before


def test_final_directory_failure_restores_manifest_for_retry(app, monkeypatch):
    p = import_pair(app)
    folder = main.store.folder(p['id'])
    original_rmdir = Path.rmdir
    def locked(path):
        if path == folder.resolve():
            raise PermissionError('Fixture directory handle')
        return original_rmdir(path)
    with monkeypatch.context() as patch:
        patch.setattr(Path, 'rmdir', locked)
        response = app.request('DELETE', f"/api/projects/{p['id']}", json={'revision': p['revision'], 'confirmed': True})
        assert response.status_code == 409
        assert main.store.load(p['id']) == p
    assert app.request('DELETE', f"/api/projects/{p['id']}", json={'revision': p['revision'], 'confirmed': True}).status_code == 200


def test_accepted_cache_cannot_recreate_deleted_project(app):
    project = import_pair(app)
    client = fake_client(cache_dir=main.store.folder(project['id']) / 'ai-cache')
    client.complete('discovery', {'chunks': []}, Extraction)
    response = app.request('DELETE', f"/api/projects/{project['id']}", json={'revision': project['revision'], 'confirmed': True})
    assert response.status_code == 200
    with pytest.raises(ValueError, match='cache directory'):
        client.accept()
    assert not main.store.folder(project['id']).exists()
