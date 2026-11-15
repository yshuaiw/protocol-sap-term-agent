"""Reconstructed editable text plus unchanged page facsimiles; never claim PDF layout fidelity."""
import io
import hashlib
import json
from pathlib import Path

import pdfplumber
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor


def export_pair(project, folder: Path, log: list, export_id: str):
    out = folder / 'exports' / export_id
    out.mkdir(parents=True, exist_ok=True)
    files, checks = [], []
    for source in project['documents']:
        doc = Document()
        section = doc.sections[0]
        section.header.paragraphs[0].text = f"{source['role']} | reconstructed working copy"
        section.footer.paragraphs[0].text = 'Source images in appendix are unchanged originals. See verification.json.'
        doc.styles['Normal'].font.size = Pt(10)
        doc.styles['Normal'].paragraph_format.space_after = Pt(2)
        doc.styles['Normal'].paragraph_format.line_spacing = 1.05
        for style_name in ('Title', 'Subtitle', 'Heading 1', 'Heading 2', 'Heading 3'):
            style = doc.styles[style_name]
            style.font.color.rgb = RGBColor(0, 0, 0)
            style.font.underline = False
            for border in style.element.xpath('.//w:pBdr'):
                border.getparent().remove(border)
        doc.add_heading(f"{source['role']} revised working copy", 0)
        doc.add_paragraph('Editable transcription of the selected PDF pages. Layout and region classification are reconstructed. '
                          'The appendix retains unchanged source page images, including image-only content; approved edits appear only in the transcription. '
                          'Review the coverage report before using this draft.')
        doc.add_paragraph(f"Source: {source['name']} | PDF pages {source['start']}-{source['end']} | SHA256 {source['sha256']}")
        expected = []
        anchor_number = 0
        def anchor(paragraph, block):
            nonlocal anchor_number
            anchor_number += 1
            marker = 'b' + hashlib.sha256(block['id'].encode()).hexdigest()[:32]
            start = OxmlElement('w:bookmarkStart')
            start.set(qn('w:id'), str(anchor_number))
            start.set(qn('w:name'), marker)
            end = OxmlElement('w:bookmarkEnd')
            end.set(qn('w:id'), str(anchor_number))
            paragraph._p.insert(0, start)
            paragraph._p.append(end)
            expected.append((marker, block['text']))
        for page in source['pages']:
            doc.add_heading(f"Source page {page['page']}", 1)
            table_map = {}
            for block in (b for b in source['blocks'] if b['page'] == page['page']):
                if block['region'] == 'table':
                    key = block['table']
                    if key not in table_map:
                        cells = [b for b in source['blocks'] if b['page'] == page['page'] and b.get('table') == key]
                        table_map[key] = doc.add_table(rows=max(b['row'] for b in cells) + 1, cols=max(b['col'] for b in cells) + 1)
                        table_map[key].style = 'Table Grid'
                    cell = table_map[key].cell(block['row'], block['col'])
                    cell.text = block['text']
                    anchor(cell.paragraphs[0], block)
                else:
                    paragraph = doc.add_paragraph(block['text'])
                    anchor(paragraph, block)
            for issue in page['issues']:
                doc.add_paragraph('Coverage issue: ' + issue)
        doc.add_page_break()
        doc.add_heading('Unchanged original PDF page images', 1)
        with pdfplumber.open(folder / 'inputs' / source['source']) as pdf:
            for page_index, page in enumerate(source['pages']):
                if page_index:
                    doc.add_page_break()
                doc.add_paragraph(f"Original PDF page {page['page']} - not revised")
                picture = pdf.pages[page['page'] - 1].to_image(resolution=100).original
                buffer = io.BytesIO()
                picture.convert('RGB').save(buffer, format='PNG')
                buffer.seek(0)
                width = min(6, 7.4 * picture.width / picture.height)
                doc.add_picture(buffer, width=Inches(width))
        path = out / f"{source['role']}_revised.docx"
        doc.save(path)
        reopened = Document(path)
        # Reopen OOXML and resolve bookmarks in both paragraphs and cells.
        found = {}
        for bookmark in reopened.element.xpath('.//w:bookmarkStart'):
            name = bookmark.get(qn('w:name'))
            text = ''.join(bookmark.getparent().xpath('.//w:t/text()'))
            found.setdefault(name, []).append(text)
        errors = []
        for marker, text in expected:
            if found.get(marker) != [text]:
                errors.append(marker)
        checks.append({'role': source['role'], 'blocks_expected': len(expected), 'blocks_reread': len(expected) - len(errors),
                       'exact_text_match': not errors, 'failed_anchors': errors,
                       'source_pages_retained': len(source['pages']), 'coverage_warnings': source['warnings']})
        files.append(path.name)
    report = {'export_id': export_id, 'approved_changes': log, 'documents': checks,
              'verified': all(c['exact_text_match'] for c in checks),
              'limits': ['Verification covers exact parsed text, approved patch reconciliation and original source hashes, not semantic correctness.',
                         'Page facsimiles retain original visual content; they are not edited. No OCR. Complex tables and footnotes are not semantically reconstructed.',
                         'DOCX layout has not been certified as equivalent to PDF.']}
    (out / 'verification.json').write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    (out / 'change-log.json').write_text(json.dumps(log, indent=2, ensure_ascii=False), encoding='utf-8')
    (out / 'mention-index.json').write_text(json.dumps(project['mentions'], indent=2, ensure_ascii=False), encoding='utf-8')
    if not report['verified']:
        raise ValueError('DOCX reread verification failed; exports were not published.')
    return {'id': export_id, 'files': files + ['verification.json', 'change-log.json', 'mention-index.json'], 'verification': report}
