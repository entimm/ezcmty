from collections.abc import Iterator
from contextlib import contextmanager
from threading import RLock
from typing import Any


class MemoryRedis:
    def __init__(self) -> None:
        self.now = 1000.0
        self.values: dict[str, tuple[str, float]] = {}
        self.locks: dict[str, RLock] = {}

    @contextmanager
    def lock(self, name: str, **kwargs: Any) -> Iterator[None]:
        with self.locks.setdefault(name, RLock()):
            yield

    def get(self, key: str) -> str | None:
        item = self.values.get(key)
        return item[0] if item and item[1] > self.now else None

    def setex(self, key: str, ttl: int, value: str) -> None:
        self.values[key] = (value, self.now + ttl)

    def delete(self, key: str) -> None:
        self.values.pop(key, None)

    def expire(self, key: str, ttl: int) -> bool:
        value = self.get(key)
        if value is None:
            return False
        self.setex(key, ttl, value)
        return True

    def eval(self, script: str, key_count: int, *args: Any) -> int:
        exceeded = False
        window, limit = args[-2:]
        for key in args[:key_count]:
            item = self.values.get(key)
            count = int(self.get(key) or 0) + 1
            self.values[key] = (
                str(count),
                item[1] if item and item[1] > self.now else self.now + window,
            )
            exceeded |= count > limit
        if exceeded and "TTL" in script:
            return max(1, int(self.values[args[0]][1] - self.now))
        return int(exceeded)
