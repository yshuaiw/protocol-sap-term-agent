import hashlib
import io
import json
import zipfile

import httpx
import pytest
from docx import Document
from lxml import etree
from fastapi.testclient import TestClient

from backend import main
from backend.ai import routes
from backend.ai.client import GroqClient, ModelError
from backend.ai.config import Settings
from backend.ai.schemas import Extraction
from backend.ai.workflow import generate_registry
from backend.ai.vision import enrich_visual_text
from backend.docx_input import NS, P, paragraph_text, parse_docx, read_package, xml
from backend.docx_export import export_docx
from backend.store import Store


def word_file(role='Protocol'):
    d = Document()
    p = d.add_paragraph()
    p.add_run('Arm ').bold = True
    p.add_run('A receives 10 mg in ' + role + '.').italic = True
    d.add_table(rows=1, cols=1).cell(0, 0).text = 'Arm A table'
    d.sections[0].header.paragraphs[0].text = 'Arm A header'
    d.sections[0].footer.paragraphs[0].text = 'Arm A footer'
    out = io.BytesIO()
    d.save(out)
    package = read_package(out.getvalue())
    package['word/footnotes.xml'] = b'<w:footnotes xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:footnote w:id="-1" w:type="separator"><w:p><w:r><w:separator/></w:r></w:p></w:footnote><w:footnote w:id="0" w:type="continuationSeparator"><w:p><w:r><w:continuationSeparator/></w:r></w:p></w:footnote><w:footnote w:id="1"><w:p><w:r><w:t>Arm A footnote</w:t></w:r></w:p></w:footnote></w:footnotes>'
    tree = xml(package['word/document.xml'])
    run = etree.SubElement(next(tree.iter(P)), '{' + NS['w'] + '}r')
    reference = etree.SubElement(run, '{' + NS['w'] + '}footnoteReference')
    reference.set('{' + NS['w'] + '}id', '1')
    package['word/document.xml'] = etree.tostring(tree)
    rels = xml(package['word/_rels/document.xml.rels'])
    relation = etree.SubElement(rels, '{http://schemas.openxmlformats.org/package/2006/relationships}Relationship')
    relation.attrib.update({'Id': 'rIdFixtureFootnotes', 'Type': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/footnotes', 'Target': 'footnotes.xml'})
    package['word/_rels/document.xml.rels'] = etree.tostring(rels)
    types = xml(package['[Content_Types].xml'])
    override = etree.SubElement(types, '{http://schemas.openxmlformats.org/package/2006/content-types}Override')
    override.attrib.update({'PartName': '/word/footnotes.xml', 'ContentType': 'application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml'})
    package['[Content_Types].xml'] = etree.tostring(types)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as z:
        for name, raw in package.items():
            z.writestr(name, raw)
    return buffer.getvalue()


class ScriptedGroq:
    """Transport fixture, not a claim that a real model produces these answers."""
    def __init__(self, invalid=False, omit_link=False):
        self.calls = []
        self.invalid = invalid
        self.omit_link = omit_link

    def __call__(self, request):
        assert str(request.url) == 'https://api.groq.com/openai/v1/chat/completions'
        body = json.loads(request.content)
        self.calls.append(body)
        data = body['messages'][1]['content']
        if isinstance(data, list):
            payload = json.loads(data[0]['text'])
            answer = {'segments': [], 'limitations': []}
        else:
            payload = json.loads(data)
            if payload.get('phase') in ('scan', 'review'):
                from tests.test_boundaries import BoundaryTransport
                return BoundaryTransport()(request)
            if 'chunks' in payload:
                mentions = []
                for block in payload['chunks']:
                    pos = block['text'].find('Arm A')
                    if pos >= 0:
                        mentions.append({'block_id': block['block_id'],
                            'context_quote': block['text'][max(0, pos - 20):pos + 25],
                            'term_text': 'invented' if self.invalid else 'Arm A', 'canonical_name': 'Arm A',
                            'category': 'treatment', 'definition': 'Named treatment group', 'reason': 'Exact anchored label.'})
                answer = {'mentions': mentions}
            elif 'ledger' in payload:
                group = payload['ledger'][0]['id'] if payload['ledger'] else 'new:arm-a'
                answer = {'assignments': [{'candidate_id': c['id'], 'group_id': group, 'canonical_name': 'Arm A',
                    'category': 'treatment', 'definition': 'Named treatment group', 'reason': 'Fixture association.',
                    'ambiguous': False} for c in payload['candidates']]}
                if self.omit_link:
                    answer['assignments'] = []
            elif 'mentions' in payload:
                answer = {'decisions': [{'mention_id': m['id'], 'decision': 'update', 'reason': 'Fixture naming-only advice.',
                    'evidence': m['text'], 'semantic_risk': False} for m in payload['mentions']]}
            elif 'request' in payload:
                answer = {'concept_id': payload['concepts'][0]['id'], 'mappings': [{'old': 'Arm A', 'new': 'Investigational Arm A'}],
                          'reason': 'Fixture request interpretation.', 'semantic_risk': False}
            elif 'changes' in payload:
                answer = {'findings': [], 'note': 'Fixture audit; not a quality result.'}
            else:
                answer = {'documents': [], 'compatibility_note': 'Needs human review.'}
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(answer)}}],
                                      'usage': {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15}})


