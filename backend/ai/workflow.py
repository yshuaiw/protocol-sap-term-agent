"""Model discovery and semantic linking with deterministic evidence validation."""
import hashlib
import json

from .client import ModelError
from .schemas import Extraction, DiscoveryRepairs


def stable_id(*parts):
    return hashlib.sha256(':'.join(map(str, parts)).encode()).hexdigest()[:32]


def batches(items, size=20):
    for start in range(0, len(items), size):
        yield items[start:start + size]


def document_chunks(documents, budget, max_units=8):
    pending, length = [], 0
    for doc in documents:
        blocks = doc['blocks']
        for index, block in enumerate(blocks):
            text = block['text']
            step = max(1, budget - 300)
            starts = range(0, len(text), step) if len(text) > budget else [0]
            for start in starts:
                end = min(len(text), start + budget)
                unit = {'block_id': block['id'], 'role': doc['role'], 'region': block['region'],
                        'start': start, 'end': end, 'text': text[start:end],
                        'preceding_context': blocks[index - 1]['text'][-400:] if index else '',
                        'following_context': blocks[index + 1]['text'][:400] if index + 1 < len(blocks) else ''}
                # Short blocks also require a full output record; contexts/IDs cost input tokens.
                cost = len(json.dumps(unit, ensure_ascii=False))
                if pending and (length + cost > budget or len(pending) >= max_units):
                    yield pending
                    pending, length = [], 0
                pending.append(unit)
                length += cost
                if end == len(text):
                    break
    if pending:
        yield pending


def locate_evidence(text, ranges, mention):
    """Compute Unicode offsets from exact, uniquely identifying model quotations."""
    quote, term = mention['evidence'], mention['text']
    relative = []
    position = quote.find(term)
    while position >= 0:
        relative.append(position)
        position = quote.find(term, position + 1)
    if not relative:
        raise ModelError('Discovery evidence does not contain the proposed term exactly. No approximate match was accepted.')
    anchors = set()
    for start, end in ranges:
        position = text.find(quote, start, end)
        while position >= 0:
            anchors.update((position + offset, position + offset + len(term)) for offset in relative)
            if len(anchors) > 1:
                raise ModelError('Discovery evidence is ambiguous within its submitted text block; a unique context quotation is required.')
            position = text.find(quote, position + 1, end)
    if not anchors:
        raise ModelError('Discovery evidence quotation is absent from its submitted text range. No approximate match was accepted.')
    return next(iter(anchors))


def discovery_payload(units):
    # Every source block is processed as a target; duplicated neighbor text is linking context only.
    fields = ('block_id', 'role', 'region', 'start', 'end', 'text')
    return {'chunks': [{field: unit[field] for field in fields} for unit in units]}


def anchored_item(extracted, allowed, lookup):
    item = {key: value for key, value in extracted.items() if key not in ('term_text', 'context_quote')}
    item.update(text=extracted['term_text'], evidence=extracted['context_quote'])
    bid = item['block_id']
    if bid not in allowed:
        raise ModelError('Discovery returned an unknown block outside the supplied chunk.')
    _, block = lookup[bid]
    start, end = locate_evidence(block['text'], allowed[bid], item)
    return {**item, 'start': start, 'end': end}


def validate_discovery(response, units, lookup, client, run):
    allowed, valid, rejected = {}, [], []
    for unit in units:
        allowed.setdefault(unit['block_id'], []).append((unit['start'], unit['end']))
    for index, extracted in enumerate(response['mentions']):
        try:
            valid.append(anchored_item(extracted, allowed, lookup))
        except ModelError as error:
            rejected.append({'rejected_id': str(index), 'proposal': extracted, 'validation_error': str(error)})
    if not rejected:
        return valid
    # One model repair pass; no unanchored item is accepted or silently discarded.
    try:
        repaired = client.complete('discovery_repair', {**discovery_payload(units), 'rejected': rejected}, DiscoveryRepairs)
    except ModelError as error:
        raise ModelError('Discovery evidence repair failed after: ' + rejected[0]['validation_error'] + ' ' + str(error)) from None
    decisions = repaired['decisions']
    ids = [item['rejected_id'] for item in decisions]
    if len(ids) != len(set(ids)) or set(ids) != {r['rejected_id'] for r in rejected}:
        raise ModelError('Discovery evidence repair omitted, duplicated or invented proposal IDs.')
    proposals = {r['rejected_id']: r['proposal'] for r in rejected}
    exclusions = []
    for decision in decisions:
        if decision['action'] == 'corrected' and decision['mentions']:
            valid.extend(anchored_item(item, allowed, lookup) for item in decision['mentions'])
        elif decision['action'] == 'out_of_scope' and not decision['mentions']:
            proposal = proposals[decision['rejected_id']]
            exclusions.append({'term': proposal['term_text'], 'reason': decision['reason'], 'block_id': proposal['block_id']})
        else:
            raise ModelError('Discovery evidence remains unresolved after one model repair pass; existing register retained.')
    run['discovery_repair_operations'] = run.get('discovery_repair_operations', 0) + 1
    run.setdefault('discovery_exclusions', []).extend(exclusions)
    return valid


def generate_registry(project, client, run):
    chunks = list(document_chunks(project['documents'], client.settings.chunk_chars, client.settings.chunk_units))
    lookup = {b['id']: (d, b) for d in project['documents'] for b in d['blocks']}
    found = {}
    run.update(status='running', chunks_total=len(chunks), chunks_completed=0, candidates=0)
    for index, units in enumerate(chunks):
        response = client.complete('discovery', discovery_payload(units), Extraction)
        for item in validate_discovery(response, units, lookup, client, run):
            bid, start, end = item['block_id'], item['start'], item['end']
            doc, block = lookup[bid]
            source_unit = next(u for u in units if u['block_id'] == bid and u['start'] <= start < end <= u['end'])
            key = (bid, start, end)
            if key not in found:
                found[key] = {**item, 'start': start, 'end': end, 'id': stable_id(bid, start, end, item['text']),
                              'role': doc['role'], 'doc_id': doc['id'], 'page': block['page'],
                              'region': block['region'], 'context': block['text'],
                              'preceding_context': source_unit['preceding_context'],
                              'following_context': source_unit['following_context'],
                              'evidence_kind': block.get('evidence_kind', 'native_text')}
        run.update(chunks_completed=index + 1, candidates=len(found))
        client.accept()
    candidates = list(found.values())
    from .linking import link_registry
    link_registry(project, candidates, client, run)
    project['engine'] = client.settings.provider + '-ai-v1'
    run.update(status='completed', concepts=len(project['concepts']), mentions=len(project['mentions']),
               blocks_scanned=len(lookup), coverage_notice='All selected text blocks submitted. Semantic recall is not certified. Visual transcriptions and unsupported media require review.')
