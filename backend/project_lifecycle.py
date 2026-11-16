"""One-process project activity, covering the complete ASGI response lifetime."""
import re
import threading
from contextlib import contextmanager

from starlette.responses import JSONResponse


class ProjectStateError(ValueError):
    status_code = 409


class ProjectMissing(ProjectStateError):
    status_code = 404


class ProjectActivity:
    def __init__(self):
        self._lock = threading.Lock()
        self._active = {}
        self._llm = {}
        self._deleting = set()

    def busy(self, pid):
        with self._lock:
            return bool(self._active.get(pid) or pid in self._deleting)

    @contextmanager
    def operation(self, pid, llm=False):
        with self._lock:
            if pid in self._deleting:
                raise ProjectStateError('Project deletion is in progress. Wait for it to finish.')
            self._active[pid] = self._active.get(pid, 0) + 1
            if llm:
                self._llm[pid] = self._llm.get(pid, 0) + 1
        try:
            yield
        finally:
            with self._lock:
                self._active[pid] -= 1
                if not self._active[pid]:
                    del self._active[pid]
                if llm:
                    self._llm[pid] -= 1
                    if not self._llm[pid]:
                        del self._llm[pid]

    def non_llm_busy(self, pid):
        with self._lock:
            return self._active.get(pid, 0) > self._llm.get(pid, 0) or pid in self._deleting

    def active_count(self, pid):
        with self._lock:
            return self._active.get(pid, 0)

    @contextmanager
    def deletion(self, pid, cancel_llm=False):
        # Separate from the store lock: reject busy exports immediately, without waiting
        # behind their long write lock and then deleting as soon as the export finishes.
        with self._lock:
            blocking = self._active.get(pid, 0) - (self._llm.get(pid, 0) if cancel_llm else 0)
            if blocking or pid in self._deleting:
                raise ProjectStateError('This project has an active operation. Wait for it to finish before deleting.')
            self._deleting.add(pid)
        try:
            yield
        finally:
            with self._lock:
                self._deleting.remove(pid)


class ProjectOperationMiddleware:
    def __init__(self, app, store_getter):
        self.app, self.store_getter = app, store_getter

    async def __call__(self, scope, receive, send):
        path = scope.get('path', '')
        match = re.fullmatch(r'/api/projects/([0-9a-f]{32})(/.*)?', path)
        tracked = scope['type'] == 'http' and match and not (
            scope['method'] == 'DELETE' and not match[2] or
            scope['method'] == 'GET' and match[2] == '/deletion' or
            scope['method'] == 'POST' and match[2] == '/cancel-delete')
        if not tracked:
            return await self.app(scope, receive, send)
        activity = self.store_getter().activity.operation(match[1], llm=scope.get('llm_operation', False))
        try:
            activity.__enter__()
        except ProjectStateError as exc:
            return await JSONResponse({'detail': str(exc)}, status_code=exc.status_code)(scope, receive, send)
        try:
            return await self.app(scope, receive, send)
        finally:
            activity.__exit__(None, None, None)