def fake_client(script=None, **kwargs):
    return GroqClient(Settings(api_key='offline-fixture-key', pdf_mode='text'), transport=httpx.MockTransport(script or ScriptedGroq()), **kwargs)


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(main, 'store', Store(tmp_path / 'projects'))
    monkeypatch.setattr(main, 'new_client', lambda pid=None: fake_client())
    monkeypatch.setattr(routes, 'new_client', lambda pid=None: fake_client())
    return TestClient(main.app)


def import_pair(app):
    files = [('files', (r + '.docx', word_file(r))) for r in ('Protocol', 'SAP')]
    data = {'name': 'Offline AI contract', 'version_note': 'Synthetic independent DOCX pair.',
            'selections': json.dumps([{'role': r, 'file_index': i, 'start': 1, 'end': 1} for i, r in enumerate(('Protocol', 'SAP'))])}
    response = app.post('/api/projects', data=data, files=files)
    assert response.status_code == 200, response.text
    return response.json()


def test_config_reads_local_key_without_exposing_it(tmp_path, monkeypatch):
    monkeypatch.delenv('GROQ_API_KEY', raising=False)
    (tmp_path / 'API.txt').write_text('GROQ_API_KEY=fixture-private-key')
    s = Settings.load(tmp_path)
    assert s.api_key == 'fixture-private-key'
    assert 'fixture-private-key' not in repr(s) + json.dumps(s.public())


def test_offline_block_and_sanitized_provider_errors():
    with pytest.raises(ModelError, match='disabled'):
        GroqClient(Settings(api_key='secret', offline=True)).complete('discovery', {}, Extraction)
    transport = httpx.MockTransport(lambda request: httpx.Response(401, text='secret must never enter a log'))
    with pytest.raises(ModelError) as error:
        GroqClient(Settings(api_key='secret'), transport=transport).complete('discovery', {}, Extraction)
    assert 'HTTP 401' in str(error.value) and 'secret' not in str(error.value)


def test_docx_all_regions_and_export_new_file_only(tmp_path):
    original = word_file()
    source = tmp_path / 'original.docx'
    source.write_bytes(original)
    doc = parse_docx(original, 'Protocol', 1, 1, source.name)
    assert {b['region'] for b in doc['blocks']} >= {'body', 'table', 'header', 'footer', 'footnote'}
    for block in doc['blocks']:
        block['text'] = block['text'].replace('Arm A', 'Investigational Arm A')
    target = tmp_path / 'Protocol_revised.docx'
    result = export_docx(doc, original, target)
    assert result['exact_text_match'] and result['untouched_package_parts_match']
    assert hashlib.sha256(source.read_bytes()).digest() == hashlib.sha256(original).digest()
    parsed = parse_docx(target.read_bytes(), 'Protocol', 1, 1, target.name)
    assert all('Investigational Arm A' in b['text'] for b in parsed['blocks'])
    tree = xml(read_package(target.read_bytes())['word/document.xml'])
    assert tree.xpath('boolean(.//w:rPr/w:b)', namespaces=NS)
    assert tree.xpath('boolean(.//w:rPr/w:i)', namespaces=NS)


