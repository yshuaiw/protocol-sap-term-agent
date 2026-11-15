"""Conservative candidate discovery; equality is evidence to review, not proof of identity."""
import re
import uuid

CATEGORIES = ('treatment', 'visit', 'endpoint', 'label')
PATTERNS = {
    'treatment': r'\b(?:treatment\s+arm\s+(?:[A-Z]\d*|\d+)|arm\s+(?:[A-Z]\d*|\d+)|cohort\s+\d+|dapagliflozin|placebo)\b',
    'visit': r'\b(?:visit\s+\d+(?:[A-Z])?|week\s+\d+|day\s+\d+|screening\s+visit|baseline\s+visit|follow-up\s+visit|end\s+of\s+treatment)\b',
    'endpoint': r'\b(?:primary\s+(?:composite\s+)?endpoint|secondary\s+(?:composite\s+)?endpoint|overall\s+survival|progression-free\s+survival|objective\s+response\s+rate|disease\s+control\s+rate|duration\s+of\s+response)\b',
    'label': r'\b(?:full\s+analysis\s+set|safety\s+analysis\s+set|per[- ]protocol\s+(?:set|population)|response[- ]evaluable\s+set|intention[- ]to[- ]treat|primary\s+analyses\s+censoring\s+date|study\s+end\s+date)\b',
}


def uid():
    return uuid.uuid4().hex


def matches(text, form):
    return re.finditer(r'(?<!\w)' + re.escape(form) + r'(?!\w)', text, re.I)


def build_registry(project):
    concepts = {}
    for doc in project['documents']:
        for block in doc['blocks']:
            for category, pattern in PATTERNS.items():
                for match in re.finditer(pattern, block['text'], re.I):
                    name = match.group()
                    key = re.sub(r'\s+', ' ', name).lower()
                    if key not in concepts:
                        concepts[key] = {'id': uid(), 'name': name, 'category': category,
                                         'aliases': [], 'confirmed': False,
                                         'evidence': f"{doc['role']} p{block['page']}: {block['text']}",
                                         'note': 'Rule candidate. Same spelling may denote different concepts. Confirm evidence before editing.'}
    # Only harvest abbreviations beside in-scope names; don't index every medical acronym.
    for concept in concepts.values():
        for doc in project['documents']:
            for block in doc['blocks']:
                text = block['text']
                for match in matches(text, concept['name']):
                    tail = text[match.end():match.end() + 24]
                    abbr = re.match(r'\s*\(([A-Z][A-Z0-9-]{1,12})\)', tail)
                    if abbr and abbr[1] not in concept['aliases']:
                        concept['aliases'].append(abbr[1])
                abbr = re.match(r'^([A-Z][A-Z0-9-]{1,12})\s+' + re.escape(concept['name']) + r'\b', text, re.I)
                if abbr and abbr[1].isupper() and abbr[1] not in concept['aliases']:
                    concept['aliases'].append(abbr[1])
    project['concepts'] = list(concepts.values())
    rescan(project)


def rescan(project):
    previous = {(m['block_id'], m['start'], m['end'], m['text']): m for m in project['mentions']}
    occurrences = {}
    for doc in project['documents']:
        for block in doc['blocks']:
            for concept in project['concepts']:
                spans = []
                for form in dict.fromkeys([concept['name'], *concept['aliases']]):
                    for match in matches(block['text'], form):
                        spans.append(match)
                accepted = []
                for match in sorted(spans, key=lambda m: (-(m.end() - m.start()), m.start())):
                    # A longer registered name wins over its own nested alias.
                    if any(match.start() < end and match.end() > start for start, end in accepted):
                        continue
                    accepted.append((match.start(), match.end()))
                    key = (block['id'], match.start(), match.end(), match.group())
                    item = occurrences.setdefault(key, {'id': uid(), 'doc_id': doc['id'], 'role': doc['role'],
                        'page': block['page'], 'region': block['region'], 'block_id': block['id'],
                        'start': match.start(), 'end': match.end(), 'text': match.group(),
                        'context': block['text'], 'candidates': []})
                    if concept['id'] not in item['candidates']:
                        item['candidates'].append(concept['id'])
    result = []
    confirmed = {c['id']: c['confirmed'] for c in project['concepts']}
    for key, item in occurrences.items():
        old = previous.get(key)
        if old and old.get('manual') and old['concept_id'] in confirmed:
            item.update({k: old[k] for k in ('id', 'concept_id', 'status', 'manual')})
        else:
            unique = len(item['candidates']) == 1
            cid = item['candidates'][0] if unique else None
            item.update(concept_id=cid, status='confirmed' if unique and confirmed[cid] else 'unresolved', manual=False)
        result.append(item)
    project['mentions'] = result


def reindex_after_edits(project, plan, approved_ids):
    """Keep reviewed links while shifting offsets and adding approved new naming forms."""
    from collections import defaultdict
    changes = defaultdict(list)
    approved = [i for i in plan['items'] if i['id'] in approved_ids]
    for item in approved:
        changes[item['block_id']].append(item)
    concept = next(c for c in project['concepts'] if c['id'] == plan['concept_id'])
    old_forms = [concept['name'], *concept['aliases']]
    mappings = {old.casefold(): new for old, new in plan['mappings'].items()}
    if concept['name'].casefold() in mappings:
        concept['name'] = mappings[concept['name'].casefold()]
    concept['aliases'] = list(dict.fromkeys([*concept['aliases'], *old_forms, *[i['new'] for i in approved]]))
    concept['aliases'] = [a for a in concept['aliases'] if a != concept['name']]
    blocks = {b['id']: b['text'] for d in project['documents'] for b in d['blocks']}
    retained = []
    for mention in project['mentions']:
        edits = changes[mention['block_id']]
        overlap = [i for i in edits if i['start'] < mention['end'] and i['end'] > mention['start']]
        shift = sum(len(i['new']) - len(i['text']) for i in edits if i['end'] <= mention['start'])
        if overlap:
            if len(overlap) != 1 or overlap[0]['id'] != mention['id']:
                continue
            mention.update(text=overlap[0]['new'], status='confirmed', manual=True)
            mention['end'] = mention['start'] + len(mention['text'])
        mention['start'] += shift
        mention['end'] += shift
        mention['context'] = blocks[mention['block_id']]
        retained.append(mention)
    project['mentions'] = retained
    rescan(project)
