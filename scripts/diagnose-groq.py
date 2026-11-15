"""Two bounded SYNTHETIC requests, only with --live. No user documents or raw output."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
from backend.ai.client import SYSTEM, TASKS
from backend.ai.config import Settings
from backend.ai.diagnostics import rejected_output_summary
from backend.ai.schemas import Extraction


def probes(settings):
    text = 'Arm A receives study treatment. Arm B receives placebo. Visit 1 occurs on Day 1.'
    payload = {'chunks': [{'block_id': 'synthetic-block', 'role': 'Protocol', 'region': 'body',
                          'start': 0, 'end': len(text), 'text': text,
                          'preceding_context': '', 'following_context': ''}]}
    base = {'model': settings.model, 'messages': [
        {'role': 'system', 'content': SYSTEM + '\nTASK: ' + TASKS['discovery'] +
         '\nJSON schema: ' + json.dumps(Extraction.model_json_schema())},
        {'role': 'user', 'content': json.dumps(payload)}],
        'response_format': {'type': 'json_schema', 'json_schema': {
            'name': 'discovery', 'strict': True, 'schema': Extraction.model_json_schema()}},
        'max_completion_tokens': 4096}
    # Compare only the reasoning setting, with identical input and output budget.
    return [base, {**base, 'reasoning_effort': 'low'}]


def diagnose(settings, transport=None):
    results = []
    with httpx.Client(base_url='https://api.groq.com/openai/v1', timeout=90,
                      trust_env=False, transport=transport, follow_redirects=False) as client:
        for number, body in enumerate(probes(settings), 1):
            result = {'probe': number, 'reasoning_effort': body.get('reasoning_effort', 'model default')}
            try:
                response = client.post('/chat/completions', headers={'Authorization': 'Bearer ' + settings.api_key}, json=body)
                data = response.json()
            except (httpx.HTTPError, ValueError):
                results.append({**result, 'network_or_json_error': True})
                break
            result['http_status'] = response.status_code
            if response.status_code != 200:
                error = data.get('error', {}) if isinstance(data, dict) else {}
                result.update(rejected_output_summary(error, Extraction))
                code = error.get('code') if isinstance(error, dict) else None
                if code in ('json_validate_failed', 'invalid_json_schema', 'model_not_found', 'invalid_api_key', 'rate_limit_exceeded'):
                    result['code'] = code
            else:
                choices = data.get('choices', []) if isinstance(data, dict) else []
                choice = choices[0] if choices else {}
                finish = choice.get('finish_reason')
                if finish in ('stop', 'length', 'content_filter'):
                    result['finish_reason'] = finish
                result.update(rejected_output_summary({'failed_generation': choice.get('message', {}).get('content')}, Extraction))
                usage = data.get('usage', {})
                result['usage'] = {k: v for k, v in usage.items() if k in ('prompt_tokens', 'completion_tokens', 'total_tokens') and isinstance(v, int)}
            results.append(result)
            # Authentication/permission/quota errors do not justify another request.
            if response.status_code in (401, 403, 404, 429):
                break
    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='Make at most two real Groq requests using synthetic text.')
    args = parser.parse_args()
    if not args.live:
        print('DRY RUN: no API call. --live sends at most two synthetic discovery probes, 4096 output tokens each; no user documents or raw output.')
    else:
        settings = Settings.load()
        if settings.offline or not settings.api_key:
            parser.error('Live probes require offline=false and a local key. No request made.')
        if settings.model not in ('openai/gpt-oss-20b', 'openai/gpt-oss-120b'):
            parser.error('This comparison is limited to GPT-OSS models. No request made.')
        print(json.dumps(diagnose(settings), indent=2))
