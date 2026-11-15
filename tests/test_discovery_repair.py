import json

import httpx
import pytest

from backend.ai.client import GroqClient, ModelError
from backend.ai.config import Settings
from backend.ai.workflow import generate_registry
from tests.test_discovery_anchors import mention, project


@pytest.mark.parametrize('action', ['corrected', 'out_of_scope', 'unresolved', 'invented_id'])
def test_failed_evidence_gets_one_model_decision_with_source_guards(tmp_path, action):
    text = 'Arm A and Arm B receive treatment.'
    p, stages = project(text), []
    def reply(request):
        payload = json.loads(json.loads(request.content)['messages'][1]['content'])
        if 'rejected' in payload:
            stages.append('repair')
            rejected = payload['rejected']
            assert len(rejected) == 1 and rejected[0]['proposal']['term_text'] == 'Arm'
            replacement = [mention('Arm B', text)] if action == 'corrected' else []
            answer = {'decisions': [{'rejected_id': 'unknown' if action == 'invented_id' else rejected[0]['rejected_id'],
                'action': 'out_of_scope' if action == 'invented_id' else action,
                'mentions': replacement, 'reason': 'Generic Arm alone is not a named group; actual named groups retain their own labels.'}]}
        elif 'chunks' in payload:
            stages.append('discovery')
            answer = {'mentions': [mention('Arm A', text), mention('Arm', text)]}
        else:
            stages.append('linking')
            answer = {'assignments': [{'candidate_id': c['id'], 'group_id': 'new:' + c['id'],
                'canonical_name': c['canonical_name'], 'category': c['category'], 'definition': c['definition'],
                'reason': 'Fixture semantic grouping.', 'ambiguous': False} for c in payload['candidates']]}
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(answer)}}]})
    client = GroqClient(Settings(api_key='fixture-key'), transport=httpx.MockTransport(reply), cache_dir=tmp_path)
    run = {}
    if action in ('unresolved', 'invented_id'):
        with pytest.raises(ModelError, match='unresolved|proposal IDs'):
            generate_registry(p, client, run)
        assert not p['mentions'] and not p['concepts'] and not list(tmp_path.iterdir())
    else:
        generate_registry(p, client, run)
        assert run['status'] == 'completed'
        assert {m['text'] for m in p['mentions']} == ({'Arm A', 'Arm B'} if action == 'corrected' else {'Arm A'})
        assert run['discovery_repair_operations'] == 1
        assert len(run['discovery_exclusions']) == (1 if action == 'out_of_scope' else 0)
    assert stages.count('repair') == 1
