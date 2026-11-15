import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient
from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.utils import ImageReader
from PIL import Image

from backend import main
from backend.store import Store


def make_pdf(role='Protocol', scanned=False):
    out = io.BytesIO()
    c = Canvas(out, pagesize=(612, 792))
    if scanned:
        c.drawImage(ImageReader(Image.new('RGB', (100, 100), 'white')), 20, 20)
    else:
        c.drawString(40, 760, f'{role} Version 1.0')
        c.drawString(40, 710, '1 STUDY DESIGN')
        c.drawString(40, 680, 'Arm A receives 10 mg; Arm B receives 20 mg.')
        c.drawString(40, 650, 'Full analysis set (FAS) includes all randomized patients.')
        c.drawString(40, 620, 'Primary endpoint: overall survival. Visit 1 at Day 1.')
        c.drawString(40, 590, 'Historical Arm A designation is preserved.')
        c.drawString(40, 560, 'FAS is a document-defined label.')
        c.drawString(40, 530, 'The arm after randomization and arm should not be labels.')
        for x in (40, 250, 550):
            c.line(x, 400, x, 500)
        for y in (400, 450, 500):
            c.line(40, y, 550, y)
        c.drawString(50, 470, 'Arm A')
        c.drawString(260, 470, '10 mg')
        c.drawString(50, 420, 'Visit 1')
        c.drawString(260, 420, 'Day 1')
        c.drawString(40, 100, 'a Arm A footnote context.')
        c.drawString(40, 30, 'Arm A footer - Page 1')
    c.showPage()
    c.save()
    return out.getvalue()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, 'store', Store(tmp_path / 'projects'))
    return TestClient(main.app)


def create(client, name='Test project'):
    result = client.post('/api/projects', data={'name': name, 'version_note': 'Both Version 1.0 checked on title pages.',
        'selections': json.dumps([{'role': r, 'file_index': i, 'start': 1, 'end': 1} for i, r in enumerate(('Protocol', 'SAP'))])},
        files=[('files', (f'{role}.pdf', make_pdf(role), 'application/pdf')) for role in ('Protocol', 'SAP')])
    assert result.status_code == 200, result.text
    return result.json()


def confirm(client, p, name='Arm A', aliases=None):
    concept = next(c for c in p['concepts'] if c['name'] == name)
    response = client.put(f"/api/projects/{p['id']}/concepts/{concept['id']}", json={
        'revision': p['revision'], 'name': name, 'aliases': aliases or [], 'category': concept['category'], 'confirmed': True})
    assert response.status_code == 200, response.text
    return response.json(), concept['id']


def plan(client, p, cid, mappings=None):
    response = client.post(f"/api/projects/{p['id']}/plans", json={'revision': p['revision'], 'concept_id': cid,
                                                                'mappings': mappings or {'Arm A': 'Investigational Arm A'}})
    assert response.status_code == 200, response.text
    return response.json()


def test_import_scans_all_regions_and_persists(client):
    p = create(client)
    assert len(p['documents']) == 2
    for d in p['documents']:
        assert {b['region'] for b in d['blocks']} >= {'header', 'body', 'table', 'footer', 'footnote_candidate', 'heading'}
        assert all(x['words'] == x['represented_words'] for x in d['pages'])
    fresh = Store(main.store.root).load(p['id'])
    assert fresh == p
    main.store.validate_sources(fresh)


def test_registry_changes_do_not_change_documents(client):
    p = create(client)
    before = p['documents']
    p, _ = confirm(client, p)
    assert p['documents'] == before
    assert any(m['status'] == 'confirmed' for m in p['mentions'])
    assert not any(c['name'].lower() in ('arm after', 'arm should') for c in p['concepts'])


def test_unconfirmed_and_numeric_changes_cannot_be_applied(client):
    p = create(client)
    cid = next(c['id'] for c in p['concepts'] if c['name'] == 'Arm A')
    p = plan(client, p, cid)
    assert all(i['proposal'] == 'unresolved' for i in p['plans'][-1]['items'])
    p, cid = confirm(client, p, 'Visit 1')
    p = plan(client, p, cid, {'Visit 1': 'Visit 2'})
    assert not any(i['proposal'] == 'update' for i in p['plans'][-1]['items'])


