import copy
import json

import httpx
import pytest

from backend.ai.client import GroqClient, ModelError
from backend.ai.config import Settings
from backend.ai.workflow import generate_registry


def project(text):
    return {'id': 'fixture', 'documents': [{'id': 'doc', 'role': 'Protocol', 'blocks': [
        {'id': 'block', 'page': 1, 'region': 'table', 'text': text}]}], 'concepts': [], 'mentions': []}


def mention(text, evidence, block_id='block'):
    return {'block_id': block_id, 'text': text, 'evidence': evidence, 'canonical_name': text,
            'category': 'treatment', 'definition': 'Fixture group.', 'reason': 'Quoted in the document.'}


def client_for(mentions, tmp_path, chunk_chars=7000):
    def reply(request):
        payload = json.loads(json.loads(request.content)['messages'][1]['content'])
        if 'chunks' in payload:
            answer = {'mentions': mentions(payload['chunks']) if callable(mentions) else mentions}
        else:
            answer = {'assignments': [{'candidate_id': c['id'], 'group_id': 'new:' + c['id'],
                'canonical_name': c['canonical_name'], 'category': c['category'], 'definition': c['definition'],
                'reason': 'Fixture semantic decision.', 'ambiguous': False} for c in payload['candidates']]}
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(answer)}}]})
    return GroqClient(Settings(api_key='fixture-key', chunk_chars=chunk_chars),
                      transport=httpx.MockTransport(reply), cache_dir=tmp_path)


def test_program_locates_unicode_quote_without_model_character_counts(tmp_path):
    text = '🙂治疗组\nArm A receives 10 mg.'
    p = project(text)
    generate_registry(p, client_for([mention('Arm A', 'Arm A receives 10 mg.')], tmp_path), {})
    found = p['mentions'][0]
    assert (found['start'], found['end']) == (text.index('Arm A'), text.index('Arm A') + 5)
    assert p['documents'][0]['blocks'][0]['text'] == text


def test_context_quotes_distinguish_repeated_terms_and_model_concepts(tmp_path):
    text = 'Arm A receives 10 mg. Historical Arm A received placebo.'
    p = project(text)
    generate_registry(p, client_for([mention('Arm A', 'Arm A receives 10 mg.'),
        mention('Arm A', 'Historical Arm A received placebo.')], tmp_path), {})
    assert [m['start'] for m in p['mentions']] == [0, text.rindex('Arm A')]
    assert len(p['concepts']) == 2
    assert p['mentions'][0]['concept_id'] != p['mentions'][1]['concept_id']


@pytest.mark.parametrize(('text', 'proposal', 'error'), [
    ('Arm A then Arm A', mention('Arm A', 'Arm A'), 'ambiguous'),
    ('Arm A then Arm A', mention('Arm A', 'Arm A then Arm A'), 'ambiguous'),
    ('Arm A receives treatment.', mention('Arm C', 'Arm A receives treatment.'), 'evidence'),
    ('Arm A receives treatment.', mention('Arm-A', 'Arm-A receives treatment.'), 'evidence'),
    ('Arm A receives treatment.', mention('Arm A', 'Arm A', 'unknown'), 'unknown block'),
])
def test_invalid_or_ambiguous_quotes_cannot_replace_register(tmp_path, text, proposal, error):
    p = project(text)
    original = copy.deepcopy(p)
    with pytest.raises(ModelError, match=error):
        generate_registry(p, client_for([proposal], tmp_path), {})
    assert p == original and not list(tmp_path.iterdir())


def test_overlapping_long_chunks_produce_one_correct_global_anchor(tmp_path):
    text = 'x' * 750 + 'Arm A receives treatment.' + 'y' * 900
    p = project(text)
    def proposals(units):
        return [mention('Arm A', 'Arm A receives treatment.') for u in units
                if 'Arm A receives treatment.' in u['text']]
    generate_registry(p, client_for(proposals, tmp_path, chunk_chars=1000), {})
    assert len(p['mentions']) == 1 and p['mentions'][0]['start'] == 750


def test_evidence_from_another_chunk_is_rejected(tmp_path):
    p = project('x' * 1100 + 'Arm A receives treatment.')
    with pytest.raises(ModelError, match='evidence'):
        generate_registry(p, client_for([mention('Arm A', 'Arm A receives treatment.')], tmp_path, chunk_chars=1000), {})
    assert not p['mentions'] and not list(tmp_path.iterdir())
