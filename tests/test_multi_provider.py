import json

import httpx
import pytest

from backend.ai.client import ModelClient, ModelError
from backend.ai.config import Settings
from backend.ai.providers import PROVIDERS
from backend.ai.schemas import Extraction, VisionResult


def answer(provider, content, complete=True):
    if provider == 'google':
        return {'candidates': [{'finishReason': 'STOP' if complete else 'MAX_TOKENS',
                'content': {'parts': [{'text': json.dumps(content)}]}}], 'usageMetadata': {'totalTokenCount': 12}}
    if provider == 'anthropic':
        return {'stop_reason': 'end_turn' if complete else 'max_tokens', 'content': [{'type': 'text', 'text': json.dumps(content)}],
                'usage': {'input_tokens': 7, 'output_tokens': 5}}
    return {'choices': [{'finish_reason': 'stop' if complete else 'length', 'message': {'content': json.dumps(content)}}],
            'usage': {'total_tokens': 12}}


@pytest.mark.parametrize('provider', PROVIDERS)
def test_endpoint_auth_schema_and_success(provider):
    def reply(request):
        assert str(request.url).startswith(PROVIDERS[provider]['base'] + '/')
        assert 'fixture-private-key' not in str(request.url)
        body = json.loads(request.content)
        if provider == 'google':
            assert request.headers['x-goog-api-key'] == 'fixture-private-key'
            assert request.url.path.endswith('/models/test-model:generateContent')
            assert body['generationConfig']['responseMimeType'] == 'application/json'
        elif provider == 'anthropic':
            assert request.headers['x-api-key'] == 'fixture-private-key'
            assert request.url.path == '/v1/messages'
            assert body['output_config']['format']['type'] == 'json_schema'
        else:
            assert request.headers['Authorization'] == 'Bearer fixture-private-key'
            assert request.url.path.endswith('/chat/completions')
            assert body['response_format']['type'] in ('json_object', 'json_schema')
            assert ('max_completion_tokens' in body) == (provider in ('groq', 'openai'))
        return httpx.Response(200, json=answer(provider, {'mentions': []}))
    client = ModelClient(Settings(provider=provider, api_key='fixture-private-key', model='test-model'), transport=httpx.MockTransport(reply))
    assert client.complete('discovery', {}, Extraction) == {'mentions': []}
    assert client.records[0]['provider'] == provider and client.records[0]['simulation']
    assert 'fixture-private-key' not in json.dumps(client.records)


@pytest.mark.parametrize('provider', PROVIDERS)
@pytest.mark.parametrize('failure', ['auth', 'quota', 'truncated', 'malformed', 'network', 'secret'])
def test_safe_failure_never_calls_other_provider(provider, failure):
    requests = []
    def reply(request):
        requests.append(request)
        if failure == 'network':
            raise httpx.ReadTimeout('fixture-private-key', request=request)
        if failure in ('auth', 'quota'):
            return httpx.Response(401 if failure == 'auth' else 402, json={'error': {'message': 'fixture-private-key'}})
        content = {'mentions': []} if failure == 'truncated' else {'wrong': 'fixture-private-key'} if failure == 'malformed' else {
            'mentions': [{'block_id': 'b', 'term_text': 'fixture-private-key', 'context_quote': 'fixture-private-key',
                          'canonical_name': 'fixture-private-key', 'category': 'label', 'definition': '', 'reason': 'x'}]}
        return httpx.Response(200, json=answer(provider, content, complete=failure != 'truncated'))
    client = ModelClient(Settings(provider=provider, api_key='fixture-private-key', model='test-model'), transport=httpx.MockTransport(reply))
    with pytest.raises(ModelError) as exc:
        client.complete('discovery', {}, Extraction)
    assert 'fixture-private-key' not in str(exc.value)
    assert len(requests) == 1 and not client.records


@pytest.mark.parametrize('provider', ['google', 'openai', 'anthropic', 'groq', 'qwen', 'kimi'])
@pytest.mark.parametrize('media', ['image', 'pdf'])
def test_visual_provider_is_independent_and_media_encoded(provider, media):
    supported = media == 'image' or PROVIDERS[provider]['native_pdf']
    requests = []
    def reply(request):
        requests.append(request)
        assert str(request.url).startswith(PROVIDERS[provider]['base'])
        auth = request.headers.get('x-goog-api-key', request.headers.get('x-api-key', request.headers.get('authorization', '')))
        assert auth in ('visual-private-key', 'Bearer visual-private-key')
        body = json.loads(request.content)
        serialized = json.dumps(body)
        assert 'YWJj' in serialized
        if media == 'pdf':
            assert ('document' if provider == 'anthropic' else 'application/pdf') in serialized
        return httpx.Response(200, json=answer(provider, {'segments': [], 'limitations': []}))
    client = ModelClient(Settings(api_key='text-private-key', vision_api_key='visual-private-key', vision_provider=provider,
                                 vision_model='visual-model'), transport=httpx.MockTransport(reply))
    kwargs = {'images': ['data:image/png;base64,YWJj']} if media == 'image' else {'pdf': 'data:application/pdf;base64,YWJj'}
    if supported:
        assert client.complete('vision', {}, VisionResult, **kwargs) == {'segments': [], 'limitations': []}
        assert client.records[0]['provider'] == provider
    else:
        with pytest.raises(ModelError, match='native PDF'):
            client.complete('vision', {}, VisionResult, **kwargs)
        assert not requests
