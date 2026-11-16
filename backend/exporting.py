"""New editable Word copies; originals stay separate and hash-verified unchanged."""
import hashlib
import json
from pathlib import Path

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor
from .docx_export import export_docx
from .docx_input import paragraph_text


def export_pair(project, folder: Path, log: list, export_id: str):
    out = folder / 'exports' / export_id
    out.mkdir(parents=True, exist_ok=True)
    files, checks = [], []
    for source in project['documents']:
        source_path = folder / 'inputs' / source['source']
        original = source_path.read_bytes()
        if hashlib.sha256(original).hexdigest() != source['sha256']:
            raise ValueError('Original source file changed; exports were not published.')
        if source.get('format') == 'docx':
            path = out / f"{source['role']}_revised.docx"
            check = export_docx(source, original, path)
            checks.append(check)
            files.append(path.name)
            continue
        doc = Document()
        section = doc.sections[0]
        section.header.paragraphs[0].text = f"{source['role']} | reconstructed working copy"
        section.footer.paragraphs[0].text = 'Original documents are retained separately and unchanged. See verification.json.'
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
                          'Original files remain separate and unchanged; approved edits appear only in this working copy. '
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
                    if block.get('evidence_kind') == 'visual_transcription':
                        doc.add_paragraph('Unverified model transcription from this source page; compare the original image.', style='Caption')
                    paragraph = doc.add_paragraph(block['text'])
                    anchor(paragraph, block)
            for issue in page['issues']:
                doc.add_paragraph('Coverage issue: ' + issue)
        path = out / f"{source['role']}_revised.docx"
        doc.save(path)
        reopened = Document(path)
        # Reopen OOXML and resolve bookmarks in both paragraphs and cells.
        found = {}
        for bookmark in reopened.element.xpath('.//w:bookmarkStart'):
            name = bookmark.get(qn('w:name'))
            text = paragraph_text(bookmark.getparent())
            found.setdefault(name, []).append(text)
        errors = []
        for marker, text in expected:
            if found.get(marker) != [text]:
                errors.append(marker)
        checks.append({'role': source['role'], 'blocks_expected': len(expected), 'blocks_reread': len(expected) - len(errors),
                       'exact_text_match': not errors, 'failed_anchors': errors,
                       'source_pages_retained': len(reopened.inline_shapes),
                       'source_page_image_hashes_match': None,  # Legacy field: no page-image comparison is performed.
                       'page_image_appendix_included': bool(reopened.inline_shapes),
                       'coverage_warnings': source['warnings']})
        files.append(path.name)
    for source, check in zip(project['documents'], checks):
        original = (folder / 'inputs' / source['source']).read_bytes()
        check['original_source_hashes_match'] = hashlib.sha256(original).hexdigest() == source['sha256']
    report = {'export_id': export_id, 'approved_changes': log, 'documents': checks,
              'verified': all(c['exact_text_match'] and c['original_source_hashes_match']
                              and not c.get('page_image_appendix_included', False) for c in checks),
              'limits': ['Verification covers exact parsed text, approved patch reconciliation and original source hashes, not semantic correctness.',
                         'Original files are retained separately; PDF page headings and page-image appendices are not added. Model visual transcriptions require human source review.',
                         'Native DOCX packages preserve unrelated parts; PDF reconstruction, complex structures and final layout still require visual verification.']}
    (out / 'verification.json').write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    (out / 'change-log.json').write_text(json.dumps(log, indent=2, ensure_ascii=False), encoding='utf-8')
    (out / 'mention-index.json').write_text(json.dumps(project['mentions'], indent=2, ensure_ascii=False), encoding='utf-8')
    if not report['verified']:
        if any(not c['original_source_hashes_match'] for c in checks):
            raise ValueError('Original source file changed; exports were not published.')
        raise ValueError('DOCX reread verification failed; exports were not published.')
    return {'id': export_id, 'files': files + ['verification.json', 'change-log.json', 'mention-index.json'], 'verification': report}
