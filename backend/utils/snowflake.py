from __future__ import annotations

import os
import time


class SnowflakeIdGenerator:
    def __init__(self, *, worker_id: int) -> None:
        self._worker_id = worker_id & 0x1F
        self._sequence = 0
        self._last_ts_ms = -1

    def next_id(self) -> str:
        ts_ms = int(time.time() * 1000)
        if ts_ms == self._last_ts_ms:
            self._sequence = (self._sequence + 1) & 0xFFF
            if self._sequence == 0:
                while ts_ms <= self._last_ts_ms:
                    ts_ms = int(time.time() * 1000)
        else:
            self._sequence = 0

        self._last_ts_ms = ts_ms
        value = (ts_ms << 22) | (self._worker_id << 12) | self._sequence
        return str(value)


_DEFAULT_WORKER_ID = int(os.getenv("DEEPAGENTS_SNOWFLAKE_WORKER_ID", "1") or "1")
_generator = SnowflakeIdGenerator(worker_id=_DEFAULT_WORKER_ID)


def generate_snowflake_id() -> str:
    return _generator.next_id()
