"""Settings never live inside application project state or request diagnostics."""
from fastapi import APIRouter, HTTPException, Request

from .config import ROOT, Settings
from .settings_store import update_local

router = APIRouter(prefix='/api/ai')


def local_mutation(request):
    # Also prevents DNS rebinding and cross-site writes to the local credential store.
    host = request.url.hostname
    if host not in ('localhost', '127.0.0.1', '::1', 'testserver'):
        raise HTTPException(403, 'API settings can only be changed through the local application.')
    origin = request.headers.get('origin')
    if origin and origin != str(request.base_url).rstrip('/'):
        raise HTTPException(403, 'Open API settings from the local application origin.')


async def safe_body(request):
    # Do not let framework validation echo submitted credential values in 422 responses.
    try:
        raw = await request.body()
        if len(raw) > 4096:
            raise ValueError()
        value = await request.json()
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (ValueError, TypeError):
        raise HTTPException(400, 'Invalid API settings request; contents withheld.') from None


@router.get('/config')
def config():
    return Settings.load(ROOT).public()


@router.put('/config')
async def save_config(request: Request):
    local_mutation(request)
    update_local(ROOT, selection=await safe_body(request))
    return config()


@router.put('/credentials/{provider}')
async def save_key(provider: str, request: Request):
    local_mutation(request)
    body = await safe_body(request)
    if set(body) != {'key'} or body['key'] is None:
        raise HTTPException(400, 'Provide a key to save or use Delete key; contents withheld.')
    update_local(ROOT, credential=(provider, body['key']))
    return config()


@router.delete('/credentials/{provider}')
def delete_key(provider: str, request: Request):
    local_mutation(request)
    update_local(ROOT, credential=(provider, None))
    return config()
