import importlib.util
import json
from pathlib import Path

import httpx

from backend.ai.config import Settings
from backend.ai.diagnostics import rejected_output_summary
from backend.ai.schemas import Extraction


def test_failed_generation_summary_exposes_only_structure():
    for raw, expected in [('{"mentions": [', {'valid_json': False, 'possibly_incomplete': True}),
                           ('{"mentions": [], "PRIVATE DOCUMENT": "fixture-private-key"}',
                            {'valid_json': True, 'schema_valid': False}),
                           ('{"mentions": []}', {'valid_json': True, 'schema_valid': True})]:
        result = rejected_output_summary({'failed_generation': raw}, Extraction)
        assert all(result.get(k) == v for k, v in expected.items())
        assert 'PRIVATE DOCUMENT' not in json.dumps(result)
        assert 'fixture-private-key' not in json.dumps(result)
    assert rejected_output_summary({}, Extraction) == {'output_available': False}


def diagnostic_script():
    path = Path(__file__).resolve().parents[1] / 'scripts/diagnose-groq.py'
    spec = importlib.util.spec_from_file_location('diagnose_groq', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_synthetic_comparison_is_bounded_and_never_outputs_content():
    requests = []
    def reply(request):
        body = json.loads(request.content)
        requests.append(body)
        assert 'synthetic-block' in body['messages'][1]['content']
        return httpx.Response(400, json={'error': {'code': 'json_validate_failed',
            'failed_generation': '{"PRIVATE DOCUMENT": "fixture-private-key"}'}})
    results = diagnostic_script().diagnose(Settings(api_key='fixture-private-key'), httpx.MockTransport(reply))
    assert len(requests) == len(results) == 2
    assert requests[1] == {**requests[0], 'reasoning_effort': 'low'}
    assert 'PRIVATE DOCUMENT' not in json.dumps(results) and 'fixture-private-key' not in json.dumps(results)


def test_synthetic_comparison_stops_on_auth_or_quota_error():
    requests = []
    def reply(request):
        requests.append(request)
        return httpx.Response(429, json={'error': {'code': 'rate_limit_exceeded'}})
    result = diagnostic_script().diagnose(Settings(api_key='fixture-key'), httpx.MockTransport(reply))
    assert len(requests) == len(result) == 1
