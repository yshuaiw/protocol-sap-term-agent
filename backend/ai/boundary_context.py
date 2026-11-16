"""Bounded boundary context and optional visual evidence; no role/range heuristics."""
import io
import json

import pdfplumber

from ..boundary_inventory import add_source
from .boundary_schemas import BoundaryVisuals
from .client import ModelError
from .providers import PROVIDERS
from .vision import media_url

def budget(client):
    return min(14000, max(4000, client.settings.chunk_chars * 2))


def pack(records, base, key, limit, max_units=24):
    pending = []
    for record in records:
        if pending and (len(pending) >= max_units or
                        len(json.dumps({**base, key: [*pending, record]}, ensure_ascii=False)) > limit):
            yield {**base, key: pending}
            pending = []
        if len(json.dumps({**base, key: [record]}, ensure_ascii=False)) > limit:
            raise ModelError('A boundary context unit exceeds the batch budget. Increase the boundary context budget or review this source manually; no pages were silently dropped.')
        pending.append(record)
    if pending:
        yield {**base, key: pending}


def scan_payloads(inventory, client):
    records = [{'page': p['page'], 'characters': p['characters'],
                'native_readable': p['native_readable'], 'sources': list(p['sources'])} for p in inventory['pages']]
    base = {'phase': 'scan', 'unit_count': inventory['unit_count'], 'format': inventory['format']}
    yield from pack(records, base, 'pages', budget(client))


def supplement_unreadable(inventory, content, client):
    empty = [p for p in inventory['pages'] if not p['native_readable']]
    completed = []
    if inventory['format'] != 'pdf' or not empty:
        return completed
    if client.settings.pdf_mode == 'text' or not client.settings.visual_key():
        inventory['limitations'].append('Pages without native text were not visually read. Enable a configured visual provider or review those pages manually.')
        return completed
    native_pdf = client.settings.pdf_mode == 'native'
    if native_pdf and not PROVIDERS[client.settings.vision_provider]['native_pdf']:
        raise ModelError('The selected visual adapter does not support native PDF. Select an image route or a supported provider explicitly.')
    if native_pdf and len(content) > 15 * 1024 * 1024:
        raise ModelError('Original PDF exceeds the native-route 15 MiB limit. Choose page-image processing explicitly.')
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for offset in range(0, len(empty), 3):
            group = empty[offset:offset + 3]
            page_ids = [p['page'] for p in group]
            payload = {'phase': 'visual_structure', 'target_pages': page_ids,
                       'instruction': 'Read only these original PDF page numbers. Keep every requested page, including blank/unreadable pages. No role/range decisions.'}
            if native_pdf:
                response = client.complete('boundary_vision', payload, BoundaryVisuals,
                                pdf=media_url(content, 'application/pdf'))
            else:
                images = []
                for p in group:
                    buffer = io.BytesIO()
                    pdf.pages[p['page'] - 1].to_image(resolution=100).original.convert('RGB').save(buffer, format='PNG')
                    images.append(media_url(buffer.getvalue(), 'image/png'))
                payload['image_order'] = page_ids
                response = client.complete('boundary_vision', payload, BoundaryVisuals, images=images)
            rows = response['pages']
            if len(rows) != len(page_ids) or {r['page'] for r in rows} != set(page_ids):
                raise ModelError('Visual boundary reading must identify every requested source page exactly once.')
            for row in rows:
                page = next(p for p in group if p['page'] == row['page'])
                page['text'] = '\n'.join(s['text'] for s in row['segments'])
                page['characters'] = len(page['text'])
                for index, segment in enumerate(row['segments']):
                    start = sum(len(s['text']) + 1 for s in row['segments'][:index])
                    add_source(inventory, page, start, start + len(segment['text']), f'visual{index}', 'visual_transcription')
                completed.append(page['page'])
                inventory['limitations'].extend(f"PDF page {row['page']}: {lim}" for lim in row['limitations'])
            client.accept()
    inventory['limitations'].append('Visual text and its source-page attribution require checking against the original PDF; they are not native-text evidence.')
    return completed


def review_payloads(inventory, candidates, client):
    starts = [{'source_id': c['source_id'], 'page': inventory['sources'][c['source_id']]['page'],
               'role': c['role'], 'kind': c['kind'], 'reason': c['reason']} for c in candidates]
    records = []
    for candidate in candidates:
        source = inventory['sources'][candidate['source_id']]
        context = {source['id']: source}
        numbers = set(range(max(1, source['page'] - 1), min(inventory['unit_count'], source['page'] + 1) + 1))
        numbers.add(inventory['unit_count'])  # File-end evidence prevents losing the last continuation page.
        for number in sorted(numbers):
            page = inventory['pages'][number - 1]
            kind = 'native_text' if page['native_readable'] else 'visual_transcription'
            begin = max(0, source['start'] - 900) if number == source['page'] else 0
            expanded = add_source(inventory, page, begin, min(len(page['text']), begin + 2500), f'review{begin}', kind)
            if expanded:
                context[expanded['id']] = expanded
        records.append({'target': candidate, 'evidence': list(context.values())})
    base = {'phase': 'review', 'unit_count': inventory['unit_count'], 'format': inventory['format'],
            'all_starts': starts}
    for batch in pack(records, base, 'contexts', budget(client), max_units=6):
        batch['targets'] = [c['target'] for c in batch['contexts']]
        if len(json.dumps(batch, ensure_ascii=False)) > budget(client):
            # Targets duplicate a small amount of metadata; count that before submission too.
            if len(batch['contexts']) > 1:
                for entry in batch['contexts']:
                    single = {**base, 'contexts': [entry], 'targets': [entry['target']]}
                    if len(json.dumps(single, ensure_ascii=False)) > budget(client):
                        raise ModelError('Expanded boundary context exceeds the budget. Review this source manually; no context was silently dropped.')
                    yield single
                continue
            raise ModelError('Expanded boundary context exceeds the budget. Review this source manually; no context was silently dropped.')
        yield batch
