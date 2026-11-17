import json

import httpx
import pytest

from backend.ai.client import ModelClient, ModelError
from backend.ai.config import Settings
from backend.ai.schemas import Links


def candidate(text='Alias Z', context=None, ident='candidate'):
    context = context or text + ' is a treatment group.'
    return dict(id=ident, text=text, canonical_name=text, category='treatment', definition='A named treatment group.',
                reason='Source label.', evidence=text, context=context, start=context.index(text),
                end=context.index(text) + len(text), role='Protocol', page=1, region='body',
                doc_id='doc', block_id=ident, evidence_kind='native_text', preceding_context='', following_context='')


def ledger(count=240):
    concepts, representatives = {}, {}
    for i in range(count):
        cid = 'concept-' + str(i)
        name = 'Target group' if i == count - 1 else 'Existing group ' + str(i)
        c = candidate(name, ident=cid)
        concepts[cid] = dict(id=cid, name=name, category='treatment', definition='Description. ' * 70,
                             aliases=['Alias Z'] if i == count - 1 else ['Alias ' + str(i)], evidence=c['context'])
        representatives[cid] = c
    return concepts, representatives


def client_for(callback, tmp_path=None):
    def reply(request):
        body = json.loads(request.content)
        payload = json.loads(body['messages'][1]['content'])
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(callback(payload))}}]})
    return ModelClient(Settings(api_key='fixture-key'), httpx.MockTransport(reply), tmp_path)


def assignment(c, ref='new:none', name='Alias Z', ambiguous=False):
    return dict(candidate_id=c['id'], group_id=ref, canonical_name=name, category='treatment',
                definition='Fixture group.', reason='Fixture semantic decision.', ambiguous=ambiguous)


def test_large_ledger_checks_every_page_and_finds_late_alias():
    from backend.ai.linking import resolve_group
    from backend.ai.linking_context import request_size, INPUT_BUDGET
    concepts, reps = ledger()
    seen, sizes = set(), []
    client = None
    def reply(p):
        stage = {'index_page': 'linking_scan', 'evidence_page': 'linking_verify', 'new_groups': 'linking_create'}[p['phase']]
        sizes.append(request_size(client, stage, p))
        if p['phase'] == 'index_page':
            seen.update(x['id'] for x in p['ledger'])
        target = next((x for x in p['ledger'] if x['name'] == 'Target group'), None)
        return {'assignments': [assignment(c, target['id'] if target else 'new:none', 'Target group' if target else 'Alias Z') for c in p['candidates']]}
    client = client_for(reply)
    result = resolve_group([candidate()], concepts, reps, client, {})
    assert len(seen) == len(concepts) and len(sizes) > 2
    assert max(sizes) <= INPUT_BUDGET
    assert result[0]['group_id'] == 'concept-239' and not result[0]['ambiguous']


def test_long_evidence_tail_conflict_cannot_be_ignored():
    from backend.ai.linking import resolve_group
    concepts, reps = ledger(1)
    reps['concept-0']['context'] += ' x' * 60000 + ' DIFFERENT MEANING'
    seen_ranges = []
    def reply(p):
        if p['phase'] == 'evidence_page':
            seen_ranges.extend(r for r in p['source_ranges'] if r['owner'].startswith('L'))
        conflict = any('DIFFERENT MEANING' in r['text'] for r in p.get('source_ranges', []))
        return {'assignments': [assignment(c, p['ledger'][0]['id'], 'Target group', conflict) for c in p['candidates']]}
    result = resolve_group([candidate()], concepts, reps, client_for(reply), {})
    assert result[0]['ambiguous'] and result[0]['group_id'].startswith('new:')
    ordered = sorted(seen_ranges, key=lambda r: r['start'])
    end = 0
    for row in ordered:
        assert row['start'] <= end
        assert row['text'] == reps['concept-0']['context'][row['start']:row['end']]
        end = max(end, row['end'])
    assert end == len(reps['concept-0']['context'])


def test_new_group_waits_for_all_index_pages():
    from backend.ai.linking import resolve_group
    concepts, reps = ledger()
    seen = set()
    def reply(p):
        if p['phase'] == 'index_page':
            seen.update(x['id'] for x in p['ledger'])
        else:
            assert len(seen) == len(concepts)
        return {'assignments': [assignment(c, 'new:none' if p['phase'] == 'index_page' else 'new:independent') for c in p['candidates']]}
    result = resolve_group([candidate()], concepts, reps, client_for(reply), {})
    assert result[0]['group_id'] == 'new:independent'


