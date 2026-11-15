"""Tiny UI contract fixture. No real key or Groq network connection is used."""
import os
import socket
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
os.environ['TERM_AGENT_DATA'] = str(root / 'tmp' / 'offline-ui-projects')
os.environ['GROQ_API_KEY'] = 'offline-fixture-key'
os.environ['TERM_AGENT_OFFLINE'] = '0'

from backend import main
from backend.ai import routes
from tests.test_ai_offline import fake_client
from fastapi.routing import APIRoute

main.new_client = lambda pid=None: fake_client()
routes.new_client = lambda pid=None: fake_client()
main.app.router.routes.insert(0, APIRoute('/api/offline-fixture', lambda: {
    'simulation': True, 'external_network': 'denied'}, methods=['GET']))
original_connect = socket.socket.connect


def local_only(sock, address):
    if isinstance(address, tuple) and address[0] not in ('127.0.0.1', 'localhost', '::1'):
        raise AssertionError('External network is prohibited in the UI fixture server.')
    return original_connect(sock, address)


socket.socket.connect = local_only

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(main.app, host='127.0.0.1', port=8766, log_level='warning')
