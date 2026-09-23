"""Small process-local cache; authorization is checked before every lookup."""

import threading
import time
from collections import OrderedDict
from collections.abc import Callable


class PreviewCache:
    def __init__(self, max_bytes: int = 4 * 1024 * 1024, ttl: float = 60):
        self.max_bytes = max_bytes
        self.ttl = ttl
        self._entries: OrderedDict[tuple[object, ...], tuple[float, bytes]] = OrderedDict()
        self._lock = threading.Lock()
        self._bytes = 0

    def get(self, key: tuple[object, ...], render: Callable[[], bytes]) -> bytes:
        with self._lock:
            now = time.monotonic()
            for expired in [key for key, (until, _) in self._entries.items() if until <= now]:
                self._bytes -= len(self._entries.pop(expired)[1])
            if key in self._entries:
                self._entries.move_to_end(key)
                return self._entries[key][1]
        data = render()
        if len(data) > self.max_bytes:
            return data
        with self._lock:
            previous = self._entries.pop(key, None)
            if previous:
                self._bytes -= len(previous[1])
            while self._entries and (
                self._bytes + len(data) > self.max_bytes or len(self._entries) >= 24
            ):
                self._bytes -= len(self._entries.popitem(last=False)[1][1])
            self._entries[key] = (time.monotonic() + self.ttl, data)
            self._bytes += len(data)
        return data
