from __future__ import annotations

import itertools
from datetime import datetime, timedelta, timezone

import pytest

from memoraos import MemoryOS


class FakeClock:
    """Deterministic clock; every call advances one second so system time is strictly ordered."""

    def __init__(self, start: datetime | None = None):
        self.now = start or datetime(2026, 1, 1, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        self.now += timedelta(seconds=1)
        return self.now

    def jump(self, **kw: float) -> None:
        self.now += timedelta(**kw)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def mem(clock: FakeClock) -> MemoryOS:
    counter = itertools.count(1)
    m = MemoryOS.in_memory(clock=clock, id_factory=lambda p: f"{p}_{next(counter):05d}")
    yield m
    m.close()


@pytest.fixture
def disk(tmp_path, clock: FakeClock):
    counter = itertools.count(1)

    def make() -> MemoryOS:
        return MemoryOS.local(tmp_path / "data", clock=clock, id_factory=lambda p: f"{p}_{next(counter):05d}")

    return make
