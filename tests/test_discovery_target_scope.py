import json

import httpx

from backend.ai.client import GroqClient
from backend.ai.config import Settings
from backend.ai.workflow import generate_registry


def test_discovery_cannot_extract_from_duplicated_neighbor_context(tmp_path):
    p = {'id': 'fixture', 'documents': [{'id': 'doc', 'role': 'Protocol', 'blocks': [
        {'id': 'heading', 'page': 1, 'region': 'heading', 'text': 'Treatment assignment'},
        {'id': 'body', 'page': 1, 'region': 'body', 'text': 'Arm A receives study treatment.'},
    ]}], 'concepts': [], 'mentions': []}
    discovery_texts, linking = [], []
    def reply(request):
        payload = json.loads(json.loads(request.content)['messages'][1]['content'])
        if 'chunks' in payload:
            found = []
            for unit in payload['chunks']:
                discovery_texts.append(unit['text'])
                # Reproduce the real failure class: the model copies an adjacent label into the wrong block.
                source = unit.get('following_context') or unit['text']
                if 'Arm A' in source:
                    found.append({'block_id': unit['block_id'], 'term_text': 'Arm A', 'context_quote': 'Arm A receives study treatment.',
                                  'canonical_name': 'Arm A', 'category': 'treatment', 'definition': 'Named group.', 'reason': 'Named in source.'})
                assert 'preceding_context' not in unit and 'following_context' not in unit
            answer = {'mentions': found}
        else:
            linking.extend(payload['candidates'])
            answer = {'assignments': [{'candidate_id': c['id'], 'group_id': 'new:arm-a',
                'canonical_name': 'Arm A', 'category': 'treatment', 'definition': 'Named group.',
                'reason': 'Actual source context supports the group.', 'ambiguous': False} for c in payload['candidates']]}
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(answer)}}]})
    client = GroqClient(Settings(api_key='fixture-key'), transport=httpx.MockTransport(reply), cache_dir=tmp_path)
    generate_registry(p, client, {})
    assert discovery_texts == ['Treatment assignment', 'Arm A receives study treatment.']
    assert len(p['mentions']) == 1 and p['mentions'][0]['block_id'] == 'body'
    assert linking[0]['preceding_context'] == 'Treatment assignment'
