"""Opt-in, synthetic-text-only Groq evidence checks. No existing project or machine setting is changed."""
import argparse
import json
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def execute():
    from backend.ai.client import ModelClient, ModelError
    from backend.ai.config import Settings, credentials, local_options
    from backend.ai.explanations import supplement, evidence_current
    from backend.ai.settings_store import read_local
    keys, _ = credentials(local_options(), read_local(ROOT), ROOT)
    if not keys['groq']:
        raise ValueError('An enabled local Groq credential is required; no provider fallback.')
    p = {'id': 'synthetic', 'concepts': [{'id':str(i),'name':name,'aliases':[]} for i,name in enumerate(
        ('Group Atlas','Primary Endpoint','Visit Q','Assessment Window'))], 'documents': []}
    texts = {
        'Protocol': ['Group Atlas receives placebo.', 'Primary Endpoint is change in marker X from baseline to day 7.',
                     'Visit Q', 'The Assessment Window starts on day 1.'],
        'SAP': ['Group Atlas is analyzed as the placebo group.', 'Primary Endpoint is change in marker X from baseline to day 14.',
                'The Assessment Window ends on day 7.']}
    for role, paragraphs in texts.items():
        p['documents'].append({'id':role, 'role':role, 'blocks':[{'id':role+str(i),'text':text,'page':1,'region':'body'}
                             for i,text in enumerate(paragraphs)]})
    model = 'openai/gpt-oss-20b'
    client = ModelClient(Settings(api_key=keys['groq'],model=model,pdf_mode='text',max_calls=8,max_output_tokens=4096,
                                  rate_limits={'groq':{model:10}}))
    out = ROOT/'output'/('explanations-live-'+uuid.uuid4().hex[:12]);out.mkdir(parents=True)
    summary = {'simulation':False,'synthetic_text_only':True,'provider':'groq','model':model,
               'full_project_workflow_tested':False,'remote_cancellation_tested':False,'passed':False}
    try:
        result = supplement(p,client)
        explanations = {c['name']:c['explanation'] for c in p['concepts']}
        summary.update(result=result, explanations=explanations,
            passed=result['status']=='completed' and explanations['Primary Endpoint']['status']=='conflict'
                and explanations['Visit Q']['status']=='not_found' and bool(explanations['Group Atlas']['claims'])
                and all(evidence_current(claim,p['documents']) for c in p['concepts'] for claim in c['explanation']['claims']))
    except Exception as exc:
        summary['error'] = str(exc) if isinstance(exc,ModelError) else type(exc).__name__
    summary.update(calls=client.records, reported_tokens=sum(c['usage'].get('total_tokens',0) for c in client.records))
    payload=json.dumps(summary,ensure_ascii=False,indent=2)
    if keys['groq'] in payload:
        raise ValueError('Credential material rejected before evidence write.')
    (out/'summary.json').write_text(payload,encoding='utf-8')
    print(json.dumps({k:v for k,v in summary.items() if k not in ('explanations','calls')},ensure_ascii=False))
    print('Evidence:',out/'summary.json')
    return 0 if summary['passed'] else 1


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--live',action='store_true')
    args=parser.parse_args()
    if args.live:
        raise SystemExit(execute())
    print('DRY RUN: --live sends a synthetic evidence scan and at most four relationship requests to free Groq. No real PDFs, existing projects or other providers are used.')