def test_ai_api_contract_roundtrip_without_external_calls(app):
    p = import_pair(app)
    assert p['engine'] == 'pending-ai' and not p['concepts']
    pid = p['id']
    sources = {d['source']: (main.store.folder(pid) / 'inputs' / d['source']).read_bytes() for d in p['documents']}
    response = app.post(f'/api/projects/{pid}/ai/generate', json={'revision': p['revision']})
    assert response.status_code == 200, response.text
    p = response.json()
    assert p['engine'] == 'groq-ai-v1'
    assert {r['stage'] for r in p['ai_runs'][-1]['calls']} == {'discovery', 'linking'}
    assert p['ai_runs'][-1]['chunks_completed'] == p['ai_runs'][-1]['chunks_total']
    assert len(p['mentions']) == 10 and len(p['concepts']) == 1
    cid = p['concepts'][0]['id']
    p = app.put(f'/api/projects/{pid}/concepts/{cid}', json={'revision': p['revision'], 'name': 'Arm A',
        'category': 'treatment', 'aliases': [], 'confirmed': True}).json()
    response = app.post(f'/api/projects/{pid}/plans', json={'revision': p['revision'], 'concept_id': cid,
        'mappings': {'Arm A': 'Investigational Arm A'}})
    assert response.status_code == 200, response.text
    p = response.json()
    plan = p['plans'][-1]
    assert plan['engine'] == 'groq-ai-v1' and all(i['model_reason'] for i in plan['items'])
    p = app.post(f'/api/projects/{pid}/plans/{plan["id"]}/apply', json={'revision': p['revision'],
        'approved_ids': [i['id'] for i in plan['items'] if i['proposal'] == 'update'], 'coverage_acknowledged': True}).json()
    assert p['exports'][-1]['verification']['verified']
    assert all((main.store.folder(pid) / 'inputs' / name).read_bytes() == data for name, data in sources.items())
    response = app.post(f'/api/projects/{pid}/ai/audit', json={'revision': p['revision'], 'export_id': p['exports'][-1]['id']})
    assert response.status_code == 200, response.text
    assert response.json()['semantic_audits'][-1]['findings'] == []
    packed = app.get(f'/api/projects/{pid}/bundle').content
    response = app.post('/api/bundles', files={'file': ('project.zip', packed)})
    assert response.status_code == 200, response.text
    assert 'offline-fixture-key' not in packed.decode('latin1')


@pytest.mark.parametrize('invalid,omit', [(True, False), (False, True)])
def test_invalid_model_evidence_never_replaces_register(app, monkeypatch, invalid, omit):
    monkeypatch.setattr(routes, 'new_client', lambda pid=None: fake_client(ScriptedGroq(invalid, omit)))
    p = import_pair(app)
    r = app.post(f'/api/projects/{p["id"]}/ai/generate', json={'revision': p['revision']})
    assert r.status_code == 400
    current = app.get(f'/api/projects/{p["id"]}').json()
    assert current['concepts'] == p['concepts'] and current['documents'] == p['documents']
    assert current['ai_runs'][-1]['status'] == 'failed'


def test_model_cannot_override_unconfirmed_permissions(app):
    p = import_pair(app)
    p = app.post(f'/api/projects/{p["id"]}/ai/generate', json={'revision': p['revision']}).json()
    response = app.post(f'/api/projects/{p["id"]}/plans', json={'revision': p['revision'],
        'concept_id': p['concepts'][0]['id'], 'mappings': {'Arm A': 'Investigational Arm A'}})
    assert response.status_code == 200
    assert all(i['proposal'] == 'unresolved' for i in response.json()['plans'][-1]['items'])


