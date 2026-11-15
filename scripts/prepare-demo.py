"""Build a real local demo from the user's PDFs; never downloads or publishes source data."""
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.documents import parse_pdf
from backend.registry import build_registry
from backend.store import Store


def main():
    root = Path(__file__).resolve().parents[1]
    store = Store(root / 'data' / 'projects')
    selections = [('DAPA-CKD_protocol.pdf', 'Protocol', 3, 79), ('DAPA-CKD_SAP.pdf', 'SAP', 1, 30)]
    docs, inputs = [], {}
    for name, role, first, last in selections:
        content = (root / 'Protocols' / name).read_bytes()
        doc = parse_pdf(content, role, first, last, name)
        filename = hashlib.sha256(content).hexdigest()[:16] + '.pdf'
        doc['source'] = filename
        docs.append(doc)
        inputs[filename] = content
        print(f'{role}: {len(doc["pages"])} pages; {len(doc["blocks"])} blocks; {len(doc["warnings"])} coverage flags', flush=True)
    note = ('D169AC00001 original documents: Protocol 1.0 dated 26 October 2016, PDF pp3-79; '
            'SAP Edition 1.0 dated 1 February 2017, PDF pp1-30. Later versions are excluded from extraction but retained in original files. '
            'Same study code and original-edition timing verified; explicit SAP-to-protocol version cross-reference not located, so compatibility is not certified. '
            'This is a technical terminology demonstration, not a validated clinical revision.')
    p = store.create('DAPA-CKD · original editions · review needed', docs, inputs, note)
    build_registry(p)
    store.save(p, 'Generated rule candidates on every page of the selected original editions; no manual truth labels or model calls')
    out = root / 'output'
    out.mkdir(exist_ok=True)
    (out / 'DAPA-CKD-demo-project.zip').write_bytes(store.bundle(p['id']))
    summary = {'id': p['id'], 'concepts': len(p['concepts']), 'mentions': len(p['mentions']),
               'documents': [{'role': d['role'], 'pages': len(d['pages']), 'blocks': len(d['blocks']),
                              'words': sum(x['words'] for x in d['pages']),
                              'represented_words': sum(x['represented_words'] for x in d['pages']),
                              'tables': sum(x['tables'] for x in d['pages']), 'warnings': len(d['warnings'])} for d in docs],
               'version_note': note}
    (out / 'real-demo-summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == '__main__':
    main()
