"""Paged semantic association with explicit abstention and exact legacy-cache replay."""
from .client import ModelError
from .schemas import Links
from .linking_context import (INPUT_BUDGET, candidate_groups, concept_card, evidence_packets,
                              fits, index_fragments, pack_rows, request_size, source_rows, wire_candidate)
from ..operations import CURRENT, check


def publish(progress, client):
    progress['http_attempts'] = client.http_attempts - progress.get('_initial_attempts', client.http_attempts)
    op = CURRENT.get()
    if op:
        op.progress = {k: v for k, v in progress.items() if not k.startswith('_')}


def checked_assignments(response, ids):
    rows = response['assignments']
    returned = [r['candidate_id'] for r in rows]
    if len(returned) != len(set(returned)) or set(returned) != set(ids):
        raise ModelError('Semantic linking omitted, duplicated or invented candidate IDs.')
    return rows


def call(client, stage, payload, progress):
    size = request_size(client, stage, payload)
    if size > INPUT_BUDGET:
        raise ModelError('Linking packet exceeds its complete request budget; no source was truncated.')
    publish(progress, client)
    result = client.complete(stage, payload, Links)
    progress['max_input_characters'] = max(progress.get('max_input_characters', 0), size)
    progress['cache_hits'] = progress.get('cache_hits', 0) + int(client.records[-1]['cached'])
    return checked_assignments(result, [c['id'] for c in payload['candidates']])


def abstain(c, reason):
    return dict(candidate_id=c['id'], group_id='new:uncertain-' + c['id'], canonical_name=c['canonical_name'],
                category=c['category'], definition=c['definition'], reason=reason[:1500], ambiguous=True)


def verify_pairs(pairs, concepts, representatives, refs, client, progress):
    """Check every original range for each proposed pair; one conflict prevents merging."""
    results = {}
    pending = []
    def base_for(items):
        return {'phase': 'evidence_page', 'candidates': [wire_candidate(c, c['id']) for c, cid in items],
                'ledger': [concept_card(concepts[cid], representatives[cid], refs[cid]) for cid in dict.fromkeys(cid for _, cid in items)],
                'expected_matches': {c['id']: refs[cid] for c, cid in items}}
    groups = []
    for pair in pairs:
        if pending and not fits(client, 'linking_verify', base_for([*pending, pair]), reserve=12000):
            groups.append(pending)
            pending = []
        pending.append(pair)
    if pending:
        groups.append(pending)
    for group in groups:
        base = base_for(group)
        valid = {c['id']: True for c, _ in group}
        latest = {}
        unique = {}
        for c, cid in group:
            for row in [*source_rows(c, c['id']), *source_rows(representatives[cid], refs[cid])]:
                key = (row.get('doc_id'), row['block_id'], row['start'], row['end'], row['text'])
                if key in unique:
                    unique[key]['owners'].append(row['owner'])
                else:
                    unique[key] = {**row, 'owners': [row['owner']]}
        for packet in evidence_packets(client, base, unique.values()):
            check()
            for item in call(client, 'linking_verify', packet, progress):
                cid = next(cid for c, cid in group if c['id'] == item['candidate_id'])
                if (item['ambiguous'] or item['group_id'] != refs[cid] or
                        (item['canonical_name'], item['category']) != (concepts[cid]['name'], concepts[cid]['category'])):
                    valid[item['candidate_id']] = False
                latest[item['candidate_id']] = {**item, 'group_id': cid}
            client.accept()
            progress['evidence_requests'] = progress.get('evidence_requests', 0) + 1
        for c, _ in group:
            results[c['id']] = latest[c['id']] if valid[c['id']] else abstain(c, 'Conflicting or insufficient full-source evidence; reviewer association required.')
    return results


def resolve_group(group, concepts, representatives, client, progress):
    refs = {cid: f'L{i+1}' for i, cid in enumerate(concepts)}
    reverse = {v: k for k, v in refs.items()}
    local = [{**c, 'id': f'C{i+1}'} for i, c in enumerate(group)]
    original = {c['id']: group[i]['id'] for i, c in enumerate(local)}
    uncertain, hits = set(), {c['id']: set() for c in local}
    base = {'phase': 'index_page', 'candidates': [wire_candidate(c, c['id']) for c in local]}
    pages = list(pack_rows(client, 'linking_scan', base, 'ledger', index_fragments(concepts, representatives, refs)))
    progress['index_pages_current'] = len(pages)
    progress['index_pages_current_checked'] = 0
    for page in pages:
        check()
        allowed = {c['id'] for c in page['ledger']}
        for item in call(client, 'linking_scan', page, progress):
            ident, ref = item['candidate_id'], item['group_id']
            if item['ambiguous']:
                uncertain.add(ident)
            elif ref in allowed:
                cid = reverse[ref]
                if (item['canonical_name'], item['category']) != (concepts[cid]['name'], concepts[cid]['category']):
                    uncertain.add(ident)
                else:
                    hits[ident].add(cid)
            elif not ref.startswith('new:'):
                uncertain.add(ident)
        client.accept()
        progress['index_pages_checked'] = progress.get('index_pages_checked', 0) + 1
        progress['index_pages_current_checked'] += 1
    results, pairs, new = {}, [], []
    for c in local:
        if c['id'] in uncertain or len(hits[c['id']]) > 1:
            results[c['id']] = abstain(c, 'Index pages contain conflicting, unknown or uncertain matches; reviewer association required.')
        elif hits[c['id']]:
            pairs.append((c, next(iter(hits[c['id']]))))
        else:
            new.append(c)
    results.update(verify_pairs(pairs, concepts, representatives, refs, client, progress))
    if new:
        payload = {'phase': 'new_groups', 'ledger': [], 'candidates': [wire_candidate(c, c['id']) for c in new]}
        for item in call(client, 'linking_create', payload, progress):
            results[item['candidate_id']] = item
        client.accept()
    publish(progress, client)
    return [{**results[c['id']], 'candidate_id': original[c['id']]} for c in local]


