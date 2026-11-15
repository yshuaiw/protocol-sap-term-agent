import json

import httpx

from backend.ai.client import GroqClient
from backend.ai.config import Settings
from backend.ai.workflow import generate_registry
from tests.test_discovery_anchors import mention, project


def test_conflicting_model_group_metadata_is_separate_and_unresolved():
    text = 'Arm A and Arm B receive treatment.'
    p, run = project(text), {}
    def reply(request):
        payload = json.loads(json.loads(request.content)['messages'][1]['content'])
        if 'chunks' in payload:
            answer = {'mentions': [mention('Arm A', text), mention('Arm B', text)]}
        else:
            answer = {'assignments': [{'candidate_id': c['id'], 'group_id': 'new:conflicting-group',
                'canonical_name': c['text'], 'category': 'treatment', 'definition': 'Fixture named group.',
                'reason': 'Deliberately inconsistent fixture grouping.', 'ambiguous': False} for c in payload['candidates']]}
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(answer)}}]})
    client = GroqClient(Settings(api_key='fixture-key'), transport=httpx.MockTransport(reply))
    generate_registry(p, client, run)
    assert len(p['concepts']) == len(p['mentions']) == 2
    assert p['mentions'][0]['concept_id'] != p['mentions'][1]['concept_id']
    assert p['mentions'][1]['status'] == 'unresolved' and p['mentions'][1]['model_link_status'] == 'ambiguous'
    assert len(run['linking_conflicts']) == 1


def test_short_refs_map_aliases_to_an_existing_concept_across_batches():
    text = 'Experimental group (Arm A) receives treatment.'
    p = project(text)
    def reply(request):
        payload = json.loads(json.loads(request.content)['messages'][1]['content'])
        if 'chunks' in payload:
            answer = {'mentions': [mention('Experimental group', text), mention('Arm A', text)]}
        else:
            assert payload['candidates'][0]['id'] == 'C1'
            group = payload['ledger'][0]['id'] if payload['ledger'] else 'new:experimental'
            if payload['ledger']:
                assert group == 'L1'
            answer = {'assignments': [{'candidate_id': 'C1', 'group_id': group,
                'canonical_name': 'Experimental group', 'category': 'treatment', 'definition': 'Named group.',
                'reason': 'Parenthetical alias in source.', 'ambiguous': False}]}
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(answer)}}]})
    client = GroqClient(Settings(api_key='fixture-key', link_batch_size=1), transport=httpx.MockTransport(reply))
    generate_registry(p, client, {})
    assert len(p['concepts']) == 1 and p['concepts'][0]['aliases'] == ['Arm A']
    assert len(p['mentions']) == 2 and len({m['concept_id'] for m in p['mentions']}) == 1


def test_unknown_concept_reference_cannot_merge_distinct_occurrences():
    from backend.registry import rescan
    text = 'Arm A and Arm B receive treatment.'
    p, run = project(text), {}
    def reply(request):
        payload = json.loads(json.loads(request.content)['messages'][1]['content'])
        if 'chunks' in payload:
            answer = {'mentions': [mention('Arm A', text), mention('Arm B', text)]}
        else:
            answer = {'assignments': [{'candidate_id': c['id'], 'group_id': 'unknown-ledger-reference',
                'canonical_name': c['text'], 'category': 'treatment', 'definition': 'Named group.',
                'reason': 'Unknown fixture reference.', 'ambiguous': False} for c in payload['candidates']]}
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(answer)}}]})
    client = GroqClient(Settings(api_key='fixture-key'), transport=httpx.MockTransport(reply))
    generate_registry(p, client, run)
    assert len(p['concepts']) == len(p['mentions']) == len(run['linking_conflicts']) == 2
    for concept in p['concepts']:
        concept['confirmed'] = True
    rescan(p)
    assert all(m['model_link_status'] == 'ambiguous' and m['status'] == 'unresolved' for m in p['mentions'])
