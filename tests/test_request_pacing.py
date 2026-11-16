"""Admission behavior; provider bodies are scripted, timings are not model-quality evidence."""
import json
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from backend.ai.client import ModelClient
from backend.ai.config import Settings
from backend.ai.request_limits import RequestLimiter
from backend.ai.schemas import Extraction


class Clock:
    def __init__(self):
        self.now = 0.0

    def sleep(self, seconds):
        self.now += seconds


def success():
    return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': '{"mentions":[]}'}}]})


def test_all_stages_clients_and_same_text_visual_model_share_quota():
    clock = Clock()
    gate = RequestLimiter(clock=lambda: clock.now, sleep=clock.sleep)
    starts = []
    def reply(request):
        starts.append(clock.now)
        return success()
    settings = Settings(api_key='fixture-key', model='shared', vision_model='shared',
                        rate_limits={'groq': {'shared': 3}})
    first = ModelClient(settings, transport=httpx.MockTransport(reply), limiter=gate)
    second = ModelClient(settings, transport=httpx.MockTransport(reply), limiter=gate)
    for client, stage, media in [(first, 'discovery', {}), (second, 'linking', {}),
                                 (first, 'vision', {'images': ['data:image/png;base64,AA==']}),
                                 (second, 'boundary_scan', {})]:
        client.complete(stage, {}, Extraction, **media)
    assert starts[0] == 0 and all(b - a >= 20 for a, b in zip(starts, starts[1:]))
    assert first.records[-1]['rpm_limit'] == 3 and second.records[-1]['rate_wait_seconds'] >= 20


def test_other_models_providers_and_cache_hits_do_not_consume_this_bucket(tmp_path):
    clock = Clock()
    gate = RequestLimiter(clock=lambda: clock.now, sleep=clock.sleep)
    starts = []
    def reply(request):
        starts.append(clock.now)
        return success()
    for provider, model in [('groq', 'A'), ('groq', 'B'), ('openai', 'A'), ('groq', 'A'), ('groq', 'A')]:
        client = ModelClient(Settings(api_key='fixture-key', provider=provider, model=model,
                                     rate_limits={provider: {model: 2}}),
                             transport=httpx.MockTransport(reply), cache_dir=tmp_path, limiter=gate)
        client.complete('discovery', {}, Extraction)
        client.accept()
    assert starts == [0, 0, 0]  # Later A requests were validated local cache hits.
    assert gate.acquire('groq', 'A', 2) >= 30


def test_retries_and_format_recovery_each_pass_through_gate(monkeypatch):
    clock = Clock()
    monkeypatch.setattr('backend.ai.client.time.sleep', clock.sleep)
    gate = RequestLimiter(clock=lambda: clock.now, sleep=clock.sleep)
    starts = []
    statuses = [503, 429, 400, 200]
    def reply(request):
        starts.append(clock.now)
        status = statuses[len(starts) - 1]
        return success() if status == 200 else httpx.Response(status, headers={'retry-after': '2'},
                                    json={'error': {'code': 'json_validate_failed'}})
    model = 'openai/gpt-oss-20b'
    client = ModelClient(Settings(api_key='fixture-key', rate_limits={'groq': {model: 6}}),
                         transport=httpx.MockTransport(reply), limiter=gate)
    client.complete('discovery', {}, Extraction)
    assert len(starts) == client.records[0]['request_attempts'] == 4
    assert all(b - a >= 10 for a, b in zip(starts, starts[1:]))


def test_cooldown_is_shared_and_new_limit_does_not_reset_recent_usage():
    clock = Clock()
    gate = RequestLimiter(clock=lambda: clock.now, sleep=clock.sleep)
    assert gate.acquire('google', 'model', 4) == 0
    gate.defer('google', 'model', 30)
    assert gate.acquire('google', 'model', 15) >= 30
    assert gate.acquire('google', 'other', 15) == 0
    before = clock.now
    gate.acquire('google', 'model', 2)
    assert clock.now - before >= 30


def test_concurrent_operations_share_admission_without_blocking_other_models():
    gate = RequestLimiter(window=.06, safety=.001)
    def start(_):
        gate.acquire('google', 'shared', 2)
        return time.monotonic()
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(start, i) for i in range(4)]
        before = time.monotonic()
        gate.acquire('groq', 'independent', 2)
        assert time.monotonic() - before < .025
        starts = sorted(f.result(timeout=2) for f in futures)
    assert all(sum(a <= b < a + .06 for b in starts) <= 2 for a in starts)


@pytest.mark.parametrize('rpm', [0, -1, 1.5, True, 1001])
def test_invalid_limit_is_refused_before_sending(rpm):
    gate = RequestLimiter()
    with pytest.raises(ValueError, match='RPM'):
        gate.acquire('groq', 'model', rpm)
