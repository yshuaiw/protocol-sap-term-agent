"""Model discovery and semantic linking with deterministic evidence validation."""
import hashlib
import json

from .client import ModelError
from .schemas import Extraction, Links, DiscoveryRepairs


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
    concepts, mentions, ledger = {}, [], []
    for group_index, group in enumerate(batches(candidates, client.settings.link_batch_size)):
        candidate_refs = {f'C{i + 1}': candidate['id'] for i, candidate in enumerate(group)}
        ledger_refs = {f'L{i + 1}': concept['id'] for i, concept in enumerate(ledger)}
        reverse_candidates = {value: key for key, value in candidate_refs.items()}
        reverse_ledger = {value: key for key, value in ledger_refs.items()}
        payload = {'ledger': [{**concept, 'id': reverse_ledger[concept['id']]} for concept in ledger],
                   'candidates': [{**{k: v for k, v in candidate.items() if k not in ('id', 'doc_id', 'block_id', 'start', 'end')},
                                   'id': reverse_candidates[candidate['id']]} for candidate in group]}
        response = client.complete('linking', payload, Links)
        assignments = response['assignments']
        ids = [a['candidate_id'] for a in assignments]
        expected = set(candidate_refs)
        if len(ids) != len(set(ids)) or set(ids) != expected:
            raise ModelError('Semantic linking omitted, duplicated or invented candidate IDs.')
        assignments = [{**item, 'candidate_id': candidate_refs[item['candidate_id']],
                        'group_id': ledger_refs.get(item['group_id'], item['group_id'])} for item in assignments]
        group_map = {}
        candidate_map = {c['id']: c for c in group}
        for item in assignments:
            raw = item['group_id']
            if item['ambiguous']:
                cid = stable_id('ambiguous', item['candidate_id'])
            elif raw in concepts:
                cid = raw
            elif raw.startswith('new:') and len(raw) <= 150:
                cid = group_map.setdefault(raw, stable_id(project['id'], group_index, raw))
            else:
                cid = stable_id('unknown-link', item['candidate_id'])
                item = {**item, 'ambiguous': True,
                        'reason': 'Model returned an unknown concept reference; kept separate for reviewer association. ' + item['reason']}
                run.setdefault('linking_conflicts', []).append(item['candidate_id'])
            if cid in concepts and (concepts[cid]['category'] != item['category'] or
                                    concepts[cid]['name'] != item['canonical_name']):
                # Abstain rather than overwrite the ledger or merge conflicting model identities.
                cid = stable_id('link-conflict', item['candidate_id'])
                item = {**item, 'ambiguous': True,
                        'reason': 'Model group ID conflicts with its name/category; kept separate for reviewer association. ' + item['reason']}
                run.setdefault('linking_conflicts', []).append(item['candidate_id'])
            candidate = candidate_map[item['candidate_id']]
            concept = concepts.setdefault(cid, {'id': cid, 'name': item['canonical_name'], 'category': item['category'],
                'definition': item['definition'], 'aliases': [], 'confirmed': False,
                'evidence': f"{candidate['role']} {candidate['page']}: {candidate['context']}",
                'note': 'Model grouping is uncertain; reviewer association required.' if item['ambiguous'] else
                        'Model-supported proposal; human evidence review is required.', 'origin': 'groq'})
            if candidate['text'] != concept['name'] and candidate['text'] not in concept['aliases']:
                concept['aliases'].append(candidate['text'])
            mentions.append({k: candidate[k] for k in ('id', 'doc_id', 'role', 'page', 'region', 'block_id',
                                                      'start', 'end', 'text', 'context', 'evidence_kind')} | {
                'concept_id': cid, 'candidates': [cid], 'status': 'unresolved', 'manual': False,
                'model_link_status': 'ambiguous' if item['ambiguous'] else 'supported',
                'model_reason': item['reason'], 'origin': 'groq'})
        ledger = [{'id': c['id'], 'name': c['name'], 'category': c['category'], 'definition': c['definition'],
                   'aliases': c['aliases'], 'evidence': c['evidence']} for c in concepts.values()]
        client.accept()
    project['concepts'], project['mentions'] = list(concepts.values()), mentions
    project['engine'] = 'groq-ai-v1'
    run.update(status='completed', concepts=len(concepts), mentions=len(mentions),
               blocks_scanned=len(lookup), coverage_notice='All selected text blocks submitted. Semantic recall is not certified. Visual transcriptions and unsupported media require review.')
