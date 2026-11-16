"""All-page structure excerpts with program-owned exact source coordinates."""
import re
from collections import Counter

from pypdf import PdfReader

CLUES = re.compile(r'statistical\s+analysis\s+plan|clinical\s+(?:study\s+|trial\s+)?protocol|'
                   r'study\s+protocol|trial\s+protocol|statistical\s+(?:methods|considerations|analysis)|'
                   r'data\s+analysis.{0,3}statistical|table\s+of\s+contents', re.I)


def line_key(line):
    return re.sub(r'\d+', '#', ' '.join(line.lower().split()))


def add_source(inventory, page, start, end, label, kind='native_text'):
    text = page['text'][start:end]
    if not text.strip():
        return None
    existing = next((s for s in page['sources'] if s['start'] == start and s['end'] == end), None)
    if existing:
        return existing
    source = {'id': f"P{page['page']}:{label}", 'page': page['page'], 'start': start, 'end': end,
              'text': text, 'evidence_kind': kind}
    page['sources'].append(source)
    inventory['sources'][source['id']] = source
    return source


def make_inventory(texts, fmt='pdf'):
    inventory = {'format': fmt, 'unit_count': len(texts), 'pages': [], 'sources': {}, 'limitations': []}
    common = Counter(key for text in texts for key in set(line_key(line) for line in text.splitlines()) if key)
    for number, text in enumerate(texts, 1):
        page = {'page': number, 'text': text, 'characters': len(text), 'sources': [], 'native_readable': bool(text.strip())}
        inventory['pages'].append(page)
        add_source(inventory, page, 0, min(len(text), 1100 if number <= 3 else 180), 'head')
        offset = 0
        for line in text.splitlines(keepends=True):
            if re.search(r'[A-Za-z\u4e00-\u9fff]', line) and common[line_key(line)] <= max(2, len(texts) // 4):
                if offset:
                    add_source(inventory, page, offset, min(len(text), offset + 230), 'body')
                break
            offset += len(line)
        # These are retrieval clues, never local role/range decisions. Keep quotations intact.
        for index, match in enumerate(list(CLUES.finditer(text))[:3]):
            add_source(inventory, page, max(0, match.start() - 110), min(len(text), match.end() + 310), f'clue{index}')
        if len(text) > 1100:
            add_source(inventory, page, max(0, len(text) - 100), len(text), 'tail')
    return inventory


def pdf_inventory(reader: PdfReader):
    return make_inventory([page.extract_text() or '' for page in reader.pages])


def public_inventory(inventory):
    unreadable = [p['page'] for p in inventory['pages'] if not p['native_readable']]
    hints = [s for p in inventory['pages'] for s in p['sources']
             if p['page'] <= 3 or ':clue' in s['id']]
    return {'pages': inventory['unit_count'],
            'boundary_hints': [{'page': s['page'], 'evidence': s['text'], 'source_id': s['id']} for s in hints],
            'boundary_coverage': {'pages_indexed': inventory['unit_count'],
                                  'native_readable_pages': inventory['unit_count'] - len(unreadable),
                                  'unreadable_pages': unreadable},
            'notice': 'Every page is indexed using structure excerpts. Model suggestions and all document versions require source review.'}
