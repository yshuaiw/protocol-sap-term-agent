import base64
import hashlib
import io
import json

import httpx
from pypdf import PdfReader, PdfWriter

from backend.ai.client import ModelClient
from backend.ai.config import Settings
from backend.ai.vision import enrich_visual_text
from backend.store import Store


def test_native_pdf_keeps_original_bytes_and_selected_page_locations(tmp_path):
    writer = PdfWriter()
    for _ in range(3):
        writer.add_blank_page(width=100, height=100)
    buf = io.BytesIO()
    writer.write(buf)
    raw = buf.getvalue()
    inputs = tmp_path / 'inputs'
    inputs.mkdir()
    (inputs / 'original.pdf').write_bytes(raw)
    requests = []
    def reply(request):
        body = json.loads(request.content)
        parts = body['contents'][0]['parts']
        payload = json.loads(parts[0]['text'])
        assert payload['target_pdf_page'] == 2
        submitted = base64.b64decode(parts[1]['inlineData']['data'])
        assert submitted == raw and len(PdfReader(io.BytesIO(submitted)).pages) == 3
        requests.append(request)
        return httpx.Response(200, json={'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{'text': json.dumps({
            'segments': [{'text': 'Arm A scan', 'region': 'image_text'}], 'limitations': ['Page attribution requires source review.']})}]}}]})
    client = ModelClient(Settings(api_key='text-private-key', vision_api_key='vision-private-key',
                                 vision_provider='google', vision_model='test-model', pdf_mode='native'),
                         transport=httpx.MockTransport(reply))
    project = {'documents': [{'id': 'doc', 'format': 'pdf', 'role': 'SAP', 'source': 'original.pdf', 'blocks': [],
                             'pages': [{'page': 2, 'words': 0, 'images': 1}]}]}
    run = {}
    enrich_visual_text(project, tmp_path, client, run)
    block = project['documents'][0]['blocks'][0]
    assert block['page'] == 2 and block['visual_source'] == '2' and block['evidence_kind'] == 'visual_transcription'
    assert run['coverage_gaps'] and len(requests) == 1
    assert (inputs / 'original.pdf').read_bytes() == raw


def test_bundle_excludes_machine_credentials_and_transient_cache(tmp_path):
    store = Store(tmp_path / 'projects')
    raw = b'fixture-source'
    filename = hashlib.sha256(raw).hexdigest()[:16] + '.pdf'
    project = store.create('Privacy test', [{'role': r, 'source': filename, 'sha256': hashlib.sha256(raw).hexdigest()}
                                           for r in ('Protocol', 'SAP')], {filename: raw}, 'Synthetic sources')
    folder = store.folder(project['id'])
    (folder / 'ai-cache').mkdir()
    (folder / 'ai-cache' / 'private.json').write_text('private-cache-value')
    (folder / '.env.providers.json').write_text('private-credential-value')
    bundle = store.bundle(project['id'])
    import zipfile
    with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
        assert not any('.env' in name or 'ai-cache' in name for name in archive.namelist())
        assert all(b'private-credential-value' not in archive.read(name) and b'private-cache-value' not in archive.read(name)
                   for name in archive.namelist())
