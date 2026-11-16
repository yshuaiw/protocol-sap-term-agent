"""Exact-source evidence, partial preservation and reviewer roundtrips; scripted model outputs only."""
import copy
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from backend import main
from backend.ai import routes
from backend.ai.client import ModelClient, ModelError
from backend.ai.config import Settings
from backend.ai.explanations import anchored_claim, evidence_current, supplement
from backend.ai.providers import PROVIDERS
from backend.store import Store
from tests.test_ai_offline import ScriptedGroq, fake_client, import_pair


def project():
    return {'id': 'synthetic', 'concepts': [{'id':'c','name':'Visit A','aliases':['VA'], 'definition':'Old unsupported suggestion'}],
            'documents':[{'id':'d1','role':'Protocol','blocks':[
                {'id':'b1','text':'😀 Visit A occurs on day 7.','page':1,'region':'body'}]},
                {'id':'d2','role':'SAP','blocks':[
                {'id':'b2','text':'Visit A occurs on day 14.','page':2,'region':'table'}]}]}


def claim(bid='b1', quote='Visit A occurs on day 7.', kind='explicit'):
    return {'statement':quote, 'kind':kind, 'evidence':[{'block_id':bid,'quote':quote,'support':'States the visit timing explicitly.'}]}


def model_reply(data):
    return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(data)}}]})


def responder(relationship='conflict', empty=False):
    def respond(request):
        data=json.loads(json.loads(request.content)['messages'][1]['content'])
        if 'explanation_targets' in data:
            return model_reply({'concepts':[{'concept_id':c['id'],'missing_reason':'Only an occurrence, no definition.' if empty else '',
                'claims':[] if empty else [claim(b['block_id'], b['text'].removeprefix('😀 ')) for b in data['source_ranges']]}
                for c in data['explanation_targets']]})
        return model_reply({'relationship':relationship,'reason':'The two documents specify incompatible days.'})
    return respond


def test_full_scan_keeps_conflicts_separate_and_offsets_are_program_owned():
    p=project()
    client=fake_client(responder())
    summary=supplement(p,client)
    result=p['concepts'][0]['explanation']
    assert summary['status']=='completed' and summary['counts']['conflict']==1
    assert result['status']=='conflict' and len(result['claims'])==2
    evidence=result['claims'][0]['evidence'][0]
    assert evidence['start']==2 and evidence['end']==26  # Python Unicode, including one emoji code point.
    assert evidence['role']=='Protocol' and result['claims'][1]['evidence'][0]['role']=='SAP'
    assert all(evidence_current(c,p['documents']) and c['review']=='pending' for c in result['claims'])
    assert {r['stage'] for r in client.records}=={'explanation_scan','explanation_relation'}


@pytest.mark.parametrize('relationship',['complementary','uncertain'])
def test_compatible_details_and_uncertainty_are_not_overwritten(relationship):
    p=project()
    supplement(p,fake_client(responder(relationship)))
    result=p['concepts'][0]['explanation']
    assert len(result['claims'])==2 and result['relationship']==relationship
    assert result['status']=='needs_review'


def test_missing_definition_has_no_external_or_legacy_fallback():
    p=project()
    result=supplement(p,fake_client(responder(empty=True)))
    assert result['counts']['not_found']==1
    assert not p['concepts'][0]['explanation']['claims']
    assert p['concepts'][0]['definition']=='Old unsupported suggestion'


@pytest.mark.parametrize('bid,quote',[('other','Visit A occurs on day 7.'),('b1','Visit A occurs on day 8.'),('b1','Visit A')])
def test_rejects_invented_outside_and_bare_term_evidence(bid,quote):
    p=project()
    units=[{'block_id':'b1','start':0,'end':25}]
    with pytest.raises(ModelError):
        anchored_claim(claim(bid,quote),units,p['documents'],['Visit A','VA'])


def test_rejects_ambiguous_quote_and_quote_outside_submitted_range():
    p=project();p['documents'][0]['blocks'][0]['text']='Visit A occurs on day 7. Visit A occurs on day 7.'
    with pytest.raises(ModelError):
        anchored_claim(claim(),[{'block_id':'b1','start':0,'end':len(p['documents'][0]['blocks'][0]['text'])}],p['documents'],['Visit A'])
    with pytest.raises(ModelError):
        anchored_claim(claim(),[{'block_id':'b1','start':0,'end':10}],p['documents'],['Visit A'])


def test_partial_timeout_retains_valid_claims_and_stops_further_scan_attempts():
    p=project();count=0
    def respond(request):
        nonlocal count
        count+=1
        if count==2:
            raise httpx.ReadTimeout('private raw error text withheld')
        return responder()(request)
    client=ModelClient(Settings(api_key='fixture',chunk_units=1,pdf_mode='text'),transport=httpx.MockTransport(respond))
    summary=supplement(p,client)
    result=p['concepts'][0]['explanation']
    assert summary['status']=='partial' and result['status']=='partial'
    assert len(result['claims'])==1 and result['scanned']==1 and result['total']==2 and count==2
    assert 'private raw' not in json.dumps(result)
    previous=copy.deepcopy(result['claims'])
    supplement(p,fake_client(lambda r: httpx.Response(401,json={})))
    assert p['concepts'][0]['explanation']['claims'][0]['previous_retained']
    assert p['concepts'][0]['explanation']['claims'][0]['id']==previous[0]['id']


