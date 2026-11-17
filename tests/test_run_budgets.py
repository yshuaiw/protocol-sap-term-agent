import hashlib
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from backend import main
from backend.ai import settings_routes
from backend.ai.client import ModelClient, ModelError
from backend.ai.config import Settings
from backend.ai.providers import ADAPTER_VERSION
from backend.ai.schemas import Extraction
from backend.ai.settings_store import SETTINGS_FILE


def response(content='{"mentions":[]}', finish='stop'):
    return httpx.Response(200, json={'choices': [{'finish_reason': finish, 'message': {'content': content}}]})


def test_defaults_and_settings_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_routes, 'ROOT', tmp_path)
    monkeypatch.delenv('TERM_AGENT_MAX_CALLS', raising=False)
    monkeypatch.delenv('TERM_AGENT_MAX_OUTPUT_TOKENS', raising=False)
    monkeypatch.setenv('GROQ_API_KEY', 'fixture-private-key')
    client = TestClient(main.app)
    initial = Settings.load(tmp_path)
    requests = []
    def reply(request):
        requests.append(json.loads(request.content))
        return response()
    running = ModelClient(initial, httpx.MockTransport(reply))
    assert (initial.max_calls, initial.max_output_tokens) == (10000, 16384)
    assert (running.settings.max_calls, running.settings.max_output_tokens) == (10000, 16384)
    result = client.put('/api/ai/run-limits', json={'max_calls': 20000, 'max_output_tokens': 32768})
    assert result.status_code == 200, result.text
    loaded = Settings.load(tmp_path)
    assert (loaded.max_calls, loaded.max_output_tokens) == (20000, 32768)
    running.complete('discovery', {}, Extraction)
    ModelClient(loaded, httpx.MockTransport(reply)).complete('discovery', {}, Extraction)
    assert [body['max_completion_tokens'] for body in requests] == [16384, 32768]
    assert (initial.max_calls, initial.max_output_tokens) == (10000, 16384)
    assert json.loads((tmp_path / SETTINGS_FILE).read_text())['run_limits'] == {'max_calls': 20000, 'max_output_tokens': 32768}
    saved = (tmp_path / SETTINGS_FILE).read_bytes()
    for bad in (True, 0, -1, 2.5, 'credential-private-string', 1000001):
        result = client.put('/api/ai/run-limits', json={'max_calls': bad, 'max_output_tokens': 32768})
        assert result.status_code == 400 and 'credential-private-string' not in result.text
        assert (tmp_path / SETTINGS_FILE).read_bytes() == saved
    assert client.put('/api/ai/run-limits', json={'max_calls': 20000, 'max_output_tokens': 32768},
                      headers={'origin': 'https://evil.example'}).status_code == 403


def test_cache_hits_do_not_use_attempt_budget(tmp_path):
    requests = []
    def reply(request):
        requests.append(request)
        return response()
    client = ModelClient(Settings(api_key='fixture-key', max_calls=1), httpx.MockTransport(reply), tmp_path)
    client.complete('discovery', {'part': 1}, Extraction)
    client.accept()
    for _ in range(600):
        client.complete('discovery', {'part': 1}, Extraction)
    with pytest.raises(ModelError, match='HTTP attempt'):
        client.complete('discovery', {'part': 2}, Extraction)
    assert len(requests) == 1


def test_failed_attempts_and_retries_use_budget():
    requests = []
    def reply(request):
        requests.append(request)
        return httpx.Response(503, json={})
    client = ModelClient(Settings(api_key='fixture-key', max_calls=1), httpx.MockTransport(reply))
    with pytest.raises(ModelError, match='HTTP attempt'):
        client.complete('discovery', {}, Extraction)
    assert len(requests) == 1 and not client.records


def test_default_budget_processes_more_than_500_new_requests():
    requests = []
    def reply(request):
        requests.append(request)
        return response()
    client = ModelClient(Settings(api_key='fixture-key'), httpx.MockTransport(reply))
    for i in range(600):
        client.complete('discovery', {'part': i}, Extraction)
    assert len(requests) == client.http_attempts == 600


def test_budget_and_rpm_changes_reuse_accepted_cache(tmp_path):
    requests = []
    def reply(request):
        requests.append(request)
        return response()
    for limit, output, rpm in [(500, 4096, 20), (20000, 32768, 5)]:
        client = ModelClient(Settings(api_key='fixture-key', max_calls=limit, max_output_tokens=output,
                             rate_limits={'groq': {'openai/gpt-oss-20b': rpm}}), httpx.MockTransport(reply), tmp_path)
        client.complete('discovery', {}, Extraction)
        client.accept()
    assert len(requests) == 1


def test_legacy_cache_survives_budget_raise_without_rewriting(tmp_path):
    old = Settings(api_key='fixture-key', max_calls=500, max_output_tokens=4096).provenance()
    project = tmp_path / 'project.json'
    project.write_text(json.dumps({'ai_runs': [{'configuration': old}]}))
    cache = tmp_path / 'ai-cache'
    cache.mkdir()
    identity = ['discovery', 'groq', 'openai/gpt-oss-20b', old, Extraction.model_json_schema(), {'part': 1},
                [], None, 'discovery-v5-explicit-terms', True, ADAPTER_VERSION]
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    existing = cache / (digest + '.json')
    existing.write_text('{"mentions":[]}')
    before = existing.read_bytes()
    def deny(request):
        raise AssertionError('A compatible legacy cache must not issue a request')
    client = ModelClient(Settings(api_key='fixture-key', max_calls=20000, max_output_tokens=32768), httpx.MockTransport(deny), cache)
    assert client.complete('discovery', {'part': 1}, Extraction) == {'mentions': []}
    assert client.records[0]['cached'] and existing.read_bytes() == before
    client.accept()
    assert len(list(cache.iterdir())) == 1


@pytest.mark.parametrize('content,finish,reason', [('{"mentions":[', 'length', 'truncated'),
    ('PRIVATE SOURCE', 'stop', 'invalid JSON'), ('{"wrong":"PRIVATE SOURCE"}', 'stop', 'schema validation')])
def test_safe_output_failure_reason(content, finish, reason):
    client = ModelClient(Settings(api_key='fixture-key'), httpx.MockTransport(lambda r: response(content, finish)))
    with pytest.raises(ModelError) as exc:
        client.complete('discovery', {}, Extraction)
    assert reason in str(exc.value) and 'discovery' in str(exc.value)
    assert 'PRIVATE SOURCE' not in str(exc.value) and 'fixture-key' not in str(exc.value)
    assert not client.records
