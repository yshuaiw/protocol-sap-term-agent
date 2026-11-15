from .client import ModelError
from .schemas import Decisions, Interpretation, SemanticAudit, Boundaries
from .workflow import batches
from ..revisions import preview


def review_plan(project, concept_id, mappings, client):
    plan = preview(project, concept_id, mappings)
    if not plan['items']:
        raise ModelError('No indexed occurrences are available for AI review. Check the register before generating a plan.')
    concept = next(c for c in project['concepts'] if c['id'] == concept_id)
    for batch in batches(plan['items']):
        result = client.complete('rename_review', {'concept': concept, 'mappings': mappings, 'mentions': batch}, Decisions)
        rows = {d['mention_id']: d for d in result['decisions']}
        if len(rows) != len(result['decisions']) or set(rows) != {m['id'] for m in batch}:
            raise ModelError('Rename review must return exactly one decision for every occurrence.')
        for item in batch:
            decision = rows[item['id']]
            if decision['evidence'] not in item['context']:
                raise ModelError('Rename review evidence is not present in the occurrence context.')
            item.update(model_decision=decision['decision'], model_reason=decision['reason'],
                        model_evidence=decision['evidence'], semantic_risk=decision['semantic_risk'])
            # Model advice may only narrow the deterministic/human permissions, never expand them.
            if decision['semantic_risk']:
                item.update(proposal='unresolved', reason='Model flagged a possible meaning/design change: ' + decision['reason'])
            elif item['proposal'] == 'update':
                item.update(proposal=decision['decision'], reason=decision['reason'])
            if item.get('evidence_kind') == 'visual_transcription' and not item.get('manual'):
                item.update(proposal='unresolved', reason='Verify this visual transcription individually against its source before approval.')
        client.accept()
    plan['engine'] = 'groq-ai-v1'
    plan['model_calls'] = list(client.records)
    return plan


def interpret_request(project, text, client):
    result = client.complete('interpretation', {'request': text, 'concepts': project['concepts']}, Interpretation)
    concept = next((c for c in project['concepts'] if c['id'] == result['concept_id']), None)
    if not concept or not result['mappings']:
        raise ModelError('The request did not identify one existing concept and its replacement forms. Specify it in the register.')
    forms = {f.casefold() for f in [concept['name'], *concept['aliases']]}
    if any(m['old'].casefold() not in forms for m in result['mappings']):
        raise ModelError('The interpreted request contains an unregistered replacement form.')
    client.accept()
    return result


def audit_export(project, export_id, client):
    export = next((e for e in project['exports'] if e['id'] == export_id), None)
    if not export:
        raise ModelError('Unknown export.')
    blocks = {b['id']: b for d in project['documents'] for b in d['blocks']}
    changed = {i['block_id'] for i in export['verification']['approved_changes']}
    # Use the snapshot that contains this export to avoid reviewing later text as an older export.
    if 'after_blocks' not in export or any(blocks[i]['text'] != export['after_blocks'].get(i) for i in changed):
        raise ModelError('This export is older than current text; restore its snapshot before semantic review.')
    findings, notes = [], []
    for group in batches(sorted(changed), 10):
        payload = {'changes': [{'block_id': bid, 'before': export['before_blocks'][bid], 'after': blocks[bid]['text'],
                                'approved': [i for i in export['verification']['approved_changes'] if i['block_id'] == bid]} for bid in group]}
        result = client.complete('semantic_audit', payload, SemanticAudit)
        for finding in result['findings']:
            if finding['block_id'] not in group or finding['evidence'] not in blocks[finding['block_id']]['text']:
                raise ModelError('Semantic audit returned ungrounded evidence.')
        findings.extend(result['findings'])
        notes.append(result['note'])
        client.accept()
    return {'export_id': export_id, 'findings': findings, 'notes': notes,
            'notice': 'Advisory model review, not independent proof of semantic correctness.', 'model_calls': client.records}


def suggest_boundaries(hints, pages, client):
    result = client.complete('boundaries', {'title_hints': hints, 'unit_count': pages}, Boundaries)
    for item in result['documents']:
        if not 1 <= item['start'] <= item['end'] <= pages or not any(item['evidence'] in h['evidence'] for h in hints):
            raise ModelError('Boundary suggestion is outside the input or lacks exact title-page evidence.')
    client.accept()
    return result
