"""Opt-in Groq-only timing check with synthetic text, no project/config writes."""
import argparse
import json
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def execute():
    import httpx
    from backend.ai.client import ModelClient, ModelError
    from backend.ai.config import Settings, credentials, local_options
    from backend.ai.request_limits import RequestLimiter
    from backend.ai.schemas import Extraction
    from backend.ai.settings_store import read_local
    keys, _ = credentials(local_options(), read_local(ROOT), ROOT)
    if not keys['groq']:
        raise ValueError('A locally enabled Groq key is required; no alternative provider is used.')
    starts = []
    class TimedTransport(httpx.BaseTransport):
        def __init__(self):
            self.inner = httpx.HTTPTransport(trust_env=False)

        def handle_request(self, request):
            starts.append(time.monotonic())  # Never record headers, request/response bodies or keys.
            return self.inner.handle_request(request)

    transport = TimedTransport()
    model = 'openai/gpt-oss-20b'
    client = ModelClient(Settings(api_key=keys['groq'], model=model, pdf_mode='text', max_calls=3,
                                  rate_limits={'groq': {model: 3}}), transport=transport, limiter=RequestLimiter())
    out = ROOT / 'output' / ('rpm-live-' + uuid.uuid4().hex[:12])
    out.mkdir(parents=True)
    summary = {'simulation': False, 'provider': 'groq', 'model': model, 'rpm': 3,
               'synthetic_text_only': True, 'project_workflow_tested': False, 'passed': False}
    try:
        for index in range(3):
            client.complete('discovery', {'chunks': [{'block_id': f'synthetic-{index}',
                            'text': 'Arm A receives placebo in this synthetic example.'}]}, Extraction)
            print(f'Accepted synthetic request {index + 1}/3.', flush=True)
        gaps = [b - a for a, b in zip(starts, starts[1:])]
        summary.update(passed=len(client.records) == 3 and all(gap >= 19.9 for gap in gaps),
                       http_attempts=len(starts), start_offsets=[round(s - starts[0], 3) for s in starts],
                       gaps=[round(gap, 3) for gap in gaps])
    except Exception as error:
        summary['error'] = str(error) if isinstance(error, ModelError) else type(error).__name__
        if keys['groq'] in summary['error']:
            summary['error'] = 'Credential material withheld.'
    finally:
        transport.inner.close()
        summary['calls'] = client.records
        summary['reported_tokens'] = sum(c['usage'].get('total_tokens', 0) for c in client.records)
        (out / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
        print(json.dumps({k: v for k, v in summary.items() if k != 'calls'}, indent=2))
        print('Evidence:', out / 'summary.json')
    return 0 if summary['passed'] else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    args = parser.parse_args()
    if args.live:
        raise SystemExit(execute())
    print('DRY RUN: --live sends three small synthetic Groq requests at 3 RPM, about 40+ seconds. No saved settings/projects or other providers are used.')
