"""Bound complete text request envelopes; retain originals through program-owned ranges."""
import json

from .client import ModelError
from .prompts import SYSTEM, TASKS
from .providers import request_spec
from .schemas import Links

INPUT_BUDGET = 60000  # Serialized characters, not a claim about provider token capacity.


def request_size(client, stage, payload):
    prompt = SYSTEM + '\nTASK: ' + TASKS[stage] + '\nJSON schema: ' + json.dumps(Links.model_json_schema())
    _, _, body, _ = request_spec(client.settings.provider, client.settings.model, '', stage, prompt,
                                json.dumps(payload, ensure_ascii=False), Links.model_json_schema(), client.settings.max_output_tokens)
    return len(json.dumps(body, ensure_ascii=False))


def fits(client, stage, payload, reserve=0):
    return request_size(client, stage, payload) <= INPUT_BUDGET - reserve


def wire_candidate(c, ident):
    start, end = max(0, c['start'] - 600), min(len(c['context']), c['end'] + 600)
    keys = ('text', 'canonical_name', 'category', 'definition', 'evidence', 'role', 'page', 'region',
            'preceding_context', 'following_context', 'evidence_kind')
    return {**{k: c[k] for k in keys if k in c}, 'id': ident, 'context': c['context'][start:end],
            'context_range': [start, end], 'context_complete': start == 0 and end == len(c['context']),
            'source': {k: c[k] for k in ('doc_id', 'block_id', 'start', 'end') if k in c}}


def concept_card(c, representative, ident):
    return {'id': ident, 'name': c['name'], 'category': c['category'], 'definition': c['definition'],
            'evidence': representative['evidence'],
            'source': {k: representative[k] for k in ('role', 'page', 'block_id', 'start', 'end')}}


def index_fragments(concepts, representatives, refs):
    for cid, c in concepts.items():
        base = concept_card(c, representatives[cid], refs[cid])
        aliases = []
        for alias in c['aliases']:
            if len(json.dumps({**base, 'aliases': [*aliases, alias]}, ensure_ascii=False)) > 8000 and aliases:
                yield {**base, 'aliases': aliases}
                aliases = []
            aliases.append(alias)
        yield {**base, 'aliases': aliases}


def pack_rows(client, stage, base, field, rows):
    pending = []
    for row in rows:
        if not fits(client, stage, {**base, field: [*pending, row]}):
            if pending:
                yield {**base, field: pending}
                pending = []
            if not fits(client, stage, {**base, field: [row]}):
                raise ModelError('A single linking index entry exceeds its request budget; sources retained and no grouping guessed.')
        pending.append(row)
    if pending:
        yield {**base, field: pending}


def candidate_groups(candidates, count, client):
    pending = []
    for c in candidates:
        trial = [*pending, c]
        payload = {'phase': 'new_groups', 'ledger': [], 'candidates': [wire_candidate(x, f'C{i+1}') for i, x in enumerate(trial)]}
        if pending and (len(trial) > count or not fits(client, 'linking_create', payload, reserve=24000)):
            yield pending
            pending = []
        pending.append(c)
        if not fits(client, 'linking_create', {'phase': 'new_groups', 'ledger': [],
                'candidates': [wire_candidate(x, f'C{i+1}') for i, x in enumerate(pending)]}, reserve=24000):
            raise ModelError('A single anchored candidate exceeds the linking budget; source retained for review.')
    if pending:
        yield pending


def source_rows(c, owner):
    text, start = c['context'], 0
    while start < len(text):
        end = min(len(text), start + 2000)
        yield {'owner': owner, 'doc_id': c.get('doc_id', ''), 'block_id': c['block_id'], 'role': c['role'], 'page': c['page'],
               'start': start, 'end': end, 'text': text[start:end]}
        if end == len(text):
            break
        start = end - 150


def evidence_packets(client, base, rows):
    pending = []
    todo = list(rows)
    while todo:
        row = todo.pop(0)
        if fits(client, 'linking_verify', {**base, 'source_ranges': [*pending, row]}):
            pending.append(row)
            continue
        if pending:
            yield {**base, 'source_ranges': pending}
            pending = []
            todo.insert(0, row)
        elif len(row['text']) > 1:
            mid = len(row['text']) // 2
            overlap = min(150, mid // 4)
            todo[:0] = [{**row, 'end': row['start'] + mid + overlap, 'text': row['text'][:mid+overlap]},
                        {**row, 'start': row['start'] + mid - overlap, 'text': row['text'][mid-overlap:]}]
        else:
            raise ModelError('Link evidence metadata exceeds the bounded request; no source was discarded.')
    if pending:
        yield {**base, 'source_ranges': pending}
