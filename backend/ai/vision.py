import base64
import hashlib
import io

import pdfplumber

from .client import ModelError
from .providers import PROVIDERS
from .schemas import VisionResult
from ..docx_input import read_package


def enrich_visual_text(project, folder, client, run):
    run['visual_units_completed'] = 0
    run['coverage_gaps'] = []
    if client.settings.pdf_mode == 'native' and not PROVIDERS[client.settings.vision_provider]['native_pdf']:
        raise ModelError('Selected visual provider does not support native PDF. Change API settings; no fallback was used.')
    for doc in project['documents']:
        # Regeneration always starts from native source text rather than stacking OCR duplicates.
        doc['blocks'] = [b for b in doc['blocks'] if b.get('evidence_kind') != 'visual_transcription']
        if doc.get('format', 'pdf') == 'pdf':
            if client.settings.pdf_mode == 'text':
                if any(p['images'] or not p['words'] for p in doc['pages']):
                    run['coverage_gaps'].append(f"{doc['role']}: text-only route does not interpret image text/blank or scanned pages.")
                continue
            source = folder / 'inputs' / doc['source']
            if client.settings.pdf_mode == 'native':
                # Original bytes, one selected page target at a time; never convert through Word.
                # Explicitly bounded: a large native request must be changed by the reviewer.
                if source.stat().st_size > 15 * 1024 * 1024:
                    raise ModelError('Original PDF exceeds the native-route 15 MiB limit. Select page-image mode explicitly.')
                raw = source.read_bytes()
                for page in doc['pages']:
                    native = '\n'.join(b['text'] for b in doc['blocks'] if b['page'] == page['page'])
                    add_segments(doc, str(page['page']), page['page'], raw, 'application/pdf', native, client, run, editable=True)
                continue
            with pdfplumber.open(source) as pdf:
                for page in doc['pages']:
                    picture = pdf.pages[page['page'] - 1].to_image(resolution=120).original
                    buffer = io.BytesIO()
                    picture.convert('RGB').save(buffer, format='PNG')
                    native = '\n'.join(b['text'] for b in doc['blocks'] if b['page'] == page['page'])
                    add_segments(doc, str(page['page']), page['page'], buffer.getvalue(), 'image/png', native, client, run, editable=True)
        else:
            package = read_package((folder / 'inputs' / doc['source']).read_bytes())
            for name, raw in package.items():
                if not name.startswith('word/media/'):
                    continue
                mime = 'image/png' if raw.startswith(b'\x89PNG') else 'image/jpeg' if raw.startswith(b'\xff\xd8') else None
                if client.settings.pdf_mode == 'text' or not mime:
                    run['coverage_gaps'].append(f"{doc['role']}: embedded {name} was retained but not visually interpreted.")
                    continue
                add_segments(doc, name, 1, raw, mime, '', client, run, editable=False)
            for warning in doc['warnings']:
                if 'Embedded charts/objects' in warning or 'Equations or alternate-content' in warning:
                    run['coverage_gaps'].append(f"{doc['role']}: {warning}")


def add_segments(doc, label, page, raw, mime, native, client, run, editable):
    url = 'data:' + mime + ';base64,' + base64.b64encode(raw).decode()
    payload = {'role': doc['role'], 'source_unit': label, 'native_text': native}
    if mime == 'application/pdf':
        payload.update(target_pdf_page=page, instruction='Transcribe ONLY this 1-based original PDF page. Ignore all other pages, including versions outside the selected range.')
        response = client.complete('vision', payload, VisionResult, pdf=url)
    else:
        response = client.complete('vision', payload, VisionResult, images=[url])
    client.accept()
    run['visual_units_completed'] += 1
    for limit in response['limitations']:
        run['coverage_gaps'].append(f"{doc['role']} {label}: {limit}")
    for i, segment in enumerate(response['segments']):
        if segment['text'] in native:
            continue
        bid = doc['id'] + ':visual:' + hashlib.sha256((label + ':' + str(i)).encode()).hexdigest()[:16]
        doc['blocks'].append({'id': bid, 'page': page, 'region': 'image_text', 'model_region': segment['region'],
                              'text': segment['text'], 'original_text': segment['text'], 'bbox': None,
                              'evidence_kind': 'visual_transcription', 'editable': editable,
                              'visual_source': label, 'notice': 'Model transcription; verify against original source.'})
