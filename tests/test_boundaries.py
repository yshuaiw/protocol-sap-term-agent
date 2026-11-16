import io
import json
import re

import httpx
import pytest
from reportlab.pdfgen.canvas import Canvas

from backend.ai.boundaries import suggest_boundaries
from backend.ai.client import ModelClient
from backend.ai.config import Settings
from backend.boundary_inventory import make_inventory
from backend.input_documents import inspect_input


def combined_pdf():
    out = io.BytesIO()
    c = Canvas(out)
    for lines in [('STUDY PROTOCOL', 'Study ABC, Protocol Version 1.0', 'Standalone document cover', 'Protocol page 1 of 3'),
                  ('Study ABC, Protocol Version 1.0', 'Protocol page 2 of 3 - continuation', '1. Trial design and methods'),
                  ('Study ABC, Protocol Version 1.0', 'Protocol page 3 of 3', '2. References - end of protocol'),
                  ('STATISTICAL ANALYSIS PLAN', 'Study ABC, SAP Version 1.0', 'Standalone document cover', 'SAP page 1 of 3'),
                  ('Study ABC, SAP Version 1.0', 'SAP page 2 of 3 - continuation', '1. Statistical methods'),
                  ('Study ABC, SAP Version 1.0', 'SAP page 3 of 3', '2. Analysis methods - end of SAP')]:
        for index, line in enumerate(lines):
            c.drawString(40, 720 - index * 24, line)
        c.showPage()
    c.save()
    return out.getvalue()


class BoundaryTransport:
    def __init__(self, mode='pair'):
        self.payloads = []
        self.mode = mode

    def __call__(self, request):
        body = json.loads(request.content)
        content = body['messages'][1]['content']
        payload = json.loads(content[0]['text'] if isinstance(content, list) else content)
        self.payloads.append(payload)
        if payload['phase'] == 'scan':
            candidates = []
            for page in payload['pages']:
                for s in page['sources']:
                    role = 'Protocol' if re.search(r'^\s*(?:STUDY\s+PROTOCOL|Protocol Version)', s['text'], re.I) else 'SAP' if re.search(r'^\s*(?:STATISTICAL\s+ANALYSIS\s+PLAN|SAP Version)', s['text'], re.I) else None
                    if role and not any(c['role'] == role and c['source_id'].startswith(f"P{page['page']}:") for c in candidates):
                        candidates.append({'source_id': s['id'], 'role': role,
                                           'kind': 'embedded_section' if role == 'SAP' and self.mode == 'section' else 'independent_document',
                                           'confidence': 'high', 'reason': 'Synthetic title fixture.'})
            if self.mode == 'empty':
                candidates = []
            answer = {'candidates': candidates, 'limitations': []}
        elif payload['phase'] == 'review':
            rows = []
            for target in payload['targets']:
                page = next(s['page'] for s in payload['all_starts'] if s['source_id'] == target['source_id'])
                following = [s['page'] for s in payload['all_starts'] if s['page'] > page and s['kind'] == 'independent_document']
                end = min(following) - 1 if following else payload['unit_count']
                rows.append({'candidate_id': target['source_id'], **target, 'end': end})
                if target['role'] == 'SAP':
                    if self.mode == 'unknown':
                        rows[-1]['source_id'] = 'invented-source'
                    if self.mode == 'outside':
                        rows[-1]['end'] = 99
                    if self.mode == 'overlap':
                        rows[0]['end'] = 6
            if self.mode == 'omitted':
                rows = rows[:-1]
            if self.mode == 'duplicated':
                rows.append(rows[-1])
            answer = {'documents': rows, 'compatibility_note': 'Synthetic result; versions require human review.'}
        else:
            raise AssertionError(payload)
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(answer)}}]})


def run(mode='pair', inventory=None, **settings):
    script = BoundaryTransport(mode)
    client = ModelClient(Settings(api_key='fixture-key', pdf_mode='text', **settings), transport=httpx.MockTransport(script))
    if inventory is None:
        inventory = inspect_input(combined_pdf(), include_boundary_context=True)['_boundary_inventory']
    return suggest_boundaries(inventory, client), script


def test_all_pages_indexed_even_without_old_title_phrases():
    inventory = make_inventory(['STUDY PROTOCOL\nABC', 'Body 2', 'Body 3',
                                'STATISTICAL\nANALYSIS PLAN\nABC', 'Body 5', 'Body 6'])
    result, script = run(inventory=inventory)
    scan_pages = [p['page'] for payload in script.payloads if payload['phase'] == 'scan' for p in payload['pages']]
    assert scan_pages == list(range(1, 7))
    assert result['coverage']['pages_indexed'] == 6


def test_pair_ranges_anchored_without_model_retyping_quotes():
    result, _ = run()
    assert result['status'] == 'proposed' and result['can_apply_pair']
    assert [(d['role'], d['start'], d['end']) for d in result['documents']] == [('Protocol', 1, 3), ('SAP', 4, 6)]
    assert all(d['evidence'] and d['evidence_kind'] == 'native_text' and d['source_id'] for d in result['documents'])


@pytest.mark.parametrize('mode', ['unknown', 'outside', 'overlap', 'omitted', 'duplicated'])
def test_invalid_boundary_never_becomes_an_applicable_pair(mode):
    result, _ = run(mode)
    assert not result['can_apply_pair'] and result['issues']
    assert result['status'] == 'needs_review'


def test_interior_statistics_section_is_visible_but_not_an_independent_sap():
    result, _ = run('section')
    sap = next(d for d in result['documents'] if d['role'] == 'SAP')
    assert sap['kind'] == 'embedded_section' and not sap['applicable']
    assert not result['can_apply_pair']


def test_empty_result_is_not_success_and_does_not_prove_absence():
    result, _ = run('empty')
    assert result['status'] == 'no_pair' and not result['can_apply_pair']
    assert not result['documents'] and result['compatibility_note']


def test_late_title_and_unicode_sources_preserve_exact_offsets():
    text = '🧪中文 ' + 'x ' * 950 + '\nSTATISTICAL ANALYSIS PLAN\nVersion 1\n'
    inventory = make_inventory([text])
    sources = inventory['pages'][0]['sources']
    assert any('STATISTICAL ANALYSIS PLAN' in s['text'] and s['start'] > 700 for s in sources)
    assert all(text[s['start']:s['end']] == s['text'] for s in sources)


def test_index_batches_count_serialized_metadata_and_keep_every_page():
    inventory = make_inventory([f'Page {i}: ' + 'body ' * 100 for i in range(80)])
    result, script = run('empty', inventory, chunk_chars=1500)
    payloads = [p for p in script.payloads if p['phase'] == 'scan']
    assert [p['page'] for b in payloads for p in b['pages']] == list(range(1, 81))
    assert all(len(p['pages']) <= 24 for p in payloads)
    assert all(len(json.dumps(p, ensure_ascii=False)) <= 4000 for p in payloads)
    assert result['coverage']['pages_indexed'] == 80


def test_multiple_document_versions_stay_separate_for_manual_selection():
    inventory = make_inventory(['Protocol Version 1', 'Methods', 'SAP Version 1', 'Analyses',
                                'Protocol Version 2', 'New methods', 'SAP Version 2', 'New analyses'])
    result, _ = run(inventory=inventory)
    assert [(d['role'], d['start'], d['end']) for d in result['documents']] == [
        ('Protocol', 1, 2), ('SAP', 3, 4), ('Protocol', 5, 6), ('SAP', 7, 8)]
    assert not result['can_apply_pair'] and result['status'] == 'needs_review'
