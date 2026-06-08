from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any

import httpx

from .models import ModelConfig


DEFAULT_BASE_URLS = {
    "ant_ling": "https://api.ant-ling.com/v1",
    "deepseek": "https://api.deepseek.com",
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "qwen_vision": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "openai": "https://api.openai.com/v1",
    "openai_responses": "https://api.openai.com/v1",
    "gemini": "https://generativelanguage.googleapis.com",
}

MODEL_ALIASES = {
    "DeepSeek-v4-pro": "deepseek-v4-pro",
    "DeepSeek-v4-flash": "deepseek-v4-flash",
    "Gemini-3.5-flash": "gemini-3.5-flash",
    "Gemini-3.5-pro": "gemini-3.5-pro",
}

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
RETRYABLE_TRANSPORT_ERRORS = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.RemoteProtocolError,
)
MAX_ATTEMPTS = 3
SENSITIVE_QUERY_RE = re.compile(r"([?&](?:key|api_key|access_token)=)[^&\s'\"]+")
BEARER_TOKEN_RE = re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]+")


@dataclass
class LlmCallResult:
    ok: bool
    text: str | None
    latency_ms: int
    raw_response: dict[str, Any] | None = None
    error: str | None = None


def _base_url(config: ModelConfig) -> str:
    return (config.base_url or DEFAULT_BASE_URLS.get(config.provider, "")).rstrip("/")


def _with_v1(url: str) -> str:
    return url if url.endswith("/v1") else f"{url}/v1"


def _headers(config: ModelConfig) -> dict[str, str]:
    api_key = (config.api_key or "").strip()
    if not api_key:
        raise ValueError("API key is not configured.")
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def _model_name(config: ModelConfig) -> str:
    return MODEL_ALIASES.get(config.model, config.model)


def _max_output_tokens(config: ModelConfig, override: int | None) -> int:
    return override if override is not None else config.max_output_tokens


def _sanitize_error_message(message: str) -> str:
    message = SENSITIVE_QUERY_RE.sub(r"\1***", message)
    return BEARER_TOKEN_RE.sub(r"\1***", message)


def _retry_delay(attempt: int) -> float:
    return 0.4 * (2**attempt)


def _post_with_retry(client: httpx.Client, url: str, **kwargs: Any) -> httpx.Response:
    for attempt in range(MAX_ATTEMPTS):
        try:
            response = client.post(url, **kwargs)
            if response.status_code in RETRYABLE_STATUS_CODES and attempt < MAX_ATTEMPTS - 1:
                time.sleep(_retry_delay(attempt))
                continue
            response.raise_for_status()
            return response
        except RETRYABLE_TRANSPORT_ERRORS:
            if attempt >= MAX_ATTEMPTS - 1:
                raise
            time.sleep(_retry_delay(attempt))
    raise RuntimeError("HTTP request failed after retries.")


def call_model(config: ModelConfig, prompt: str, max_output_tokens: int | None = None) -> LlmCallResult:
    started = time.perf_counter()
    try:
        if config.provider == "openai_responses":
            text, raw = _call_openai_responses(config, prompt, max_output_tokens)
        elif config.provider == "gemini":
            text, raw = _call_gemini(config, prompt, max_output_tokens)
        else:
            text, raw = _call_openai_compatible(config, prompt, max_output_tokens)
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
            error=_sanitize_error_message(str(exc)),
            latency_ms=int((time.perf_counter() - started) * 1000),
        )


def _call_openai_compatible(config: ModelConfig, prompt: str, max_output_tokens: int | None) -> tuple[str, dict[str, Any]]:
    base_url = _with_v1(_base_url(config))
    payload = {
        "model": _model_name(config),
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": _max_output_tokens(config, max_output_tokens),
    }
    with httpx.Client(timeout=90.0) as client:
        response = _post_with_retry(client, f"{base_url}/chat/completions", headers=_headers(config), json=payload)
    raw = response.json()
    text = raw.get("choices", [{}])[0].get("message", {}).get("content") or ""
    return text.strip(), raw


def _call_openai_responses(config: ModelConfig, prompt: str, max_output_tokens: int | None) -> tuple[str, dict[str, Any]]:
    base_url = _with_v1(_base_url(config))
    payload = {
        "model": _model_name(config),
        "input": [{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
        "max_output_tokens": _max_output_tokens(config, max_output_tokens),
        "store": False,
    }
    with httpx.Client(timeout=90.0) as client:
        response = _post_with_retry(client, f"{base_url}/responses", headers=_headers(config), json=payload)
    raw = response.json()
    return _extract_responses_text(raw), raw


def _extract_responses_text(raw: dict[str, Any]) -> str:
    direct = raw.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    parts: list[str] = []
    for item in raw.get("output", []) or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []) or []:
            if not isinstance(content, dict):
                continue
            text = content.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "\n".join(parts).strip()


def _call_gemini(config: ModelConfig, prompt: str, max_output_tokens: int | None) -> tuple[str, dict[str, Any]]:
    api_key = (config.api_key or "").strip()
    if not api_key:
        raise ValueError("API key is not configured.")
    base_url = _base_url(config)
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0,
            "maxOutputTokens": _max_output_tokens(config, max_output_tokens),
        },
    }
    url = f"{base_url}/v1beta/models/{_model_name(config)}:generateContent"
    with httpx.Client(timeout=90.0) as client:
        response = _post_with_retry(
            client,
            url,
            params={"key": api_key},
            headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
            json=payload,
        )
    raw = response.json()
    parts = raw.get("candidates", [{}])[0].get("content", {}).get("parts", []) or []
    text = "\n".join(str(part.get("text", "")) for part in parts if isinstance(part, dict)).strip()
    return text, raw
