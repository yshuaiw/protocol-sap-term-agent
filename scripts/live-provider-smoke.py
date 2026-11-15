"""Opt-in Groq-only synthetic PDF workflow. Never selects a paid alternative."""
import argparse
import hashlib
import io
import json
import sys
import uuid
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def pdf_fixture(role):
    from reportlab.pdfgen import canvas
    buffer = io.BytesIO()
    page = canvas.Canvas(buffer)
    for index, text in enumerate([role + ' synthetic terminology fixture.',
                                  'Arm A receives study treatment.', 'Arm B receives placebo.',
                                  'Visit 1 occurs on Day 1.']):
        page.drawString(72, 760 - index * 25, text)
    page.save()
    return buffer.getvalue()


def execute():
    from fastapi.testclient import TestClient
    from backend import main
    from backend.ai import routes
    from backend.ai.client import ModelClient
    from backend.ai.config import Settings
    from backend.store import Store
    settings = Settings.load()
    if settings.offline or settings.provider != 'groq' or not settings.api_key:
        raise ValueError('Live smoke requires offline=false, Groq text selection and a local Groq key. No alternative provider is called.')
    settings.pdf_mode = 'text'
    settings.max_calls = 12
    settings.chunk_chars = 4000
    tag = uuid.uuid4().hex[:12]
    out = ROOT / 'output' / ('live-provider-' + tag)
    out.mkdir(parents=True)
    main.store = Store(ROOT / 'tmp' / ('live-provider-' + tag) / 'projects')
    clients = []
    def new_client(pid=None):
        client = ModelClient(settings, cache_dir=main.store.folder(pid) / 'ai-cache' if pid else None)
        clients.append(client)
        return client
    main.new_client = routes.new_client = new_client
    api = TestClient(main.app)
    summary = {'provider': 'groq', 'model': settings.model, 'synthetic_documents': True,
               'scripted_reviewer': True, 'simulation': False, 'configuration': settings.provenance(),
               'whole_sample_workflow_passed': False, 'vision_tested': False, 'output_directory': str(out)}
    project = None
    def request(method, path, **kwargs):
        response = api.request(method, '/api' + path, **kwargs)
        if response.status_code != 200:
            detail = response.json().get('detail', 'Request failed')
            raise ValueError(detail if isinstance(detail, str) else 'Request failed validation; contents withheld.')
        return response.json()
    try:
        roles = ('Protocol', 'SAP')
        sources = {role: pdf_fixture(role) for role in roles}
        project = request('POST', '/projects', data={'name': 'Real Groq synthetic PDF smoke ' + tag,
            'version_note': 'Synthetic independent one-page PDFs; not clinical data. Approval actions are scripted test actions.',
            'selections': json.dumps([{'role': r, 'file_index': i, 'start': 1, 'end': 1} for i, r in enumerate(roles)])},
            files=[('files', (role + '.pdf', raw, 'application/pdf')) for role, raw in sources.items()])
        path = '/projects/' + project['id']
        project = request('POST', path + '/ai/generate', json={'revision': project['revision'], 'pdf_mode': 'text'})
        summary.update(registry_passed=True, concepts=len(project['concepts']), occurrences=len(project['mentions']))
        targets = [m for m in project['mentions'] if m['text'] == 'Arm A']
        if {m['role'] for m in targets} != set(roles) or len({m['concept_id'] for m in targets}) != 1:
            raise ValueError('Real model did not unambiguously group Arm A across both documents. No scripted correction was applied.')
        cid = targets[0]['concept_id']
        concept = next(c for c in project['concepts'] if c['id'] == cid)
        if any(m.get('model_link_status') == 'ambiguous' for m in targets):
            raise ValueError('Real model association is ambiguous. No automatic approval was attempted.')
        for mention in targets:
            project = request('PUT', path + '/mentions/' + mention['id'], json={
                'revision': project['revision'], 'concept_id': cid, 'status': 'confirmed'})
        project = request('POST', path + '/plans', json={'revision': project['revision'], 'concept_id': cid,
                          'mode': 'ai', 'mappings': {'Arm A': 'Investigational Arm A'}})
        plan = project['plans'][-1]
        approved = [i['id'] for i in plan['items'] if i['proposal'] == 'update' and i['text'] == 'Arm A']
        if set(approved) != {m['id'] for m in targets}:
            raise ValueError('Real AI review did not approve both synthetic naming changes. No model decision was overridden.')
        summary['rename_review_passed'] = True
        project = request('POST', path + '/plans/' + plan['id'] + '/apply', json={
            'revision': project['revision'], 'approved_ids': approved, 'coverage_acknowledged': True})
        exported = project['exports'][-1]
        verification = exported['verification']
        assert verification['verified'] and verification['approved_delta_match']
        assert len(verification['approved_changes']) == len(targets)
        for doc in project['documents']:
            original = (main.store.folder(project['id']) / 'inputs' / doc['source']).read_bytes()
            assert original == sources[doc['role']] and hashlib.sha256(original).hexdigest() == doc['sha256']
        for filename in exported['files']:
            response = api.get('/api' + path + '/exports/' + exported['id'] + '/' + filename)
            assert response.status_code == 200
            (out / filename).write_bytes(response.content)
        bundle = api.get('/api' + path + '/bundle').content
        with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
            assert all(settings.api_key.encode() not in archive.read(name) for name in archive.namelist())
        (out / 'project.zip').write_bytes(bundle)
        summary.update(whole_sample_workflow_passed=True, approved_changes=len(approved),
                       original_hashes_unchanged=True, exported_files=exported['files'], bundle_key_scan_passed=True)
    except Exception as error:
        # Only local application errors may be copied, never raw HTTP/validation tracebacks.
        from backend.ai.client import ModelError
        summary['error'] = str(error) if isinstance(error, (ModelError, ValueError)) else type(error).__name__
        if settings.api_key in summary['error']:
            summary['error'] = 'Credential material withheld.'
    finally:
        summary['calls'] = [record for client in clients for record in client.records]
        summary['reported_tokens'] = sum(c['usage'].get('total_tokens', 0) for c in summary['calls'])
        summary['http_attempts_on_accepted_operations'] = sum(c.get('request_attempts', 0) for c in summary['calls'])
        summary['limits'] = 'Synthetic native-text sample with scripted reviewer actions; no clinical quality, full recall, complex-region, vision or cross-provider resume certification.'
        (out / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
        print(json.dumps(summary, indent=2))
    return 0 if summary['whole_sample_workflow_passed'] else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    args = parser.parse_args()
    if not args.live:
        print('DRY RUN: no model calls. --live uses configured Groq text model only, new synthetic PDFs and an isolated store. No account/billing changes.')
    else:
        raise SystemExit(execute())
