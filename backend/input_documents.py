from .documents import inspect_pdf, parse_pdf
from .docx_input import inspect_docx, parse_docx


def input_format(content):
    if content.startswith(b'%PDF-'):
        return 'pdf'
    if content.startswith(b'PK'):
        return 'docx'
    raise ValueError('Use an unlocked PDF or a macro-free DOCX document.')


def inspect_input(content):
    fmt = input_format(content)
    if fmt == 'docx':
        return inspect_docx(content)
    return {**inspect_pdf(content), 'format': 'pdf', 'unit_label': 'PDF page'}


def parse_input(content, role, start, end, name):
    fmt = input_format(content)
    doc = parse_docx(content, role, start, end, name) if fmt == 'docx' else parse_pdf(content, role, start, end, name)
    doc['format'] = fmt
    doc.setdefault('unit_label', 'PDF page')
    return doc
