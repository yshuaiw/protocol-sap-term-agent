"""Isolated, offline-only browser fixture with deliberate delays and explanation states."""
import json
import runpy
import threading
import time
from pathlib import Path

scope = runpy.run_path(str(Path(__file__).with_name('serve-offline-fixture.py')))
main, routes = scope['main'], scope['routes']
from fastapi import Request
from fastapi.routing import APIRoute
from backend.local_access import local_mutation
from tests.test_ai_offline import ScriptedGroq, fake_client

state = {'delay_stage': '', 'delay': 0, 'mode': 'normal', 'calls': []}
lock = threading.Lock()


async def control(request: Request):
    local_mutation(request)
    data = await request.json()
    with lock:
        state.update(delay_stage=data.get('delay_stage', ''), delay=min(8, max(0, data.get('delay', 0))),
                     mode=data.get('mode', 'normal'), calls=[])
    return {'simulation': True}


def status():
    with lock:
        return {'simulation': True, 'calls': list(state['calls'])}


def new_client(pid=None):
    scripted = ScriptedGroq()
    def respond(request):
        body = json.loads(request.content)
        stage = body['response_format'].get('json_schema', {}).get('name', 'other')
        with lock:
            state['calls'].append(stage)
            delay = state['delay'] if stage == state['delay_stage'] else 0
            mode = state['mode']
        if delay:
            time.sleep(delay)
        if mode == 'partial' and stage == 'explanation_scan':
            import httpx
            return httpx.Response(401, json={})
        response = scripted(request)
        if stage == 'explanation_relation' and mode == 'conflict':
            data = response.json()
            data['choices'][0]['message']['content'] = json.dumps({'relationship': 'conflict', 'reason': 'SIMULATED conflict for browser review; no semantic quality claim.'})
            import httpx
            return httpx.Response(200, json=data)
        if stage == 'explanation_scan' and mode == 'missing':
            data = response.json()
            answer = json.loads(data['choices'][0]['message']['content'])
            for concept in answer['concepts']:
                concept.update(claims=[], missing_reason='SIMULATED name-only context; no definition support.')
            data['choices'][0]['message']['content'] = json.dumps(answer)
            import httpx
            return httpx.Response(200, json=data)
        return response
    return fake_client(respond, cache_dir=main.store.folder(pid) / 'ai-cache' if pid else None)


main.new_client = routes.new_client = new_client
main.app.router.routes.insert(0, APIRoute('/api/workflow-fixture', control, methods=['POST']))
main.app.router.routes.insert(0, APIRoute('/api/workflow-fixture', status, methods=['GET']))

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(main.app, host='127.0.0.1', port=8766, log_level='warning')
