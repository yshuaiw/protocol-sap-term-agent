import io
import json

import httpx
import pytest
from PIL import Image, ImageDraw
from reportlab.pdfgen.canvas import Canvas

from backend.ai.boundaries import suggest_boundaries
from backend.ai.client import ModelClient, ModelError
from backend.ai.config import Settings
from backend.input_documents import inspect_input
from tests.test_boundaries import BoundaryTransport


def scanned_cover_pdf():
    out = io.BytesIO()
    c = Canvas(out)
    image = Image.new('RGB', (700, 300), 'white')
    ImageDraw.Draw(image).text((30, 60), 'STUDY PROTOCOL\nStudy ABC Version 1.0', fill='black')
    c.drawInlineImage(image, 40, 400, width=500, height=220)
    c.showPage()
    for line in ['Protocol body', 'STATISTICAL ANALYSIS PLAN', 'SAP body']:
        c.drawString(40, 720, line)
        c.showPage()
    c.save()
    return out.getvalue()


def visual_client(invalid=False):
    script = BoundaryTransport()
    calls = []
    def reply(request):
        body = json.loads(request.content)
        if request.url.host == 'api.anthropic.com':
            assert request.headers['x-api-key'] == 'visual-fixture-key'
            payload = json.loads(body['messages'][0]['content'][0]['text'])
            assert payload['target_pages'] == [1] and payload['image_order'] == [1]
            assert body['messages'][0]['content'][1]['type'] == 'image'
            calls.append('visual')
            pages = [{'page': 99 if invalid else 1, 'segments': [
                {'text': 'STUDY PROTOCOL\nStudy ABC Version 1.0', 'region': 'heading'}], 'limitations': []}]
            return httpx.Response(200, json={'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': json.dumps({'pages': pages})}]})
        return script(request)
    client = ModelClient(Settings(api_key='text-fixture-key', pdf_mode='vision', vision_provider='anthropic',
                                 vision_api_key='visual-fixture-key', vision_model='fixture-visual'), transport=httpx.MockTransport(reply))
    return client, calls


def test_visual_cover_is_separate_provider_and_never_native_evidence():
    raw = scanned_cover_pdf()
    inventory = inspect_input(raw, include_boundary_context=True)['_boundary_inventory']
    assert not inventory['pages'][0]['native_readable']
    client, calls = visual_client()
    result = suggest_boundaries(inventory, client, raw)
    protocol = next(d for d in result['documents'] if d['role'] == 'Protocol')
    assert calls == ['visual'] and result['coverage']['visual_pages_read'] == [1]
    assert protocol['start'] == 1 and protocol['end'] == 2 and protocol['requires_visual_review']
    assert protocol['evidence_kind'] == 'visual_transcription'
    assert all(c['simulation'] for c in client.records)
    assert {c['provider'] for c in client.records} == {'groq', 'anthropic'}


def test_wrong_visual_page_assignment_is_rejected():
    raw = scanned_cover_pdf()
    inventory = inspect_input(raw, include_boundary_context=True)['_boundary_inventory']
    client, _ = visual_client(invalid=True)
    with pytest.raises(ModelError, match='every requested source page'):
        suggest_boundaries(inventory, client, raw)


def test_text_only_route_reports_unreadable_cover_without_calling_vision():
    raw = scanned_cover_pdf()
    inventory = inspect_input(raw, include_boundary_context=True)['_boundary_inventory']
    script = BoundaryTransport()
    client = ModelClient(Settings(api_key='fixture-key', pdf_mode='text'), transport=httpx.MockTransport(script))
    result = suggest_boundaries(inventory, client, raw)
    assert result['coverage']['unreadable_pages'] == [1]
    assert not result['coverage']['visual_pages_read'] and result['limitations']
    assert not any(c['stage'] == 'boundary_vision' for c in client.records)
