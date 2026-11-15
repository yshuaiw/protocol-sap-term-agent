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
    assert len(calls) == 1 and not client.records


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