def test_invalid_claim_visible_partial_keeps_other_valid_evidence():
    p=project()
    def respond(request):
        return model_reply({'concepts':[{'concept_id':'T1','missing_reason':'','claims':[claim(),claim('b2','Invented claim')]}]})
    supplement(p,fake_client(respond))
    result=p['concepts'][0]['explanation']
    assert result['status']=='partial' and len(result['claims'])==1 and result['issues']


def test_automatic_explanations_existing_button_review_and_stale_source(tmp_path,monkeypatch):
    monkeypatch.setattr(main,'store',Store(tmp_path/'projects'))
    monkeypatch.setattr(routes,'new_client',lambda pid=None:fake_client())
    with TestClient(main.app) as app:
        p=import_pair(app);path=f"/api/projects/{p['id']}"
        p=app.post(path+'/ai/generate',json={'revision':p['revision']}).json()
        assert p['concepts'] and p['concepts'][0]['explanation']['claims']
        cid=p['concepts'][0]['id'];first=p['concepts'][0]['explanation']['claims'][0]
        reviewed=app.put(path+'/explanations/'+cid,json={'revision':p['revision'],'claim_id':first['id'],
            'decision':'accepted','note':'Checked source meaning.'})
        assert reviewed.status_code==200
        p=reviewed.json();assert p['concepts'][0]['explanation']['claims'][0]['review']=='accepted'
        before=len(p['ai_runs'])
        assert app.get(path).json()['ai_runs']==p['ai_runs']  # Opening never calls the model.
        updated=app.post(path+'/ai/explanations',json={'revision':p['revision']})
        assert updated.status_code==200 and len(updated.json()['ai_runs'])==before+1
        p=updated.json()
        b=next(b for d in p['documents'] for b in d['blocks'] if b['id']==first['evidence'][0]['block_id'])
        b['text']='Source was edited.';p=main.store.save(p,'Synthetic source modification')
        assert app.put(path+'/explanations/'+cid,json={'revision':p['revision'],'claim_id':first['id'], 'decision':'accepted'}).status_code==400


def test_explanation_failure_preserves_new_registry(tmp_path,monkeypatch):
    monkeypatch.setattr(main,'store',Store(tmp_path/'projects'))
    fixture=ScriptedGroq()
    def respond(request):
        data=json.loads(json.loads(request.content)['messages'][1]['content'])
        return httpx.Response(401,json={}) if 'explanation_targets' in data else fixture(request)
    monkeypatch.setattr(routes,'new_client',lambda pid=None:fake_client(respond))
    with TestClient(main.app) as app:
        p=import_pair(app)
        response=app.post(f"/api/projects/{p['id']}/ai/generate",json={'revision':p['revision']})
        assert response.status_code==200
        p=response.json()
        assert len(p['mentions'])==10 and p['concepts']
        assert p['ai_runs'][-1]['status']=='completed_with_gaps'
        assert p['concepts'][0]['explanation']['status']=='partial'


def test_synthesis_can_cite_multiple_selected_documents_without_becoming_verified_fact():
    p=project()
    units=[{'block_id':'b1','start':0,'end':26},{'block_id':'b2','start':0,'end':25}]
    proposed=claim(kind='synthesis')
    proposed['statement']='The documents describe different visit days.'
    proposed['evidence'].append(claim('b2','Visit A occurs on day 14.')['evidence'][0])
    actual=anchored_claim(proposed,units,p['documents'],['Visit A'])
    assert actual['kind']=='synthesis' and actual['review']=='pending'
    assert {e['role'] for e in actual['evidence']}=={'Protocol','SAP'}


@pytest.mark.parametrize('provider',PROVIDERS)
def test_explanation_contract_uses_each_configured_adapter_without_fallback(provider):
    from tests.test_multi_provider import answer
    from backend.ai.explanations import ExplanationScan
    requests=[]
    expected={'concepts':[{'concept_id':'T1','claims':[],'missing_reason':'No definition support in supplied text.'}]}
    def respond(request):
        requests.append(request)
        assert str(request.url).startswith(PROVIDERS[provider]['base'])
        return httpx.Response(200,json=answer(provider,expected))
    client=ModelClient(Settings(api_key='synthetic-key',provider=provider,model='synthetic-model'),transport=httpx.MockTransport(respond))
    assert client.complete('explanation_scan',{'explanation_targets':[{'id':'T1','name':'Visit A','aliases':[]}],
        'source_ranges':[]},ExplanationScan)==expected
    assert len(requests)==1 and client.records[0]['provider']==provider
