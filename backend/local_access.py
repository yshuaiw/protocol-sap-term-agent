"""Shared same-origin guard for local settings and destructive project actions."""
from fastapi import HTTPException


def local_mutation(request):
    if request.url.hostname not in ('localhost', '127.0.0.1', '::1', 'testserver'):
        raise HTTPException(403, 'Changes must be made through the local application.')
    origin = request.headers.get('origin')
    if origin and origin != str(request.base_url).rstrip('/'):
        raise HTTPException(403, 'Open this action from the local application origin.')
