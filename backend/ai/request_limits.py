"""One shared, secret-free request admission gate for a single backend process."""
import threading
import time
from collections import deque

from .rate_policy import valid_rpm
from ..operations import check, CURRENT


class RequestLimiter:
    def __init__(self, clock=time.monotonic, sleep=time.sleep, window=60, safety=.05):
        self.clock, self.sleep, self.window, self.safety = clock, sleep, window, safety
        self.lock = threading.Lock()
        self.buckets = {}

    def acquire(self, provider, model, rpm):
        if not valid_rpm(rpm):
            raise ValueError('RPM must be an integer from 1 to 1000.')
        started = self.clock()
        while True:
            check()
            with self.lock:
                now = self.clock()
                bucket = self.buckets.setdefault((provider, model), {'events': deque(), 'cooldown': 0})
                events = bucket['events']
                while events and events[0][0] <= now - self.window - self.safety:
                    events.popleft()
                # Saving a higher cap never clears usage or overrides a recently stricter operation.
                effective = min([rpm, *(limit for _, limit in events)])
                ready = max(now, bucket['cooldown'])
                if events:
                    ready = max(ready, events[-1][0] + self.window / effective + self.safety)
                if len(events) >= effective:
                    ready = max(ready, events[-effective][0] + self.window + self.safety)
                delay = ready - now
                if delay <= 1e-8:
                    events.append((now, rpm))
                    return max(0, now - started)
            # Never hold the lock during a wait: other models/providers remain independent.
            operation = CURRENT.get()
            if operation:
                operation.wait(min(delay, 1))
            else:
                self.sleep(min(delay, 1))

    def defer(self, provider, model, seconds):
        with self.lock:
            bucket = self.buckets.setdefault((provider, model), {'events': deque(), 'cooldown': 0})
            bucket['cooldown'] = max(bucket['cooldown'], self.clock() + seconds)


REQUEST_LIMITER = RequestLimiter()
