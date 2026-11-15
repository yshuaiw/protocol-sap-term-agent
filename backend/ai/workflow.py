"""Model discovery and semantic linking with deterministic evidence validation."""
import hashlib

from .client import ModelError
from .schemas import Extraction, Links


def stable_id(*parts):
    return hashlib.sha256(':'.join(map(str, parts)).encode()).hexdigest()[:32]


def batches(items, size=20):
    for start in range(0, len(items), size):
        yield items[start:start + size]


def document_chunks(documents, budget):
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
                if pending and length + end - start > budget:
                    yield pending
                    pending, length = [], 0
                pending.append(unit)
                length += end - start
                if end == len(text):
                    break
    if pending:
        yield pending


def generate_registry(project, client, run):
    chunks = list(document_chunks(project['documents'], client.settings.chunk_chars))
    lookup = {b['id']: (d, b) for d in project['documents'] for b in d['blocks']}
    found = {}
    run.update(status='running', chunks_total=len(chunks), chunks_completed=0, candidates=0)
    for index, units in enumerate(chunks):
        response = client.complete('discovery', {'chunks': units}, Extraction)
        allowed = {}
        for unit in units:
            allowed.setdefault(unit['block_id'], []).append((unit['start'], unit['end']))
        for item in response['mentions']:
            bid, start, end = item['block_id'], item['start'], item['end']
            if bid not in allowed or not any(a <= start < end <= b for a, b in allowed[bid]):
                raise ModelError('Discovery returned an unknown block or out-of-chunk anchor.')
            doc, block = lookup[bid]
            if block['text'][start:end] != item['text']:
                raise ModelError('Discovery evidence does not match the original text at its anchor.')
            key = (bid, start, end)
            if key not in found:
                found[key] = {**item, 'id': stable_id(bid, start, end, item['text']),
                              'role': doc['role'], 'doc_id': doc['id'], 'page': block['page'],
                              'region': block['region'], 'context': block['text'],
                              'evidence_kind': block.get('evidence_kind', 'native_text')}
        run.update(chunks_completed=index + 1, candidates=len(found))
        client.accept()
    candidates = list(found.values())
    concepts, mentions, ledger = {}, [], []
    for group_index, group in enumerate(batches(candidates)):
        payload = {'ledger': ledger, 'candidates': group}
        response = client.complete('linking', payload, Links)
        assignments = response['assignments']
        ids = [a['candidate_id'] for a in assignments]
        expected = {c['id'] for c in group}
        if len(ids) != len(set(ids)) or set(ids) != expected:
            raise ModelError('Semantic linking omitted, duplicated or invented candidate IDs.')
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
                raise ModelError('Linking referenced a concept outside the supplied ledger.')
            if cid in concepts and (concepts[cid]['category'] != item['category'] or
                                    concepts[cid]['name'] != item['canonical_name']):
                raise ModelError('Conflicting concept definitions/names in a linking response.')
            candidate = candidate_map[item['candidate_id']]
            concept = concepts.setdefault(cid, {'id': cid, 'name': item['canonical_name'], 'category': item['category'],
                'definition': item['definition'], 'aliases': [], 'confirmed': False,
                'evidence': f"{candidate['role']} {candidate['page']}: {candidate['context']}",
                'note': 'Model-supported proposal; human evidence review is required.', 'origin': 'groq'})
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
