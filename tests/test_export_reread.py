"""Real DOCX serialization must preserve whitespace without accepting changed text."""
import json

import pytest
from docx.document import Document as WordDocument

from backend.documents import parse_pdf
from backend.exporting import export_pair
from tests.test_workflow import make_pdf


@pytest.mark.parametrize('corrupt', [False, True])
def test_pdf_reconstruction_rereads_breaks_tabs_and_rejects_changed_text(tmp_path, monkeypatch, corrupt):
    inputs = tmp_path / 'inputs'
    inputs.mkdir()
    originals, documents = {}, []
    for role in ('Protocol', 'SAP'):
        raw = make_pdf(role)
        source = role + '.pdf'
        originals[source] = raw
        (inputs / source).write_bytes(raw)
        doc = parse_pdf(raw, role, 1, 1, source)
        doc['source'] = source
        doc['blocks'] = [
            {'id': role + '-body', 'page': 1, 'region': 'body', 'text': 'Arm A\nreceives\t10 mg.'},
            {'id': role + '-visual', 'page': 1, 'region': 'image_text',
             'evidence_kind': 'visual_transcription', 'text': 'Arm A:\nFirst line\nSecond line\t😀'},
            {'id': role + '-cell', 'page': 1, 'region': 'table', 'table': 0, 'row': 0, 'col': 0,
             'text': 'Arm A\nDose\t10 mg'},
        ]
        documents.append(doc)
    if corrupt:
        save = WordDocument.save
        def damaged_save(self, path):
            bookmark = self.element.xpath('.//w:bookmarkStart')[0]
            node = bookmark.getparent().xpath('.//w:t')[0]
            node.text += ' altered'
            save(self, path)
        monkeypatch.setattr(WordDocument, 'save', damaged_save)
        with pytest.raises(ValueError, match='DOCX reread verification failed'):
            export_pair({'documents': documents, 'mentions': []}, tmp_path, [], 'fixture')
    else:
        result = export_pair({'documents': documents, 'mentions': []}, tmp_path, [], 'fixture')
        assert result['verification']['verified']
        assert all(d['blocks_reread'] == 3 and d['exact_text_match'] and d['source_page_image_hashes_match']
                   for d in result['verification']['documents'])
    report = json.loads((tmp_path / 'exports/fixture/verification.json').read_text(encoding='utf-8'))
    assert report['verified'] is not corrupt
    assert all((inputs / name).read_bytes() == raw for name, raw in originals.items())
