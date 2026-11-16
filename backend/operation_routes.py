"""Ephemeral status/cancellation API and response gate for every user-started LLM action."""
import json
import re

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from starlette.responses import JSONResponse

from .local_access import local_mutation
from .operations import CURRENT, OPERATIONS, Cancelled
from .project_lifecycle import ProjectStateError

router = APIRouter(prefix='/api/operations')


class CancelRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    ids: list[str] = Field(max_length=100)


@router.get('')
def active():
    return OPERATIONS.active()


@router.post('/cancel')
def cancel(body: CancelRequest, request: Request):
    local_mutation(request)
    return {'accepted': OPERATIONS.cancel(body.ids),
            'notice': 'Cancellation waits for local work to stop. Submitted provider requests may still consume tokens.'}


class OperationMiddleware:
    def __init__(self, app, store_getter):
        self.app, self.store_getter = app, store_getter

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        path, method = scope.get('path', ''), scope['method']
        match = re.fullmatch(r'/api/projects/([0-9a-f]{32})/(ai/[a-z-]+|plans)', path)
        is_llm = method == 'POST' and (path == '/api/inspect/ai' or bool(match))
        if is_llm and match and match[2] == 'plans':
            messages = []
            while True:
                message = await receive()
                messages.append(message)
                if sum(len(m.get('body', b'')) for m in messages) > 1024 * 1024:
                    return await JSONResponse({'detail': 'Preview request exceeds the local size limit.'}, 413)(scope, receive, send)
                if message['type'] != 'http.request' or not message.get('more_body'):
                    break
            try:
                is_llm = json.loads(b''.join(m.get('body', b'') for m in messages)).get('mode', 'ai') == 'ai'
            except (ValueError, AttributeError):
                is_llm = False
            source_receive = receive
            async def replay():
                return messages.pop(0) if messages else await source_receive()
            receive = replay
        if not is_llm:
            pid_match = re.match(r'/api/projects/([0-9a-f]{32})(?:/|$)', path)
            if pid_match and method in ('POST', 'PUT', 'PATCH') and not path.endswith('/cancel-delete') and OPERATIONS.active(pid_match[1]):
                return await JSONResponse({'detail': 'An LLM operation is active. Cancel it or wait before editing this project.'}, 409)(scope, receive, send)
            return await self.app(scope, receive, send)
        op = None
        try:
            local_mutation(Request(scope))
            op = OPERATIONS.start(match[1] if match else None, match[2] if match else 'boundary suggestions')
            token = CURRENT.set(op)
            if op.pid:
                op.project_name = self.store_getter().load(op.pid)['name']
            scope['llm_operation'] = True
            output = []
            async def capture(message):
                output.append(message)
            # Do not subscribe to disconnect events: explicit cancellation is the only stop action.
            await self.app(scope, receive, capture)
            if not op.committed:
                op.commit(lambda: None)
            for message in output:
                await send(message)
        except Cancelled:
            await JSONResponse({'detail': 'LLM operation cancelled. No results, history or new cache were saved.', 'cancelled': True})(scope, receive, send)
        except HTTPException as exc:
            await JSONResponse({'detail': exc.detail}, exc.status_code)(scope, receive, send)
        except ProjectStateError as exc:
            await JSONResponse({'detail': str(exc)}, exc.status_code)(scope, receive, send)
        finally:
            if op:
                CURRENT.reset(token)
                OPERATIONS.finish(op)