def test_approved_subset_exports_exact_differences_and_roundtrips(client):
    p = create(client)
    p, cid = confirm(client, p)
    p = plan(client, p, cid)
    preview = p['plans'][-1]
    assert any(i['proposal'] == 'preserve' for i in preview['items'])
    updates = [i for i in preview['items'] if i['proposal'] == 'update']
    chosen = [updates[0]['id'], next(i['id'] for i in updates if i['role'] == 'SAP')]
    r = client.post(f"/api/projects/{p['id']}/plans/{preview['id']}/apply", json={
        'revision': p['revision'], 'approved_ids': chosen, 'coverage_acknowledged': True})
    assert r.status_code == 200, r.text
    revised = r.json()
    assert sum(m['text'] == 'Investigational Arm A' for m in revised['mentions']) == 2
    report = revised['exports'][-1]['verification']
    assert report['verified'] and report['approved_delta_match']
    assert all(d['source_pages_retained'] == 1 and d['source_page_image_hashes_match'] for d in report['documents'])
    assert len(report['approved_changes']) == 2
    before = {b['id']: b['text'] for d in p['documents'] for b in d['blocks']}
    after = {b['id']: b['text'] for d in revised['documents'] for b in d['blocks']}
    assert sum(before[k] != v for k, v in after.items()) == 2
    for role in ('Protocol', 'SAP'):
        response = client.get(f"/api/projects/{p['id']}/exports/{revised['exports'][-1]['id']}/{role}_revised.docx")
        assert response.status_code == 200
        assert zipfile.is_zipfile(io.BytesIO(response.content))
    data = client.get(f"/api/projects/{p['id']}/bundle").content
    imported = client.post('/api/bundles', files={'file': ('project.zip', data)}).json()
    assert imported['id'] != p['id']
    assert imported['documents'] == revised['documents']
    assert imported['exports'] == revised['exports']
    restored = client.post(f"/api/projects/{imported['id']}/restore", json={
        'revision': imported['revision'], 'snapshot': p['revision']}).json()
    assert restored['documents'] == p['documents']
    assert restored['revision'] > imported['revision']


def test_stale_plan_is_rejected(client):
    p = create(client)
    p, cid = confirm(client, p)
    p = plan(client, p, cid)
    old = p['plans'][-1]
    p, _ = confirm(client, p)
    r = client.post(f"/api/projects/{p['id']}/plans/{old['id']}/apply", json={
        'revision': p['revision'], 'approved_ids': [old['items'][0]['id']], 'coverage_acknowledged': True})
    assert r.status_code == 400 and 'Stale' in r.text


def test_repeating_completed_rename_has_no_additional_updates(client):
    p = create(client)
    p, cid = confirm(client, p)
    p = plan(client, p, cid)
    pv = p['plans'][-1]
    p = client.post(f"/api/projects/{p['id']}/plans/{pv['id']}/apply", json={
        'revision': p['revision'], 'approved_ids': [i['id'] for i in pv['items'] if i['proposal'] == 'update'],
        'coverage_acknowledged': True}).json()
    p = plan(client, p, cid)
    assert not any(i['proposal'] == 'update' for i in p['plans'][-1]['items'])


def test_collision_requires_occurrence_review(client):
    p = create(client)
    p, cid = confirm(client, p, 'Full analysis set', ['FAS'])
    r = client.post(f"/api/projects/{p['id']}/concepts", json={'revision': p['revision'],
        'name': 'FAS', 'category': 'label', 'confirmed': True})
    p = r.json()
    collisions = [m for m in p['mentions'] if m['text'] == 'FAS']
    assert collisions and all(m['status'] == 'unresolved' and len(m['candidates']) == 2 for m in collisions)
    m = collisions[0]
    r = client.put(f"/api/projects/{p['id']}/mentions/{m['id']}", json={
        'revision': p['revision'], 'concept_id': cid, 'status': 'confirmed'})
    assert r.status_code == 200
    assert next(x for x in r.json()['mentions'] if x['id'] == m['id'])['manual']


def test_unresolved_rejected_and_no_change_on_error(client):
    p = create(client)
    cid = next(c['id'] for c in p['concepts'] if c['name'] == 'Arm A')
    p = plan(client, p, cid)
    before = client.get(f"/api/projects/{p['id']}").json()
    r = client.post(f"/api/projects/{p['id']}/plans/{p['plans'][-1]['id']}/apply", json={
        'revision': p['revision'], 'approved_ids': [p['plans'][-1]['items'][0]['id']], 'coverage_acknowledged': True})
    assert r.status_code == 400
    assert client.get(f"/api/projects/{p['id']}").json() == before


