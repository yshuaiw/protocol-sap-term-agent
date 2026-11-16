"""Opt-in Groq-only boundary evidence. Never changes saved provider settings or projects."""
import argparse
import hashlib
import io
import json
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def execute():
    from backend.ai.boundaries import suggest_boundaries
    from backend.ai.client import ModelClient, ModelError
    from backend.ai.config import Settings, credentials, local_options
    from backend.ai.settings_store import read_local
    from backend.input_documents import inspect_input
    from tests.test_boundaries import combined_pdf
    from reportlab.pdfgen.canvas import Canvas

    keys, _ = credentials(local_options(), read_local(ROOT), ROOT)
    if not keys['groq']:
        raise ValueError('A locally enabled Groq key is required; no other provider is called.')
    settings = Settings(api_key=keys['groq'], provider='groq', model='openai/gpt-oss-20b',
                        pdf_mode='text', max_calls=20, chunk_chars=7000, max_output_tokens=4096)
    out = ROOT / 'output' / ('boundary-live-' + uuid.uuid4().hex[:12])
    out.mkdir(parents=True)
    summary = {'simulation': False, 'provider': 'groq', 'model': settings.model,
               'vision_tested': False, 'complete_project_workflow_tested': False, 'cases': []}
    cases = [('synthetic_combined', combined_pdf())]
    buffer = io.BytesIO()
    pdf = Canvas(buffer)
    for lines in [('STUDY PROTOCOL', 'Study SYNTH-002, Version 1.0', 'Clinical methods and numbered sections'),
                  ('9. STATISTICAL ANALYSIS PLAN', 'This chapter is part of the protocol SYNTH-002.',
                   '9.1 Sample size', '9.2 Analysis methods'),
                  ('10. REFERENCES', 'End of protocol SYNTH-002')]:
        for index, line in enumerate(lines):
            pdf.drawString(40, 720 - index * 24, line)
        pdf.showPage()
    pdf.save()
    cases.append(('synthetic_protocol_with_statistics_chapter', buffer.getvalue()))
    for name, raw in cases:
        client = ModelClient(settings)
        entry = {'case': name, 'source_sha256': hashlib.sha256(raw).hexdigest()}
        try:
            inventory = inspect_input(raw, include_boundary_context=True)['_boundary_inventory']
            result = suggest_boundaries(inventory, client, raw)
            entry['result'] = result
            entry['expected_behavior_observed'] = (
                result['can_apply_pair'] and [(d['role'], d['start'], d['end']) for d in result['documents'] if d['applicable']]
                == [('Protocol', 1, 3), ('SAP', 4, 6)] if name == 'synthetic_combined' else
                not result['can_apply_pair'] and
                any(d['role'] == 'Protocol' and d['start'] == 1 and d['end'] == 3 for d in result['documents']) and
                not any(d['role'] == 'SAP' and d['kind'] == 'independent_document' for d in result['documents']))
        except (ModelError, ValueError) as error:
            entry['error'] = str(error) if settings.api_key not in str(error) else 'Credential material withheld.'
            entry['expected_behavior_observed'] = False
        entry['calls'] = client.records
        summary['cases'].append(entry)
        (out / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'case': name, 'observed': entry['expected_behavior_observed'],
                          'error': entry.get('error'), 'calls': len(client.records)}, ensure_ascii=False), flush=True)
    passed = all(c['expected_behavior_observed'] for c in summary['cases'])
    print(json.dumps({'passed': passed, 'evidence': str(out / 'summary.json')}))
    return 0 if passed else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    args = parser.parse_args()
    if args.live:
        raise SystemExit(execute())
    print('DRY RUN: --live calls Groq text only on synthetic PDFs. No project, original or saved setting is changed.')