def test_page_id_omission_is_rejected_without_accepted_cache(tmp_path):
    from backend.ai.linking import resolve_group
    concepts, reps = ledger(1)
    client = client_for(lambda p: {'assignments': []}, tmp_path)
    with pytest.raises(ModelError, match='candidate IDs'):
        resolve_group([candidate()], concepts, reps, client, {})
    assert not list(tmp_path.glob('*.json'))


def test_cache_only_lookup_never_calls_provider(tmp_path):
    calls = []
    client = client_for(lambda p: calls.append(p) or {'assignments': []}, tmp_path)
    assert client.complete('linking', {'ledger': [], 'candidates': []}, Links, cache_only=True) is None
    assert client.complete('linking', {'oversized': 'x' * 100001}, Links, cache_only=True) is None
    assert not calls and client.http_attempts == 0


def test_matches_on_different_index_pages_stay_separate():
    from backend.ai.linking import resolve_group
    concepts, reps = ledger()
    concepts['concept-0']['name'] = 'Target group'
    def reply(p):
        target = next((x for x in p['ledger'] if x['name'] == 'Target group'), None)
        assert p['phase'] == 'index_page', 'Conflicting index matches must not be silently resolved'
        return {'assignments': [assignment(c, target['id'] if target else 'new:none', 'Target group') for c in p['candidates']]}
    result = resolve_group([candidate()], concepts, reps, client_for(reply), {})
    assert result[0]['ambiguous'] and result[0]['group_id'].startswith('new:')


def test_one_concept_many_aliases_are_all_indexed():
    from backend.ai.linking import resolve_group
    concepts, reps = ledger(1)
    aliases = ['Alias ' + str(i) + 'x' * 100 for i in range(1800)] + ['Alias Z']
    concepts['concept-0']['aliases'] = aliases
    seen = []
    def reply(p):
        if p['phase'] == 'index_page':
            seen.extend(a for c in p['ledger'] for a in c['aliases'])
        target = next((x for x in p['ledger'] if p['phase'] != 'index_page' or 'Alias Z' in x['aliases']), None)
        return {'assignments': [assignment(c, target['id'] if target else 'new:none', 'Target group') for c in p['candidates']]}
    result = resolve_group([candidate()], concepts, reps, client_for(reply), {})
    assert seen == aliases and result[0]['group_id'] == 'concept-0'


def test_legacy_link_batch_replays_exactly_without_new_calls(tmp_path):
    from backend.ai.linking import legacy_payload, link_registry
    group = [candidate()]
    payload, _, _ = legacy_payload(group, [])
    seed = client_for(lambda p: {'assignments': [assignment(c, 'new:alias') for c in p['candidates']]}, tmp_path)
    seed.complete('linking', payload, Links)
    seed.accept()
    def deny(p):
        raise AssertionError('A legacy cache hit must not call a new linking stage')
    replay = client_for(deny, tmp_path)
    p, run = {'id': 'project'}, {}
    link_registry(p, group, replay, run)
    assert run['linking_progress']['legacy_batches_reused'] == 1
    assert replay.http_attempts == 0 and len(p['mentions']) == 1


@pytest.mark.parametrize('provider', ['groq', 'google', 'openai', 'anthropic', 'deepseek', 'qwen', 'kimi'])
def test_request_size_matches_complete_provider_envelope(provider):
    from backend.ai.linking_context import request_size
    from tests.test_multi_provider import answer
    sent = []
    def reply(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json=answer(provider, {'assignments': []}))
    client = ModelClient(Settings(api_key='fixture-key', provider=provider), httpx.MockTransport(reply))
    payload = {'phase': 'new_groups', 'ledger': [], 'candidates': [{'id': 'C1', 'text': '中文😀'}]}
    stage = 'linking_create'
    predicted = request_size(client, stage, payload)
    client.complete(stage, payload, Links)
    assert len(sent) == 1 and client.http_attempts == 1
    assert predicted == len(json.dumps(sent[0], ensure_ascii=False))
