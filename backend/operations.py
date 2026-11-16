"""Single-process, transient LLM operations. Cancelled work never enters project history."""
import threading
import time
import uuid
from contextvars import ContextVar

from .project_lifecycle import ProjectStateError


CURRENT = ContextVar('llm_operation', default=None)


class Cancelled(Exception):
    pass


class Operation:
    def __init__(self, pid, kind):
        self.id, self.pid, self.kind = uuid.uuid4().hex, pid, kind
        self.lock = threading.RLock()
        self.cancelled = threading.Event()
        self.committed = False
        self.finalizing = False
        self.ended = False
        self.stage = 'starting'
        self.project_name = ''
        self.cache = {}

    def check(self):
        if self.cancelled.is_set():
            raise Cancelled()

    def cancel(self):
        with self.lock:
            if self.committed or self.finalizing or self.ended:
                return False
            self.cancelled.set()
            return True

    def wait(self, seconds):
        if self.cancelled.wait(seconds):
            raise Cancelled()

    def commit(self, action):
        # Cancellation and final persistence have exactly one ordering point.
        with self.lock:
            self.check()
            self.finalizing = True
            result = action()
            self.committed = True
            for path, payload in self.cache.items():
                try:
                    path.parent.mkdir(exist_ok=True)
                    if not path.exists():
                        path.write_text(payload, encoding='utf-8')
                except OSError:
                    pass  # Cache is optional; a saved project remains authoritative.
            self.cache.clear()
            return result

    def public(self):
        return {'id': self.id, 'project_id': self.pid, 'project_name': self.project_name, 'kind': self.kind, 'stage': self.stage,
                'status': 'cancelling' if self.cancelled.is_set() else 'finishing' if self.finalizing else 'running'}


class Operations:
    def __init__(self):
        self.lock = threading.RLock()
        self.items = {}

    def start(self, pid, kind):
        with self.lock:
            if pid and any(o.pid == pid for o in self.items.values()):
                raise ProjectStateError('This project already has an LLM operation. Cancel it or wait for completion.')
            op = Operation(pid, kind)
            self.items[op.id] = op
            return op

    def active(self, pid=None):
        with self.lock:
            return [o.public() for o in self.items.values() if pid is None or o.pid == pid]

    def cancel(self, ids):
        with self.lock:
            selected = {oid: self.items.get(oid) for oid in ids}
        # A final save may hold one operation lock; never block all status/cancellation on it.
        return {oid: op.cancel() if op else False for oid, op in selected.items()}

    def finish(self, op):
        with op.lock:
            op.ended = True
            op.cache.clear()
        with self.lock:
            self.items.pop(op.id, None)


OPERATIONS = Operations()


def check():
    op = CURRENT.get()
    if op:
        op.check()


def wait(seconds):
    op = CURRENT.get()
    if op:
        op.wait(seconds)
    else:
        time.sleep(seconds)
