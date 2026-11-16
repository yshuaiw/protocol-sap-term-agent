"""Document-only explanation proposals. Exact anchors establish location, never semantic truth."""
import hashlib
import json
from typing import Literal

from pydantic import Field

from .client import ModelError
from .schemas import Strict
from .workflow import batches, document_chunks
from ..operations import check


class Citation(Strict):
    block_id: str
    quote: str = Field(min_length=1, max_length=1800)
    support: str = Field(min_length=1, max_length=600, description='Explain which specific assertion this quotation supports, beyond mere occurrence of the term.')


class Claim(Strict):
    statement: str = Field(min_length=1, max_length=1500)
    kind: Literal['explicit', 'synthesis']
    evidence: list[Citation] = Field(min_length=1, max_length=8)


class ExplanationItem(Strict):
    concept_id: str
    claims: list[Claim] = Field(max_length=8)
    missing_reason: str = Field(max_length=600)


class ExplanationScan(Strict):
    concepts: list[ExplanationItem] = Field(max_length=6)


class Relationship(Strict):
    relationship: Literal['complementary', 'conflict', 'uncertain']
    reason: str = Field(min_length=1, max_length=1200)


def anchored_claim(item, units, documents, forms):
    lookup = {b['id']: (d, b) for d in documents for b in d['blocks']}
    allowed = {}
    for unit in units:
        allowed.setdefault(unit['block_id'], []).append((unit['start'], unit['end']))
    evidence = []
    for citation in item['evidence']:
        bid, quote = citation['block_id'], citation['quote']
        if bid not in allowed or quote.strip().casefold() in {f.strip().casefold() for f in forms}:
            raise ModelError('Explanation evidence is outside the submitted range or only repeats the term.')
        doc, block = lookup[bid]
        anchors = set()
        for start, end in allowed[bid]:
            pos = block['text'].find(quote, start, end)
            while pos >= 0:
                anchors.add((pos, pos + len(quote)))
                pos = block['text'].find(quote, pos + 1, end)
        if len(anchors) != 1:
            raise ModelError('Explanation quotation must uniquely match its submitted source range.')
        start, end = next(iter(anchors))
        evidence.append({**citation, 'doc_id': doc['id'], 'role': doc['role'], 'page': block['page'],
                         'region': block['region'], 'start': start, 'end': end,
                         'text_version': 'working_after_edits' if block.get('original_text', block['text']) != block['text'] else 'source_text',
                         'evidence_kind': block.get('evidence_kind', 'native_text')})
    digest = hashlib.sha256(json.dumps([item['statement'], item['kind'], evidence], sort_keys=True).encode()).hexdigest()[:32]
    return {**item, 'id': digest, 'evidence': evidence, 'review': 'pending', 'review_note': ''}


def evidence_current(claim, documents):
    blocks = {(d['id'], b['id']): b['text'] for d in documents for b in d['blocks']}
    return bool(claim.get('evidence')) and all(
        blocks.get((e['doc_id'], e['block_id']), '')[e['start']:e['end']] == e['quote']
        for e in claim['evidence'])


def supplement(project, client):
    """Scan every selected text range for each bounded group; preserve partial evidence on ordinary failure."""
    chunks = list(document_chunks(project['documents'], min(client.settings.chunk_chars, 6000), client.settings.chunk_units))
    state = {c['id']: {'claims': [], 'issues': [], 'missing_reasons': [], 'scanned': 0} for c in project['concepts']}
    all_complete = True
    try:
        for group in batches(project['concepts'], 6):
            refs = {f'T{i + 1}': c for i, c in enumerate(group)}
            for units in chunks:
                check()
                payload = {'explanation_targets': [{'id': ref, 'name': c['name'], 'aliases': c['aliases']} for ref, c in refs.items()],
                           'source_ranges': [{k: unit[k] for k in ('block_id', 'role', 'region', 'start', 'end', 'text')} for unit in units]}
                response = client.complete('explanation_scan', payload, ExplanationScan)
                ids = [row['concept_id'] for row in response['concepts']]
                if len(ids) != len(set(ids)) or set(ids) != set(refs):
                    raise ModelError('Explanation scan omitted, duplicated or invented concept references.')
                valid_response = True
                for row in response['concepts']:
                    concept = refs[row['concept_id']]
                    target = state[concept['id']]
                    target['scanned'] += 1
                    if not row['claims'] and row['missing_reason'] not in target['missing_reasons']:
                        target['missing_reasons'].append(row['missing_reason'])
                    for claim in row['claims']:
                        try:
                            validated = anchored_claim(claim, units, project['documents'], [concept['name'], *concept['aliases']])
                            if validated['id'] not in {c['id'] for c in target['claims']}:
                                target['claims'].append(validated)
                        except ModelError as exc:
                            valid_response = False
                            target['issues'].append(str(exc))
                if valid_response:
                    client.accept()
    except ModelError as exc:
        all_complete = False
        for target in state.values():
            if target['scanned'] < len(chunks):
                target['issues'].append(str(exc))
    for concept in project['concepts']:
        check()
        result = state[concept['id']]
        result['total'] = len(chunks)
        complete = result['scanned'] == len(chunks) and not result['issues'] and bool(chunks)
        if not complete:
            for old in concept.get('explanation', {}).get('claims', []):
                if evidence_current(old, project['documents']) and old['id'] not in {c['id'] for c in result['claims']}:
                    result['claims'].append({**old, 'previous_retained': True})
        result['relationship'] = 'not_assessed'
        result['reason'] = 'Model suggestions require assertion-by-assertion human evidence review.'
        if len(result['claims']) > 1:
            payload = {'concept': concept['name'], 'claims': result['claims']}
            if not all_complete:
                result['issues'].append('Relationship review not attempted after an incomplete evidence scan; claims retained separately.')
                complete = False
            elif len(json.dumps(payload, ensure_ascii=False)) > 50000:
                result['issues'].append('Too much sourced evidence for one relationship review; claims retained separately.')
                complete = False
            else:
                try:
                    relationship = client.complete('explanation_relation', payload, Relationship)
                    result.update(relationship)
                    client.accept()
                except ModelError as exc:
                    result['issues'].append(str(exc))
                    complete = False
                    all_complete = False
        result['status'] = ('conflict' if result['relationship'] == 'conflict' else
                            'needs_review' if result['claims'] else 'not_found') if complete else 'partial'
        if not chunks:
            result['issues'].append('No readable selected text ranges; no explanation could be sourced.')
        concept['explanation'] = result
    counts = {key: sum(c['explanation']['status'] == key for c in project['concepts'])
              for key in ('needs_review', 'conflict', 'not_found', 'partial')}
    return {'status': 'completed' if all_complete and not counts['partial'] else 'partial', 'counts': counts,
            'notice': 'Exact quotations prove source location only. Explanation meaning, synthesis and conflicts require human review.'}