def test_reviewer_preserve_decision_survives_preview(client):
    p = create(client)
    p, cid = confirm(client, p)
    m = next(m for m in p['mentions'] if m['concept_id'] == cid)
    p = client.put(f"/api/projects/{p['id']}/mentions/{m['id']}", json={
        'revision': p['revision'], 'concept_id': cid, 'status': 'preserve'}).json()
    p = plan(client, p, cid)
    item = next(i for i in p['plans'][-1]['items'] if i['id'] == m['id'])
    assert item['proposal'] == 'preserve' and 'Reviewer' in item['reason']
    pv = p['plans'][-1]
    response = client.post(f"/api/projects/{p['id']}/plans/{pv['id']}/apply", json={
        'revision': p['revision'], 'approved_ids': [i['id'] for i in pv['items'] if i['proposal'] == 'update'],
        'coverage_acknowledged': True})
    assert response.status_code == 200
    assert next(x for x in response.json()['mentions'] if x['id'] == m['id'])['status'] == 'preserve'


def test_combined_ranges_and_scan_rejection(client):
    from pypdf import PdfReader, PdfWriter
    writer = PdfWriter()
    for role in ('Protocol', 'SAP'):
        writer.add_page(PdfReader(io.BytesIO(make_pdf(role))).pages[0])
    buf = io.BytesIO()
    writer.write(buf)
    selection = [{'role': r, 'file_index': 0, 'start': i + 1, 'end': i + 1} for i, r in enumerate(('Protocol', 'SAP'))]
    r = client.post('/api/projects', data={'name': 'Combined', 'version_note': 'Reviewed standalone covers.', 'selections': json.dumps(selection)},
                    files={'files': ('combined.pdf', buf.getvalue())})
    assert r.status_code == 200
    selection[1]['start'] = 1
    r = client.post('/api/projects', data={'name': 'Combined', 'version_note': 'Review', 'selections': json.dumps(selection)},
                    files={'files': ('combined.pdf', buf.getvalue())})
    assert r.status_code == 400 and 'overlap' in r.text
    r = client.post('/api/projects', data={'name': 'Scanned', 'version_note': 'Review', 'selections': json.dumps([
        {'role': r, 'file_index': i, 'start': 1, 'end': 1} for i, r in enumerate(('Protocol', 'SAP'))])},
        files=[('files', ('scan.pdf', make_pdf(scanned=True))), ('files', ('sap.pdf', make_pdf('SAP')))])
    assert r.status_code == 400 and 'OCR' in r.text


def test_archive_path_traversal_rejected(client):
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w') as archive:
        archive.writestr('../escape.txt', 'bad')
    r = client.post('/api/bundles', files={'file': ('bad.zip', data.getvalue())})
    assert r.status_code == 400 and 'Unsafe' in r.text


def test_invalid_bundle_does_not_leave_a_broken_project(client):
    p = create(client)
    original = main.store.bundle(p['id'])
    data = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(original)) as source, zipfile.ZipFile(data, 'w') as target:
        for item in source.infolist():
            raw = source.read(item)
            if item.filename == 'project.json':
                state = json.loads(raw)
                del state['name']
                raw = json.dumps(state).encode()
            target.writestr(item.filename, raw)
    before = client.get('/api/projects').json()
    r = client.post('/api/bundles', files={'file': ('invalid.zip', data.getvalue())})
    assert r.status_code == 400
    assert client.get('/api/projects').json() == before


def test_concurrent_edit_guard_and_tampered_source(client):
    p = create(client)
    current, _ = confirm(client, p)
    cid = p['concepts'][0]['id']
    r = client.put(f"/api/projects/{p['id']}/concepts/{cid}", json={'revision': p['revision'], 'name': 'Arm A', 'category': 'treatment'})
    assert r.status_code == 400 and 'another tab' in r.text
    source = main.store.folder(p['id']) / 'inputs' / current['documents'][0]['source']
    source.write_bytes(b'tampered')
    r = client.get(f"/api/projects/{p['id']}")
    assert r.status_code == 400 and 'hash mismatch' in r.text
