"""AI structure scan/review with exact program-owned evidence references."""
from collections import Counter

from .boundary_context import call, review_payloads, scan_payloads, supplement_unreadable
from .boundary_schemas import BoundaryRanges, BoundaryStarts


def _validated_rows(response, payload, inventory, issues):
    targets = {t['source_id'] for t in payload['targets']}
    counts = Counter(r['candidate_id'] for r in response['documents'])
    missing = targets - counts.keys()
    if missing:
        issues.append('The model omitted some candidate decisions; those starts remain unresolved.')
    allowed = {s['id'] for c in payload['contexts'] for s in c['evidence']}
    rows = []
    for item in response['documents']:
        if item['candidate_id'] not in targets or counts[item['candidate_id']] != 1:
            issues.append('A boundary review returned an unknown or duplicated candidate decision; it was not accepted.')
            continue
        source = inventory['sources'].get(item['source_id'])
        if not source or source['id'] not in allowed:
            issues.append('A boundary proposal cited evidence outside its submitted context; it was not accepted.')
            continue
        start, end = source['page'], item['end']
        if not 1 <= start <= end <= inventory['unit_count']:
            issues.append('A boundary proposal used an invalid PDF page range; it was not accepted.')
            continue
        row = {k: v for k, v in item.items() if k != 'candidate_id'}
        row.update(start=start, evidence=source['text'], evidence_kind=source['evidence_kind'],
                   evidence_start=source['start'], evidence_end=source['end'],
                   requires_visual_review=source['evidence_kind'] == 'visual_transcription',
                   applicable=item['kind'] == 'independent_document' and item['role'] != 'unknown' and item['confidence'] != 'low')
        rows.append(row)
    return rows


def suggest_boundaries(inventory, client, content=None):
    issues, candidates, notes, documents = [], {}, [], []
    unreadable = [p['page'] for p in inventory['pages'] if not p['native_readable']]
    visual_pages = supplement_unreadable(inventory, content, client) if content is not None else []
    for payload in scan_payloads(inventory, client):
        response = call(client, 'boundary_scan', payload, BoundaryStarts)
        allowed = {s['id'] for p in payload['pages'] for s in p['sources']}
        for candidate in response['candidates']:
            if candidate['source_id'] not in allowed:
                issues.append('A structure scan cited an unknown source reference; it was not accepted.')
                continue
            sid = candidate['source_id']
            if sid in candidates and candidates[sid] != candidate:
                candidates[sid] = {**candidate, 'kind': 'uncertain', 'confidence': 'low',
                                   'reason': 'Model classifications conflicted for this source; manual review is required.'}
                issues.append('Conflicting structure classifications were kept uncertain.')
            else:
                candidates[sid] = candidate
        inventory['limitations'].extend(response['limitations'])
        client.accept()
    # References (contents entries, mentions of a separately planned SAP) cannot become ranges.
    review = sorted((c for c in candidates.values() if c['kind'] != 'reference'),
                    key=lambda c: (inventory['sources'][c['source_id']]['page'], c['source_id']))
    for payload in review_payloads(inventory, review, client):
        response = call(client, 'boundary_review', payload, BoundaryRanges)
        documents.extend(_validated_rows(response, payload, inventory, issues))
        notes.append(response['compatibility_note'])
        client.accept()
    unique = {}
    for doc in documents:
        key = (doc['role'], doc['start'], doc['end'], doc['kind'])
        if key in unique and unique[key]['confidence'] != doc['confidence']:
            unique[key].update(confidence='low', applicable=False)
            issues.append('Repeated reviews disagreed on a proposed range; manual review is required.')
        else:
            unique[key] = doc
    documents = sorted(unique.values(), key=lambda d: (d['start'], d['end'], d['role']))
    independent = [d for d in documents if d['kind'] == 'independent_document']
    for i, left in enumerate(independent):
        for right in independent[i + 1:]:
            if max(left['start'], right['start']) <= min(left['end'], right['end']):
                left['applicable'] = right['applicable'] = False
                issues.append('Independent-document ranges overlap. Adjust or select document versions manually.')
    applicable = [d for d in documents if d['applicable']]
    unresolved = any(d['kind'] == 'uncertain' for d in documents)
    pair = not unresolved and len(applicable) == 2 and {d['role'] for d in applicable} == {'Protocol', 'SAP'}
    if inventory['format'] == 'docx':
        pair = False
        inventory['limitations'].append('Combined DOCX cannot be split here. Provide separate independent documents.')
    remaining = [p['page'] for p in inventory['pages'] if not p['native_readable'] and not p['text'].strip()]
    if remaining:
        inventory['limitations'].append('Some source pages remain unreadable; absence of an independent SAP has not been established.')
    default_note = ('Document range proposals were returned. Review every proposed identity, range and version against the source.' if documents else
                    'No usable independent-document ranges were returned. This does not prove the source lacks a Protocol or SAP; inspect the source and coverage gaps.')
    status = 'proposed' if pair and not issues else 'needs_review' if documents or issues or remaining else 'no_pair'
    return {'status': status, 'can_apply_pair': pair and not issues, 'documents': documents,
            'compatibility_note': '\n'.join(dict.fromkeys(n for n in notes if n)) or default_note,
            'issues': list(dict.fromkeys(issues)), 'limitations': list(dict.fromkeys(inventory['limitations'])),
            'coverage': {'pages_indexed': inventory['unit_count'], 'native_readable_pages': inventory['unit_count'] - len(unreadable),
                         'visual_pages_read': visual_pages, 'unreadable_pages': remaining,
                         'mode': client.settings.pdf_mode, 'structure_excerpts_only': True},
            'configuration': client.settings.provenance()}
