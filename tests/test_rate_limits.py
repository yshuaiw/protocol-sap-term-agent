import httpx
import pytest

from backend.ai.client import GroqClient, ModelError
from backend.ai.config import Settings
from backend.ai.schemas import Extraction


def test_short_free_rate_limit_uses_provider_wait_and_one_retry(monkeypatch):
    waits, requests = [], []
    monkeypatch.setattr('backend.ai.client.time.sleep', waits.append)
    def reply(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(429, headers={'retry-after': '12.5'})
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': '{"mentions": []}'}}]})
    client = GroqClient(Settings(api_key='fixture-key'), transport=httpx.MockTransport(reply))
    assert client.complete('discovery', {}, Extraction) == {'mentions': []}
    assert waits == [13] and len(requests) == 2


@pytest.mark.parametrize('delay', ['3600', 'inf'])
def test_long_quota_wait_stops_instead_of_looping(monkeypatch, delay):
    waits, requests = [], []
    monkeypatch.setattr('backend.ai.client.time.sleep', waits.append)
    def reply(request):
        requests.append(request)
        return httpx.Response(429, headers={'retry-after': delay})
    client = GroqClient(Settings(api_key='fixture-key'), transport=httpx.MockTransport(reply))
    with pytest.raises(ModelError, match='longer wait'):
        client.complete('discovery', {}, Extraction)
    assert len(requests) == 1 and not waits


def test_short_followup_cooldown_can_finish_without_unbounded_wait(monkeypatch):
    waits, requests = [], []
    monkeypatch.setattr('backend.ai.client.time.sleep', waits.append)
    def reply(request):
        requests.append(request)
        if len(requests) <= 2:
            return httpx.Response(429, headers={'retry-after': '27' if len(requests) == 1 else '2'})
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': '{"mentions": []}'}}]})
    client = GroqClient(Settings(api_key='fixture-key'), transport=httpx.MockTransport(reply))
    assert client.complete('discovery', {}, Extraction) == {'mentions': []}
    assert waits == [27.5, 2.5] and len(requests) == 3


def test_cumulative_cooldown_is_bounded(monkeypatch):
    waits, requests = [], []
    monkeypatch.setattr('backend.ai.client.time.sleep', waits.append)
    def reply(request):
        requests.append(request)
        return httpx.Response(429, headers={'retry-after': '40'})
    client = GroqClient(Settings(api_key='fixture-key'), transport=httpx.MockTransport(reply))
    with pytest.raises(ModelError, match='wait budget'):
        client.complete('discovery', {}, Extraction)
    assert waits == [40.5] and len(requests) == 2


def test_server_format_and_rate_retries_have_a_finite_combined_bound(monkeypatch):
    requests = []
    monkeypatch.setattr('backend.ai.client.time.sleep', lambda seconds: None)
    statuses = [503, 429, 429, 400, 429, 429, 200]
    def reply(request):
        requests.append(request)
        status = statuses[len(requests) - 1]
        if status == 200:
            return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': '{"mentions": []}'}}]})
        return httpx.Response(status, headers={'retry-after': '1'}, json={'error': {'code': 'json_validate_failed'}})
    client = GroqClient(Settings(api_key='fixture-key'), transport=httpx.MockTransport(reply))
    client.complete('discovery', {}, Extraction)
    assert len(requests) == client.records[0]['request_attempts'] == 7
