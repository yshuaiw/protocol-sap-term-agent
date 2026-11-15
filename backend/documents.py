"""PDF text inventory. No page regions are cropped out of extraction."""
import hashlib
import io
import re

import pdfplumber
from pypdf import PdfReader


def inspect_pdf(content: bytes) -> dict:
    reader = PdfReader(io.BytesIO(content))
    if reader.is_encrypted:
        raise ValueError('Encrypted PDFs are not supported; provide an unlocked copy.')
    hints = []
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ''
        head = text[:1600]
        if re.search(r'statistical\s+analysis\s+plan|clinical\s+study\s+protocol', head, re.I):
            hints.append({'page': i + 1, 'evidence': head[:700]})
    return {'pages': len(reader.pages), 'boundary_hints': hints,
            'notice': 'Hints are not confirmed document boundaries. Review title pages, versions and ranges.'}


def parse_pdf(content: bytes, role: str, start: int, end: int, name: str) -> dict:
    digest = hashlib.sha256(content).hexdigest()
    doc_id = hashlib.sha256(f'{digest}:{role}:{start}:{end}'.encode()).hexdigest()[:16]
    blocks, pages, warnings = [], [], []
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        if not 1 <= start <= end <= len(pdf.pages):
            raise ValueError('Page range is outside the PDF.')
        for number in range(start, end + 1):
            page = pdf.pages[number - 1]
            words = page.extract_words(x_tolerance=2, y_tolerance=3)
            tables = page.find_tables()
            table_boxes = [t.bbox for t in tables]
            def inside(word, box):
                return box[0] <= (word['x0'] + word['x1']) / 2 <= box[2] and box[1] <= (word['top'] + word['bottom']) / 2 <= box[3]
            assigned = set()
            page_blocks = []
            for ti, table in enumerate(tables):
                cells = []
                for ri, row in enumerate(table.rows):
                    for ci, box in enumerate(row.cells):
                        if box is None:
                            continue
                        indices = [wi for wi, w in enumerate(words) if wi not in assigned and inside(w, box)]
                        assigned.update(indices)
                        selected = [words[wi] for wi in indices]
                        # Use the same word stream for coverage and patch offsets.
                        text = ' '.join(w['text'] for w in selected)
                        cells.append({'row': ri, 'col': ci, 'bbox': list(box), 'text': text})
                for cell in cells:
                    if cell['text']:
                        page_blocks.append({'region': 'table', 'table': ti, **cell})
            lines = []
            for wi, word in enumerate(words):
                if wi in assigned:
                    continue
                if not lines or abs(lines[-1][0]['top'] - word['top']) > 3:
                    lines.append([])
                lines[-1].append(word)
            for line in lines:
                line.sort(key=lambda w: w['x0'])
                box = [min(w['x0'] for w in line), min(w['top'] for w in line), max(w['x1'] for w in line), max(w['bottom'] for w in line)]
                text = ' '.join(w['text'] for w in line)
                region = 'header' if box[1] < page.height * .07 else 'footer' if box[3] > page.height * .94 else 'body'
                if region == 'body' and re.match(r'^\d+(?:\.\d+)*\.?\s+[A-Z]', text):
                    region = 'heading'
                if region == 'body' and box[1] > page.height * .75 and re.match(r'^[a-z*†‡]\s', text):
                    region = 'footnote_candidate'
                page_blocks.append({'region': region, 'bbox': box, 'text': text})
            page_blocks.sort(key=lambda b: (b['bbox'][1], b['bbox'][0]))
            for bi, block in enumerate(page_blocks):
                block.update(id=f'{doc_id}:p{number}:b{bi}', page=number, original_text=block['text'])
                blocks.append(block)
            represented = sum(len(b['text'].split()) for b in page_blocks)
            issues = []
            if not words:
                issues.append('No extractable text; blank, scanned or image-only page. OCR required for text editing.')
            if page.images:
                issues.append(f'{len(page.images)} image(s); text inside images is not editable or indexed.')
            if any('(cid:' in w['text'] or '\ufffd' in w['text'] for w in words):
                issues.append('Unmapped glyphs detected; inspect source before editing.')
            if represented != len(words):
                issues.append(f'Word accounting mismatch: {len(words)} extracted vs {represented} represented.')
            for issue in issues:
                warnings.append(f'Page {number}: {issue}')
            pages.append({'page': number, 'width': page.width, 'height': page.height,
                          'words': len(words), 'represented_words': represented,
                          'tables': len(table_boxes), 'images': len(page.images), 'issues': issues})
    return {'id': doc_id, 'role': role, 'name': name, 'sha256': digest,
            'start': start, 'end': end, 'blocks': blocks, 'pages': pages, 'warnings': warnings,
            'coverage_notice': 'All selected pages and text regions scanned. Region labels are heuristic. Complex merged tables, reading order, superscripts and footnote semantics need visual review. No OCR; no complete terminology recall claim.'}
