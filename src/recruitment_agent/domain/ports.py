"""Small infrastructure-neutral service ports."""

from datetime import datetime
from typing import Protocol
from uuid import UUID


class Clock(Protocol):
    """Supply timezone-aware current time."""

    def now(self) -> datetime: ...


class IdGenerator(Protocol):
    """Supply identifiers without coupling domain services to UUID creation."""

    def new(self) -> UUID: ...
