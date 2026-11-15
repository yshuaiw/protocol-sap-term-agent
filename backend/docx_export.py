"""Apply anchored DOCX changes to XML text nodes without rebuilding the package."""
import difflib
import io
import zipfile

from lxml import etree

from .docx_input import P, paragraph_text, read_package, segments, xml


def replace_span(paragraph, start, end, replacement):
    cursor, affected = 0, []
    for node, text, editable in segments(paragraph):
        a, b = cursor, cursor + len(text)
        cursor = b
        if start < b and end > a:
            if not editable:
                raise ValueError('DOCX patch crosses a tab or line-break control; review this occurrence manually.')
            affected.append((node, text, max(0, start - a), min(len(text), end - a)))
    if not affected:
        raise ValueError('DOCX patch does not match a text run.')
    for i, (node, text, a, b) in enumerate(affected):
        node.text = text[:a] + (replacement if i == 0 else '') + text[b:]
        node.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')


def export_docx(source, content, path):
    package = read_package(content)
    trees = {}
    for block in source['blocks']:
        if block.get('evidence_kind') == 'visual_transcription':
            if block['text'] != block['original_text']:
                raise ValueError('Image text cannot be patched inside an original DOCX image.')
            continue
        if block['text'] == block['original_text']:
            continue
        if not block.get('editable', True):
            raise ValueError('This DOCX field/revision region is not editable.')
        part = block['part']
        tree = trees.setdefault(part, xml(package[part]))
        paragraph = list(tree.iter(P))[block['paragraph_index']]
        before = paragraph_text(paragraph)
        if before != block['original_text']:
            raise ValueError('Original DOCX anchor no longer matches.')
        matcher = difflib.SequenceMatcher(a=before, b=block['text'], autojunk=False)
        for tag, a, b, c, d in reversed(matcher.get_opcodes()):
            if tag == 'equal':
                continue
            if a == b:
                # Insertions attach to the preceding run without changing unrelated formatting.
                position = a if a < len(before) else max(0, a - 1)
                prefix = before[position:a]
                suffix = before[a:position + 1] if position == a else ''
                replace_span(paragraph, position, position + 1, prefix + block['text'][c:d] + suffix)
            else:
                replace_span(paragraph, a, b, block['text'][c:d])
        if paragraph_text(paragraph) != block['text']:
            raise ValueError('DOCX run patch validation failed.')
    for part, tree in trees.items():
        package[part] = etree.tostring(tree, xml_declaration=True, encoding='UTF-8', standalone=True)
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as output:
        for name, raw in package.items():
            output.writestr(name, raw)
    reopened = read_package(path.read_bytes())
    failures = []
    for block in source['blocks']:
        if 'part' not in block:
            continue
        paragraph = list(xml(reopened[block['part']]).iter(P))[block['paragraph_index']]
        if paragraph_text(paragraph) != block['text']:
            failures.append(block['id'])
    untouched = all(reopened[n] == raw for n, raw in read_package(content).items() if n not in trees)
    if failures or not untouched:
        raise ValueError('Exported DOCX failed text or unrelated-part verification.')
    native_count = sum('part' in b for b in source['blocks'])
    return {'role': source['role'], 'blocks_expected': native_count,
            'blocks_reread': native_count, 'exact_text_match': True, 'failed_anchors': [],
            'source_pages_retained': 0, 'source_page_image_hashes_match': True,
            'untouched_package_parts_match': untouched, 'native_docx': True,
            'visual_transcriptions_not_rewritten_into_images': len(source['blocks']) - native_count,
            'coverage_warnings': source['warnings']}