def test_natural_request_and_explicit_regeneration_guard(app):
    p = import_pair(app)
    p = app.post(f'/api/projects/{p["id"]}/ai/generate', json={'revision': p['revision']}).json()
    response = app.post(f'/api/projects/{p["id"]}/ai/interpret', json={'revision': p['revision'],
        'text': 'Rename Arm A to Investigational Arm A.'})
    assert response.status_code == 200, response.text
    p = response.json()
    assert p['last_interpretation']['mappings'][0]['new'] == 'Investigational Arm A'
    blocked = app.post(f'/api/projects/{p["id"]}/ai/generate', json={'revision': p['revision']})
    assert blocked.status_code == 400 and 'Confirm registry replacement' in blocked.text


def test_visual_route_visits_every_selected_page_without_network(tmp_path):
    from tests.test_workflow import make_pdf
    from backend.input_documents import parse_input
    script = ScriptedGroq()
    client = fake_client(script)
    client.settings.pdf_mode = 'vision'
    content = make_pdf()
    doc = parse_input(content, 'Protocol', 1, 1, 'one.pdf')
    doc['source'] = 'a' * 16 + '.pdf'
    (tmp_path / 'inputs').mkdir()
    (tmp_path / 'inputs' / doc['source']).write_bytes(content)
    run = {}
    enrich_visual_text({'documents': [doc]}, tmp_path, client, run)
    assert run['visual_units_completed'] == 1
    assert script.calls[0]['messages'][1]['content'][1]['type'] == 'image_url'
    assert script.calls[0]['model'] == client.settings.vision_model


def test_cache_requires_explicit_evidence_acceptance(tmp_path):
    script = ScriptedGroq()
    client = fake_client(script, cache_dir=tmp_path)
    payload = {'chunks': []}
    client.complete('discovery', payload, Extraction)
    assert not list(tmp_path.glob('*.json'))
    client.accept()
    assert len(list(tmp_path.glob('*.json'))) == 1
    client.complete('discovery', payload, Extraction)
    assert len(script.calls) == 1 and client.records[-1]['cached']


def test_mixed_pdf_docx_inspection_and_import_without_model_call(app):
    from tests.test_workflow import make_pdf
    for filename, data, expected in [('p.pdf', make_pdf(), 'pdf'), ('s.docx', word_file('SAP'), 'docx')]:
        response = app.post('/api/inspect', files={'file': (filename, data)})
        assert response.status_code == 200 and response.json()['format'] == expected
    response = app.post('/api/projects', data={'name': 'Mixed', 'version_note': 'Synthetic pair',
        'selections': json.dumps([{'role': r, 'file_index': i, 'start': 1, 'end': 1} for i, r in enumerate(('Protocol', 'SAP'))])},
        files=[('files', ('protocol.pdf', make_pdf())), ('files', ('sap.docx', word_file('SAP')))])
    assert response.status_code == 200
    assert {d['format'] for d in response.json()['documents']} == {'pdf', 'docx'}
    assert response.json()['ai_runs'] == []


def test_pdf_wrapped_term_uses_one_anchored_paragraph():
    from reportlab.pdfgen.canvas import Canvas
    from backend.input_documents import parse_input
    out = io.BytesIO()
    canvas = Canvas(out)
    canvas.drawString(40, 650, 'Arm')
    canvas.drawString(40, 636, 'A receives 10 mg.')
    canvas.save()
    doc = parse_input(out.getvalue(), 'Protocol', 1, 1, 'wrapped.pdf')
    assert any('Arm A receives 10 mg.' == b['text'] for b in doc['blocks'])
    assert doc['pages'][0]['words'] == doc['pages'][0]['represented_words']
