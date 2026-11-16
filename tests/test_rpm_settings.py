import json

import pytest
from fastapi.testclient import TestClient

from backend import main
from backend.ai import settings_routes
from backend.ai.client import ModelClient
from backend.ai.config import Settings
from backend.ai.settings_store import SETTINGS_FILE, update_local
from tests.test_provider_settings import selection


def test_profiles_persist_per_provider_model_without_changing_selection_or_key(tmp_path):
    update_local(tmp_path, selection=selection(), credential=('groq', 'fixture-private-key'))
    before = Settings.load(tmp_path)
    for provider, model, rpm in [('groq', 'test-model', 15), ('google', 'test-model', 5), ('groq', 'other', 30)]:
        update_local(tmp_path, rate_limit=dict(provider=provider, model=model, rpm=rpm))
    after = Settings.load(tmp_path)
    assert after.provider == before.provider and after.api_key == before.api_key
    assert [after.request_rpm(p, m) for p, m in [('groq', 'test-model'), ('google', 'test-model'), ('groq', 'other')]] == [15, 5, 30]
    assert after.public()['text_rpm'] == 15 and after.provenance()['text_rpm'] == 15
    assert 'fixture-private-key' not in json.dumps(after.public()) + json.dumps(after.provenance())
    running = ModelClient(after)
    update_local(tmp_path, rate_limit=dict(provider='groq', model='test-model', rpm=2))
    assert running.settings.request_rpm('groq', 'test-model') == 15
    assert Settings.load(tmp_path).request_rpm('groq', 'test-model') == 2
    update_local(tmp_path, rate_limit=dict(provider='groq', model='test-model', rpm=None))
    assert 'test-model' not in Settings.load(tmp_path).rate_limits['groq']
    assert Settings.load(tmp_path).api_key == 'fixture-private-key'


@pytest.mark.parametrize('rpm', [0, -1, 2.5, True, '15', 1001, [], {}])
def test_invalid_rpm_save_keeps_previous_configuration(tmp_path, rpm):
    update_local(tmp_path, selection=selection())
    original = (tmp_path / SETTINGS_FILE).read_bytes()
    with pytest.raises(ValueError, match='RPM'):
        update_local(tmp_path, rate_limit=dict(provider='google', model='safe-model', rpm=rpm))
    assert (tmp_path / SETTINGS_FILE).read_bytes() == original


def test_api_safe_save_read_reset_and_origin_guard(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_routes, 'ROOT', tmp_path)
    monkeypatch.setenv('GOOGLE_API_KEY', 'private-model-key')
    client = TestClient(main.app)
    body = dict(provider='google', model='safe-model', rpm=12)
    assert client.put('/api/ai/rate-limits', json=body).status_code == 200
    assert client.get('/api/ai/config').json()['rate_limits']['google']['safe-model'] == 12
    saved = (tmp_path / SETTINGS_FILE).read_bytes()
    for data in [{**body, 'model': 'private-model-key'}, {**body, 'rpm': 'private-model-key'},
                 {**body, 'provider': ['private-model-key']}, {**body, 'extra': 'private-model-key'}]:
        response = client.put('/api/ai/rate-limits', json=data)
        assert response.status_code == 400 and 'private-model-key' not in response.text
        assert (tmp_path / SETTINGS_FILE).read_bytes() == saved
    assert client.put('/api/ai/rate-limits', json=body, headers={'origin': 'https://evil.example'}).status_code == 403
    assert client.put('/api/ai/rate-limits', json={**body, 'rpm': None}).status_code == 200


def test_corrupt_saved_profiles_fail_safely(tmp_path):
    (tmp_path / SETTINGS_FILE).write_text(json.dumps({'selection': {}, 'credentials': {},
                                                    'rate_limits': {'google': {'model': 0}}}))
    with pytest.raises(ValueError, match='RPM'):
        Settings.load(tmp_path)
