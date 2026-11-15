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
    assert len(requests) == 4
    assert len(list(tmp_path.glob('*.json'))) == 4


def test_model_selection_rejects_unsupported_media(tmp_path):
    with pytest.raises(ValueError, match='native PDF'):
        update_local(tmp_path, selection=selection(visual='groq', mode='native'))
    with pytest.raises(ValueError, match='text tasks only'):
        update_local(tmp_path, selection=selection(visual='deepseek', mode='vision'))
