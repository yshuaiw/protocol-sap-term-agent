"""Read Word OOXML directly, including non-body parts and text split across runs."""
import hashlib
import io
import re
import zipfile

from lxml import etree

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
NS = {'w': W}
P = '{' + W + '}p'
T = '{' + W + '}t'


def read_package(content):
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            items = archive.infolist()
            if len(items) > 5000 or sum(i.file_size for i in items) > 100 * 1024 * 1024:
                raise ValueError('DOCX expanded size is too large.')
            names = [i.filename for i in items]
            if len(names) != len(set(names)) or any('..' in n.split('/') or n.startswith('/') or '\\' in n for n in names):
                raise ValueError('Unsafe DOCX package path.')
            if 'word/document.xml' not in names or any('vbaProject' in n for n in names):
                raise ValueError('Provide a valid macro-free DOCX file.')
            return {i.filename: archive.read(i) for i in items}
    except zipfile.BadZipFile:
        raise ValueError('Invalid DOCX file.') from None


def xml(raw):
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
    if b'<!DOCTYPE' in raw or b'<!ENTITY' in raw:
        raise ValueError('DOCX XML entities are not supported.')
    return etree.fromstring(raw, parser)


def parts(package):
    return [name for name in package if re.fullmatch(r'word/(document|header\d+|footer\d+|footnotes|endnotes|comments)\.xml', name)]


def segments(paragraph):
    result = []
    for node in paragraph.iter():
        if node is paragraph or next((p for p in node.iterancestors() if p.tag == P), None) is not paragraph:
            continue
        if node.tag == T:
            result.append((node, node.text or '', True))
        elif node.tag == '{' + W + '}tab':
            result.append((node, '\t', False))
        elif node.tag in ('{' + W + '}br', '{' + W + '}cr'):
            result.append((node, '\n', False))
    return result


def paragraph_text(paragraph):
    return ''.join(t for _, t, _ in segments(paragraph))


def inspect_docx(content):
    package = read_package(content)
    document = xml(package['word/document.xml'])
    texts = [paragraph_text(p) for p in document.iter(P)]
    return {'pages': 1, 'unit_label': 'whole document', 'format': 'docx',
            'boundary_hints': [{'page': 1, 'evidence': '\n'.join(t for t in texts[:30] if t)[:3000]}],
            'notice': 'DOCX has no stable PDF page numbers. Import the whole independent document; combined DOCX splitting requires separate source files.'}


def parse_docx(content, role, start, end, name):
    if (start, end) != (1, 1):
        raise ValueError('DOCX input uses one whole-document unit, not page ranges. Split combined DOCX into independent files first.')
    package = read_package(content)
    digest = hashlib.sha256(content).hexdigest()
    did = hashlib.sha256(f'{digest}:{role}:docx'.encode()).hexdigest()[:16]
    blocks, warnings = [], []
    for part in parts(package):
        tree = xml(package[part])
        region = 'header' if '/header' in part else 'footer' if '/footer' in part else 'footnote' if 'footnotes' in part else 'endnote' if 'endnotes' in part else 'comment' if 'comments' in part else 'body'
        for index, paragraph in enumerate(tree.iter(P)):
            text = paragraph_text(paragraph)
            if not text:
                continue
            ancestors = list(paragraph.iterancestors())
            kind = 'textbox' if any(etree.QName(n).localname == 'txbxContent' for n in ancestors) else region
            if region == 'body' and any(n.tag == '{' + W + '}tc' for n in ancestors):
                kind = 'table'
            styles = paragraph.xpath('./w:pPr/w:pStyle/@w:val', namespaces=NS)
            if styles and styles[0].lower().startswith('heading'):
                kind = 'heading'
            unsafe = bool(paragraph.xpath('.//w:fldChar|.//w:instrText|.//w:del|.//w:ins', namespaces=NS)) or region == 'comment'
            if unsafe:
                warnings.append(f'{part} paragraph {index}: fields, tracked revisions or reviewer comments retained; edits blocked pending manual cleanup.')
            blocks.append({'id': f'{did}:{part}:p{index}', 'page': 1, 'region': kind, 'text': text,
                           'original_text': text, 'part': part, 'paragraph_index': index,
                           'bbox': None, 'editable': not unsafe, 'evidence_kind': 'native_text'})
    media = [n for n in package if n.startswith('word/media/')]
    if media:
        warnings.append(f'{len(media)} embedded media file(s); visual transcription depends on configured vision model. Media originals are retained.')
    unsupported = [n for n in package if n.startswith(('word/charts/', 'word/embeddings/'))]
    if unsupported:
        warnings.append('Embedded charts/objects retained but not fully interpreted: ' + ', '.join(unsupported[:8]))
    if any(b'<m:oMath' in package[n] or b':altChunk' in package[n] for n in parts(package)):
        warnings.append('Equations or alternate-content imports retained but not fully indexed; review original source.')
    if not blocks and not media:
        raise ValueError('DOCX contains no readable text or embedded media.')
    words = sum(len(b['text'].split()) for b in blocks)
    return {'id': did, 'role': role, 'name': name, 'format': 'docx', 'unit_label': 'whole document',
            'sha256': digest, 'start': 1, 'end': 1, 'blocks': blocks, 'warnings': warnings,
            'pages': [{'page': 1, 'words': words, 'represented_words': words,
                       'tables': sum(len(xml(package[n]).xpath('.//w:tbl', namespaces=NS)) for n in parts(package)), 'images': len(media),
                       'issues': warnings.copy()}],
            'coverage_notice': 'OOXML text from body, nested tables, headers, footers, notes, comments and text boxes indexed. Whole document only; page numbers are not stable. Drawings, fields, tracked changes and embedded objects require review.'}
