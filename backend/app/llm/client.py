from __future__ import annotations

import time

from ..models import ModelConfig
from .providers import ProviderCallError, call_provider, sanitize_error_message
from .types import LlmCallResult


def call_model(
    config: ModelConfig,
    prompt: str,
    max_output_tokens: int | None = None,
    max_attempts: int | None = None,
) -> LlmCallResult:
    started = time.perf_counter()
    try:
        text, raw, request = call_provider(
            config,
            prompt,
            max_output_tokens,
            **({"max_attempts": max_attempts} if max_attempts is not None else {}),
        )
        return LlmCallResult(
            ok=True,
            text=text,
            raw_response={"request": request, "response": raw},
            request=request,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
    except Exception as exc:
        request = exc.request if isinstance(exc, ProviderCallError) else None
        error = sanitize_error_message(str(exc))
        return LlmCallResult(
            ok=False,
            text=None,
            raw_response={"request": request, "error": error} if request is not None else None,
            request=request,
            error=error,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
