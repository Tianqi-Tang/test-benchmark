from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class LlmCallResult:
    ok: bool
    text: str | None
    latency_ms: int
    raw_response: dict[str, Any] | None = None
    error: str | None = None
