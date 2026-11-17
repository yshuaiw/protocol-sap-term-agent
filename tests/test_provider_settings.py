import json

import httpx
import pytest
from fastapi.testclient import TestClient

from backend import main
from backend.ai import settings_routes
from backend.ai.client import ModelClient
from backend.ai.config import Settings
from backend.ai.schemas import Extraction
from backend.ai.settings_store import SETTINGS_FILE, update_local


def selection(provider='groq', visual='google', mode='text'):
    return dict(provider=provider, model='test-model', vision_provider=visual, vision_model='visual-model', pdf_mode=mode)


def test_persistent_key_replace_delete_and_legacy_compatibility(tmp_path, monkeypatch):
    monkeypatch.delenv('GROQ_API_KEY', raising=False)
    legacy = tmp_path / 'API.txt'
    legacy.write_text('legacy-private-key')
    assert Settings.load(tmp_path).api_key == 'legacy-private-key'
    update_local(tmp_path, credential=('groq', 'saved-private-key'))
    assert Settings.load(tmp_path).api_key == 'saved-private-key'
    update_local(tmp_path, credential=('groq', 'replaced-private-key'))
    value = Settings.load(tmp_path)
    assert value.api_key == 'replaced-private-key'
    assert 'private-key' not in json.dumps(value.public()) + repr(value)
    update_local(tmp_path, credential=('groq', None))
    assert not Settings.load(tmp_path).api_key
    assert legacy.read_text() == 'legacy-private-key'
    assert 'replaced-private-key' not in (tmp_path / SETTINGS_FILE).read_text()


def test_fixed_run_and_safe_configuration_api(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_routes, 'ROOT', tmp_path)
    update_local(tmp_path, selection=selection(), credential=('groq', 'first-private-key'))
    current = Settings.load(tmp_path)
    client = TestClient(main.app)
    response = client.put('/api/ai/config', json=selection('openai'))
    assert response.status_code == 200
    assert Settings.load(tmp_path).provider == 'openai'
    assert current.provider == 'groq' and current.api_key == 'first-private-key'
    for method, url, body in [('PUT', '/api/ai/credentials/google', {'key': 'google-private-key'}),
                              ('PUT', '/api/ai/credentials/google', {'key': 'private-key\ninvalid'}),
                              ('PUT', '/api/ai/credentials/google', {'key': ['google-private-key']}),
                              ('GET', '/api/ai/config', None), ('DELETE', '/api/ai/credentials/google', None)]:
        response = client.request(method, url, json=body) if body is not None else client.request(method, url)
        assert 'private-key' not in response.text
    assert not Settings.load(tmp_path).public()['providers']['google']['key_configured']
    rejected = client.put('/api/ai/config', json=selection(), headers={'origin': 'https://evil.example'})
    assert rejected.status_code == 403
    malformed = client.put('/api/ai/config', json={**selection(), 'provider': ['invalid-private-key']})
    assert malformed.status_code == 400 and 'invalid-private-key' not in malformed.text


def test_cache_separates_provider_model_settings_and_simulation(tmp_path):
    requests = []
    def reply(request):
        requests.append(request)
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': '{"mentions":[]}'}}]})
    for provider, model, tokens in [('groq', 'same-model', 4096), ('openai', 'same-model', 4096),
                                     ('groq', 'different-model', 4096), ('groq', 'same-model', 2048),
                                     ('groq', 'same-model', 4096)]:
        client = ModelClient(Settings(api_key='test-private-key', provider=provider, model=model, max_output_tokens=tokens),
                             transport=httpx.MockTransport(reply), cache_dir=tmp_path)
        client.complete('discovery', {}, Extraction)
        client.accept()
        assert client.records[0]['provider'] == provider
    assert len(requests) == 3  # Output budget changes reuse a complete, validated result.
    assert len(list(tmp_path.glob('*.json'))) == 3


def test_model_selection_rejects_unsupported_media(tmp_path):
    with pytest.raises(ValueError, match='native PDF'):
        update_local(tmp_path, selection=selection(visual='groq', mode='native'))
    with pytest.raises(ValueError, match='text tasks only'):
        update_local(tmp_path, selection=selection(visual='deepseek', mode='vision'))


def test_changing_settings_between_calls_affects_only_next_operation(tmp_path):
    update_local(tmp_path, selection=selection(), credential=('groq', 'snapshot-private-key'))
    update_local(tmp_path, credential=('openai', 'next-run-private-key'))
    requests = []
    def reply(request):
        requests.append(request)
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': '{"mentions":[]}'}}]})
    settings = Settings.load(tmp_path)
    running = ModelClient(settings, transport=httpx.MockTransport(reply))
    running.complete('discovery', {'number': 1}, Extraction)
    update_local(tmp_path, selection=selection('openai'))
    settings.provider = 'openai'  # External mutation must not change an existing operation either.
    running.complete('discovery', {'number': 2}, Extraction)
    next_run = ModelClient(Settings.load(tmp_path), transport=httpx.MockTransport(reply))
    next_run.complete('discovery', {'number': 3}, Extraction)
    assert [r.url.host for r in requests] == ['api.groq.com', 'api.groq.com', 'api.openai.com']
    assert requests[1].headers['authorization'] == 'Bearer snapshot-private-key'
    assert requests[2].headers['authorization'] == 'Bearer next-run-private-key'
    assert {r['provider'] for r in running.records} == {'groq'}


def test_encoded_credentials_are_rejected_before_history_or_cache(tmp_path):
    answer = {'mentions': [{'block_id': 'b', 'term_text': 'safe', 'context_quote': 'safe', 'canonical_name': 'safe',
                           'category': 'label', 'definition': 'encoded-private-key', 'reason': 'fixture'}]}
    encoded = json.dumps(answer).replace('encoded-private-key', ''.join('\\u%04x' % ord(c) for c in 'encoded-private-key'))
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={
        'choices': [{'finish_reason': 'stop', 'message': {'content': encoded}}]}))
    client = ModelClient(Settings(api_key='encoded-private-key'), transport=transport, cache_dir=tmp_path)
    from backend.ai.client import ModelError
    with pytest.raises(ModelError, match='credential material'):
        client.complete('discovery', {}, Extraction)
    client.accept()
    assert not list(tmp_path.iterdir()) and not client.records


def test_invalid_save_is_atomic_and_legacy_secrets_are_not_model_ids(tmp_path, monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'legacy-private-key')
    update_local(tmp_path, selection=selection())
    previous = (tmp_path / SETTINGS_FILE).read_bytes()
    invalid = {**selection(), 'model': 'legacy-private-key'}
    with pytest.raises(ValueError, match='Credentials cannot'):
        update_local(tmp_path, selection=invalid)
    assert (tmp_path / SETTINGS_FILE).read_bytes() == previous
    monkeypatch.setenv('TERM_AGENT_MAX_CALLS', 'legacy-private-key')
    with pytest.raises(ValueError) as exc:
        Settings.load(tmp_path)
    assert 'legacy-private-key' not in str(exc.value)
