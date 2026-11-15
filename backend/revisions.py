import re
from .registry import matches, uid


def preview(project, concept_id, mappings):
    concept = next((c for c in project['concepts'] if c['id'] == concept_id), None)
    if not concept:
        raise ValueError('Unknown concept.')
    allowed = {f.casefold() for f in [concept['name'], *concept['aliases']]}
    normalized = {}
    for old, new in mappings.items():
        if old.casefold() not in allowed or not new.strip() or len(new) > 200 or any(c in new for c in '\r\n\t'):
            raise ValueError('Mappings must use registered forms and nonempty replacements of at most 200 characters.')
        if old.casefold() in normalized:
            raise ValueError('Duplicate case-insensitive mapping.')
        normalized[old.casefold()] = new.strip()
    if not normalized:
        raise ValueError('Provide at least one replacement mapping.')
    items = []
    blocks = {b['id']: b for d in project['documents'] for b in d['blocks']}
    for mention in project['mentions']:
        if concept_id not in mention['candidates'] and mention['concept_id'] != concept_id:
            continue
        new = normalized.get(mention['text'].casefold())
        status, reason = 'update', 'Confirmed concept link and explicit replacement mapping.'
        if mention['status'] == 'preserve' and mention['concept_id'] == concept_id:
            status, reason = 'preserve', 'Reviewer explicitly chose to preserve this occurrence.'
        elif mention['concept_id'] != concept_id or mention['status'] != 'confirmed':
            status, reason = 'unresolved', 'Concept association has not been confirmed, or this spelling is ambiguous.'
        elif not new or new == mention['text']:
            status, reason = 'preserve', 'No replacement requested for this form, or it already has the requested spelling.'
        elif any(m.start() <= mention['start'] and m.end() >= mention['end']
                 for m in matches(mention['context'], new)):
            status, reason = 'preserve', 'This occurrence is already within the requested replacement form.'
        elif re.search(r'\b(previous|formerly|historical|original|version history|amendment history)\b', mention['context'], re.I):
            status, reason = 'preserve', 'Possible historical reference; preserved for separate review.'
        elif re.findall(r'\d+(?:\.\d+)?', mention['text']) != re.findall(r'\d+(?:\.\d+)?', new):
            status, reason = 'unresolved', 'Numeric label or design value changes need separate review; naming-only execution is blocked.'
        if not blocks[mention['block_id']].get('editable', True):
            status, reason = 'unresolved', 'This source field, tracked revision or embedded image requires manual source editing.'
        items.append({**mention, 'new': new or mention['text'], 'proposal': status, 'reason': reason})
    return {'id': uid(), 'base_revision': project['revision'], 'concept_id': concept_id,
            'mappings': mappings, 'items': items, 'applied': False}


def patch_blocks(project, plan, approved_ids):
    if plan['applied']:
        raise ValueError('This plan has already been applied.')
    if plan['base_revision'] != project['revision']:
        raise ValueError('Stale preview. Regenerate after project or registry changes.')
    items = {i['id']: i for i in plan['items']}
    if len(approved_ids) != len(set(approved_ids)) or not set(approved_ids) <= set(items):
        raise ValueError('Unknown or duplicate approval.')
    if not approved_ids:
        raise ValueError('Approve at least one update before applying.')
    approved = [items[i] for i in approved_ids]
    if any(i['proposal'] != 'update' for i in approved):
        raise ValueError('Preserved and unresolved occurrences cannot be approved by this naming-only plan.')
    blocks = {b['id']: b for d in project['documents'] for b in d['blocks']}
    grouped = {}
    for item in approved:
        block = blocks[item['block_id']]
        if not block.get('editable', True):
            raise ValueError('This source region is not editable by an approved text patch.')
        if block['text'][item['start']:item['end']] != item['text']:
            raise ValueError('Source anchor no longer matches the preview.')
        grouped.setdefault(block['id'], []).append(item)
    log = []
    for bid, changes in grouped.items():
        changes.sort(key=lambda i: i['start'])
        if any(a['end'] > b['start'] for a, b in zip(changes, changes[1:])):
            raise ValueError('Overlapping replacements require a new, nonoverlapping plan.')
        before = blocks[bid]['text']
        after = before
        for item in reversed(changes):
            after = after[:item['start']] + item['new'] + after[item['end']:]
            log.append({'mention_id': item['id'], 'block_id': bid, 'page': item['page'], 'role': item['role'],
                        'region': item['region'], 'old': item['text'], 'new': item['new'], 'start': item['start'],
                        'reason': item['reason']})
        blocks[bid]['text'] = after
    plan['applied'] = True
    plan['approved_ids'] = approved_ids
    return log
