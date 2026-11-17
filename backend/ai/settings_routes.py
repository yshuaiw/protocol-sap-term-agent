"""Settings never live inside application project state or request diagnostics."""
from fastapi import APIRouter, HTTPException, Request

from .config import ROOT, Settings
from .settings_store import update_local
from ..local_access import local_mutation

router = APIRouter(prefix='/api/ai')


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


@router.put('/rate-limits')
async def save_rate_limit(request: Request):
    local_mutation(request)
    update_local(ROOT, rate_limit=await safe_body(request))
    return config()


@router.delete('/credentials/{provider}')
def delete_key(provider: str, request: Request):
    local_mutation(request)
    update_local(ROOT, credential=(provider, None))
    return config()


@router.put('/run-limits')
async def save_run_limits(request: Request):
    local_mutation(request)
    update_local(ROOT, run_limits=await safe_body(request))
    return config()
