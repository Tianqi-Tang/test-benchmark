from __future__ import annotations

import time

from ..models import ModelConfig
from .providers import call_provider, sanitize_error_message
from .types import LlmCallResult


def call_model(
    config: ModelConfig,
    prompt: str,
    max_output_tokens: int | None = None,
    max_attempts: int | None = None,
) -> LlmCallResult:
    started = time.perf_counter()
    try:
        text, raw = call_provider(
            config,
            prompt,
            max_output_tokens,
            **({"max_attempts": max_attempts} if max_attempts is not None else {}),
        )
        return LlmCallResult(
            ok=True,
            text=text,
            raw_response=raw,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
    except Exception as exc:
        return LlmCallResult(
            ok=False,
            text=None,
            error=sanitize_error_message(str(exc)),
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