def legacy_payload(group, ledger):
    candidate_refs = {f'C{i+1}': c['id'] for i, c in enumerate(group)}
    ledger_refs = {f'L{i+1}': c['id'] for i, c in enumerate(ledger)}
    reverse = {v: k for k, v in candidate_refs.items()}
    payload = {'ledger': [{**c, 'id': f'L{i+1}'} for i, c in enumerate(ledger)],
               'candidates': [{**{k: v for k, v in c.items() if k not in ('id', 'doc_id', 'block_id', 'start', 'end')},
                               'id': reverse[c['id']]} for c in group]}
    return payload, candidate_refs, ledger_refs


def link_registry(project, candidates, client, run):
    from .workflow import stable_id, batches
    concepts, mentions, ledger, representatives = {}, [], [], {}
    progress = run['linking_progress'] = dict(candidates_total=len(candidates), candidates_completed=0,
        legacy_batches_reused=0, index_pages_checked=0, evidence_requests=0, cache_hits=0,
        _initial_attempts=client.http_attempts)
    legacy_prefix = True
    groups = list(batches(candidates, client.settings.link_batch_size))
    group_index = 0
    while groups:
        group = groups.pop(0)
        check()
        assignments = None
        if legacy_prefix:
            payload, candidate_refs, ledger_refs = legacy_payload(group, ledger)
            response = client.complete('linking', payload, Links, cache_only=True)
            if response is not None:
                assignments = [{**a, 'candidate_id': candidate_refs[a['candidate_id']],
                    'group_id': ledger_refs.get(a['group_id'], a['group_id'])}
                    for a in checked_assignments(response, candidate_refs)]
                progress['legacy_batches_reused'] += 1
                progress['cache_hits'] += 1
            else:
                legacy_prefix = False
        if assignments is None:
            bounded = list(candidate_groups(group, client.settings.link_batch_size, client))
            group, groups = bounded[0], [*bounded[1:], *groups]
            assignments = resolve_group(group, concepts, representatives, client, progress)
        group_map, candidate_map = {}, {c['id']: c for c in group}
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
                item = {**item, 'ambiguous': True, 'reason': 'Model returned an unknown concept reference; kept separate for reviewer association. ' + item['reason']}
                run.setdefault('linking_conflicts', []).append(item['candidate_id'])
            if cid in concepts and (concepts[cid]['category'] != item['category'] or concepts[cid]['name'] != item['canonical_name']):
                cid = stable_id('link-conflict', item['candidate_id'])
                item = {**item, 'ambiguous': True, 'reason': 'Model group ID conflicts with its name/category; kept separate for reviewer association. ' + item['reason']}
                run.setdefault('linking_conflicts', []).append(item['candidate_id'])
            c = candidate_map[item['candidate_id']]
            concepts.setdefault(cid, {'id': cid, 'name': item['canonical_name'], 'category': item['category'],
                'definition': item['definition'], 'aliases': [], 'confirmed': False,
                'evidence': f"{c['role']} {c['page']}: {c['context']}",
                'note': 'Model grouping is uncertain; reviewer association required.' if item['ambiguous'] else 'Model-supported proposal; human evidence review is required.',
                'origin': client.settings.provider})
            representatives.setdefault(cid, c)
            if c['text'] != concepts[cid]['name'] and c['text'] not in concepts[cid]['aliases']:
                concepts[cid]['aliases'].append(c['text'])
            mentions.append({k: c[k] for k in ('id', 'doc_id', 'role', 'page', 'region', 'block_id', 'start', 'end', 'text', 'context', 'evidence_kind')} | {
                'concept_id': cid, 'candidates': [cid], 'status': 'unresolved', 'manual': False,
                'model_link_status': 'ambiguous' if item['ambiguous'] else 'supported', 'model_reason': item['reason'], 'origin': client.settings.provider})
        ledger = [{k: c[k] for k in ('id', 'name', 'category', 'definition', 'aliases', 'evidence')} for c in concepts.values()]
        client.accept()
        progress['candidates_completed'] += len(group)
        publish(progress, client)
        group_index += 1
    progress.pop('_initial_attempts', None)
    project['concepts'], project['mentions'] = list(concepts.values()), mentions
