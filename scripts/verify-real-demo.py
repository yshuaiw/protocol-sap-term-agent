"""Exercise four reviewer-selected real abbreviation-list occurrences through the live API."""
import json
from pathlib import Path
import httpx

root = Path(__file__).resolve().parents[1]
client = httpx.Client(base_url='http://127.0.0.1:8765', timeout=300, trust_env=False)


def request(method, route, **kwargs):
    response = client.request(method, route, **kwargs)
    response.raise_for_status()
    return response.json()


summary = json.loads((root / 'output' / 'real-demo-summary.json').read_text())
bundle = client.get(f'/api/projects/{summary["id"]}/bundle').content
p = request('POST', '/api/bundles', files={'file': ('real-demo.zip', bundle)})
path = f'/api/projects/{p["id"]}'
concept = next(c for c in p['concepts'] if c['name'].casefold() == 'full analysis set')
chosen = [m for m in p['mentions'] if m['concept_id'] == concept['id'] and
          ((m['role'] == 'Protocol' and m['page'] == 16) or (m['role'] == 'SAP' and m['page'] == 7))]
assert len(chosen) == 4 and all(m['context'] == 'FAS Full analysis set' for m in chosen)
for m in chosen:
    p = request('PUT', path + '/mentions/' + m['id'], json={
        'revision': p['revision'], 'concept_id': concept['id'], 'status': 'confirmed'})
# Keep other unreviewed matches unresolved. One evidence-reviewed occurrence remains preserved.
preserved = next(m for m in p['mentions'] if m['concept_id'] == concept['id'] and m['role'] == 'SAP' and m['page'] == 16 and m['text'] == 'Full analysis set')
p = request('PUT', path + '/mentions/' + preserved['id'], json={
    'revision': p['revision'], 'concept_id': concept['id'], 'status': 'preserve'})
p = request('POST', path + '/plans', json={'revision': p['revision'], 'concept_id': concept['id'],
    'mode': 'rules', 'mappings': {'Full analysis set': 'Main analysis set', 'FAS': 'MAS'}})
plan = p['plans'][-1]
assert sum(i['proposal'] == 'update' for i in plan['items']) == 4
assert any(i['proposal'] == 'unresolved' for i in plan['items'])
assert any(i['proposal'] == 'preserve' for i in plan['items'])
p = request('POST', path + f'/plans/{plan["id"]}/apply', json={'revision': p['revision'],
    'approved_ids': [m['id'] for m in chosen], 'coverage_acknowledged': True})
result = p['exports'][-1]
assert result['verification']['verified'] and result['verification']['approved_delta_match']
assert len(result['verification']['approved_changes']) == 4
assert all(d['source_page_image_hashes_match'] for d in result['verification']['documents'])
assert sum(m['text'] in ('MAS', 'Main analysis set') for m in p['mentions']) == 4
assert next(m for m in p['mentions'] if m['id'] == preserved['id'])['status'] == 'preserve'
out = root / 'output' / 'real-demo-verification'
out.mkdir(parents=True, exist_ok=True)
for filename in result['files']:
    response = client.get(path + f'/exports/{result["id"]}/{filename}')
    response.raise_for_status()
    (out / filename).write_bytes(response.content)
(root / 'output' / 'DAPA-CKD-reviewed-demo-project.zip').write_bytes(client.get(path + '/bundle').content)
(out / 'project-id.txt').write_text(p['id'])
print(json.dumps({'project': p['id'], 'approved': 4, 'documents': result['verification']['documents'],
                  'limits': 'Technical partial rename of four reviewed abbreviation-list strings; other matches remain preserved or unresolved. Not clinical validation.'}, indent=2))
