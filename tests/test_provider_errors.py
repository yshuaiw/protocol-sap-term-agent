import json

import httpx
import pytest

from backend.ai.client import GroqClient, ModelError
from backend.ai.config import Settings
from backend.ai.schemas import Extraction


@pytest.mark.parametrize(('error', 'expected'), [
    ({'code': 'invalid_json_schema', 'type': 'invalid_request_error',
      'message': 'Schema keyword maxLength is not supported.'}, ['schema', 'maxLength']),
    ({'code': 'json_validate_failed', 'message': 'Generated JSON does not match the expected schema.'},
     ['json_validate_failed', 'output']),
    ({'message': 'The model does not support image input.'}, ['image input']),
    ({'code': 'model_decommissioned', 'message': 'This model is no longer supported.'}, ['model_decommissioned']),
])
def test_provider_rejection_identifies_stage_and_safe_cause(error, expected):
    calls = []
    def reject(request):
        calls.append(request)
        return httpx.Response(400, json={'error': {**error, 'failed_generation': 'PRIVATE DOCUMENT'}})
    client = GroqClient(Settings(api_key='fixture-private-key'), transport=httpx.MockTransport(reject))
    with pytest.raises(ModelError) as result:
        client.complete('discovery', {}, Extraction)
    message = str(result.value)
    assert all(value in message for value in ['HTTP 400', 'discovery', 'openai/gpt-oss-20b', *expected])
    assert 'PRIVATE DOCUMENT' not in message
    assert 'No rule fallback' in message
    assert len(calls) == (2 if error.get('code') == 'json_validate_failed' else 1)
    assert not client.records


def test_untrusted_provider_content_never_reaches_error_or_cache(tmp_path):
    private = 'fixture-private-key'
    transport = httpx.MockTransport(lambda request: httpx.Response(400, json={'error': {
        'message': f'Unknown rejection. Bearer {private}. PRIVATE DOCUMENT',
        'code': private, 'type': 'PRIVATE DOCUMENT', 'failed_generation': 'PRIVATE DOCUMENT'}}))
    client = GroqClient(Settings(api_key=private), transport=transport, cache_dir=tmp_path)
    with pytest.raises(ModelError) as result:
        client.complete('discovery', {}, Extraction)
    assert private not in str(result.value) and 'PRIVATE DOCUMENT' not in str(result.value)
    client.accept()
    assert not list(tmp_path.iterdir())


def test_schema_rejection_recovers_with_validated_model_json(tmp_path):
    requests = []
    def reply(request):
        requests.append(json.loads(request.content))
        if len(requests) == 1:
            return httpx.Response(400, json={'error': {'code': 'json_validate_failed',
                'failed_generation': 'PRIVATE INVALID OUTPUT'}})
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop',
            'message': {'content': '{"mentions": []}'}}]})
    client = GroqClient(Settings(api_key='fixture-key'), transport=httpx.MockTransport(reply), cache_dir=tmp_path)
    assert client.complete('discovery', {'chunks': []}, Extraction) == {'mentions': []}
    assert [r['response_format']['type'] for r in requests] == ['json_schema', 'json_object']
    assert requests[0]['messages'] == requests[1]['messages']
    assert requests[0]['model'] == requests[1]['model'] == 'openai/gpt-oss-20b'
    assert 'PRIVATE INVALID OUTPUT' not in json.dumps(requests)
    assert client.records[0]['format_recovery'] is True
    assert client.records[0]['request_attempts'] == 2
    assert not list(tmp_path.iterdir())
    client.accept()
    assert len(list(tmp_path.iterdir())) == 1


@pytest.mark.parametrize('content,finish', [('{"mentions": [], "extra": true}', 'stop'),
                                         ('{"mentions": [', 'length')])
def test_recovery_rejects_invalid_or_truncated_output_without_cache(tmp_path, content, finish):
    requests = []
    def reply(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(400, json={'error': {'code': 'json_validate_failed'}})
        return httpx.Response(200, json={'choices': [{'finish_reason': finish, 'message': {'content': content}}]})
    client = GroqClient(Settings(api_key='fixture-key'), transport=httpx.MockTransport(reply), cache_dir=tmp_path)
    with pytest.raises(ModelError, match='truncated' if finish == 'length' else 'schema validation'):
        client.complete('discovery', {}, Extraction)
    client.accept()
    assert len(requests) == 2 and not client.records and not list(tmp_path.iterdir())


def test_json_object_rejection_is_not_retried_indefinitely():
    requests = []
    def reply(request):
        requests.append(request)
        return httpx.Response(400, json={'error': {'code': 'json_validate_failed'}})
    client = GroqClient(Settings(api_key='fixture-key', model='other-text-model'), transport=httpx.MockTransport(reply))
    with pytest.raises(ModelError, match='json_validate_failed'):
        client.complete('discovery', {}, Extraction)
    assert len(requests) == 1


@pytest.mark.parametrize('invalid_evidence', [False, True])
def test_recovery_still_requires_exact_document_evidence(tmp_path, invalid_evidence):
    from tests.test_ai_offline import ScriptedGroq, word_file
    from backend.docx_input import parse_docx
    from backend.ai.workflow import generate_registry
    scripted = ScriptedGroq(invalid=invalid_evidence)
    requests = []
    def reply(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(400, json={'error': {'code': 'json_validate_failed'}})
        return scripted(request)
    project = {'id': 'fixture-project', 'documents': [parse_docx(word_file(), 'Protocol', 1, 1, 'p.docx')],
               'concepts': [], 'mentions': []}
    client = GroqClient(Settings(api_key='fixture-key'), transport=httpx.MockTransport(reply), cache_dir=tmp_path)
    if invalid_evidence:
        with pytest.raises(ModelError, match='evidence'):
            generate_registry(project, client, {})
        assert not project['concepts'] and not project['mentions'] and not list(tmp_path.iterdir())
    else:
        generate_registry(project, client, {})
        assert project['mentions'] and len(project['concepts']) == 1
        assert all(m['text'] == 'Arm A' for m in project['mentions'])
        assert {r['stage'] for r in client.records} == {'discovery', 'linking_create'}
        assert client.records[0]['format_recovery'] is True


def test_transient_and_format_recovery_have_separate_bounded_attempts(monkeypatch):
    monkeypatch.setattr('backend.ai.client.time.sleep', lambda seconds: None)
    requests = []
    def reply(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(503)
        return httpx.Response(400, json={'error': {'code': 'json_validate_failed'}})
    client = GroqClient(Settings(api_key='fixture-key'), transport=httpx.MockTransport(reply))
    with pytest.raises(ModelError, match='recovery was attempted once'):
        client.complete('discovery', {}, Extraction)
    assert len(requests) == 3
