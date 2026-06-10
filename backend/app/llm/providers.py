from __future__ import annotations

import json
import re
import time
from typing import Any

import httpx

from ..models import ModelConfig


DEFAULT_BASE_URLS = {
    "ant_ling": "https://api.ant-ling.com/v1",
    "deepseek": "https://api.deepseek.com",
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "qwen_vision": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "nvidia": "https://integrate.api.nvidia.com/v1",
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

PROVIDER_MODEL_ALIASES = {
    "nvidia": {
        "deepseek-v4-pro": "deepseek-ai/deepseek-v4-pro",
        "deepseek-v4-flash": "deepseek-ai/deepseek-v4-flash",
    },
}

PROVIDER_MODEL_CHAT_TEMPLATE_KWARGS = {
    "nvidia": {
        "deepseek-v4-pro": {"thinking": False},
        "deepseek-v4-flash": {"thinking": False},
    },
}

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
RETRYABLE_TRANSPORT_ERRORS = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.RemoteProtocolError,
)
MAX_ATTEMPTS = 3
REQUEST_TIMEOUT_SECONDS = 30.0
PROVIDER_TIMEOUT_SECONDS = {
    "nvidia": 120.0,
}
SENSITIVE_QUERY_RE = re.compile(r"([?&](?:key|api_key|access_token)=)[^&\s'\"]+")
BEARER_TOKEN_RE = re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]+")


class ProviderCallError(RuntimeError):
    def __init__(self, message: str, request: dict[str, Any]):
        super().__init__(message)
        self.request = request


def call_provider(
    config: ModelConfig,
    prompt: str,
    max_output_tokens: int | None,
    max_attempts: int = MAX_ATTEMPTS,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    if config.provider == "openai_responses":
        return _call_openai_responses(config, prompt, max_output_tokens, max_attempts)
    if config.provider == "gemini":
        return _call_gemini(config, prompt, max_output_tokens, max_attempts)
    return _call_openai_compatible(config, prompt, max_output_tokens, max_attempts)


def sanitize_error_message(message: str) -> str:
    message = SENSITIVE_QUERY_RE.sub(r"\1***", message)
    return BEARER_TOKEN_RE.sub(r"\1***", message)


def _base_url(config: ModelConfig) -> str:
    return (config.base_url or DEFAULT_BASE_URLS.get(config.provider, "")).rstrip("/")


def _request_timeout(config: ModelConfig) -> float:
    return PROVIDER_TIMEOUT_SECONDS.get(config.provider, REQUEST_TIMEOUT_SECONDS)


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


def _redacted_headers(headers: dict[str, str]) -> dict[str, str]:
    return {
        key: ("Bearer ***" if key.lower() == "authorization" else "***" if key.lower() == "x-goog-api-key" else value)
        for key, value in headers.items()
    }


def _request_record(
    *,
    provider: str,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    max_attempts: int,
    params: dict[str, Any] | None = None,
    timeout_seconds: float = REQUEST_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    return {
        "provider": provider,
        "url": sanitize_error_message(url),
        "method": "POST",
        "headers": _redacted_headers(headers),
        "params": _redacted_params(params),
        "json": payload,
        "timeoutSeconds": timeout_seconds,
        "maxAttempts": max_attempts,
    }


def _redacted_params(params: dict[str, Any] | None) -> dict[str, Any] | None:
    if not params:
        return None
    return {
        key: "***" if key.lower() in {"key", "api_key", "access_token"} else value
        for key, value in params.items()
    }


def _model_name(config: ModelConfig) -> str:
    provider_aliases = PROVIDER_MODEL_ALIASES.get(config.provider, {})
    if config.model in provider_aliases:
        return provider_aliases[config.model]
    return MODEL_ALIASES.get(config.model, config.model)


def _chat_template_kwargs(config: ModelConfig) -> dict[str, Any] | None:
    return PROVIDER_MODEL_CHAT_TEMPLATE_KWARGS.get(config.provider, {}).get(config.model)


def _max_output_tokens(config: ModelConfig, override: int | None) -> int:
    return override if override is not None else config.max_output_tokens


def _retry_delay(attempt: int) -> float:
    return 0.4 * (2**attempt)


def _post_with_retry(client: httpx.Client, url: str, max_attempts: int = MAX_ATTEMPTS, **kwargs: Any) -> httpx.Response:
    max_attempts = max(1, max_attempts)
    for attempt in range(max_attempts):
        try:
            response = client.post(url, **kwargs)
            if response.status_code in RETRYABLE_STATUS_CODES and attempt < max_attempts - 1:
                time.sleep(_retry_delay(attempt))
                continue
            response.raise_for_status()
            return response
        except RETRYABLE_TRANSPORT_ERRORS:
            if attempt >= max_attempts - 1:
                raise
            time.sleep(_retry_delay(attempt))
    raise RuntimeError("HTTP request failed after retries.")


def _call_openai_compatible(
    config: ModelConfig,
    prompt: str,
    max_output_tokens: int | None,
    max_attempts: int,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    base_url = _with_v1(_base_url(config))
    url = f"{base_url}/chat/completions"
    payload = {
        "model": _model_name(config),
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": _max_output_tokens(config, max_output_tokens),
    }
    chat_template_kwargs = _chat_template_kwargs(config)
    if chat_template_kwargs:
        payload["chat_template_kwargs"] = chat_template_kwargs
    if config.provider == "nvidia":
        payload["stream"] = True
    headers = _headers(config)
    timeout_seconds = _request_timeout(config)
    request = _request_record(
        provider=config.provider,
        url=url,
        headers=headers,
        payload=payload,
        max_attempts=max_attempts,
        timeout_seconds=timeout_seconds,
    )
    with httpx.Client(timeout=timeout_seconds) as client:
        try:
            if config.provider == "nvidia":
                text, raw = _stream_chat_completion(client, url, headers, payload)
                return text, raw, request
            response = _post_with_retry(
                client,
                url,
                max_attempts=max_attempts,
                headers=headers,
                json=payload,
            )
        except Exception as exc:
            raise ProviderCallError(str(exc), request) from exc
    raw = response.json()
    text = raw.get("choices", [{}])[0].get("message", {}).get("content") or ""
    return text.strip(), raw, request


def _stream_chat_completion(
    client: httpx.Client,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    with client.stream("POST", url, headers=headers, json=payload) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if not line:
                continue
            if line.startswith("data:"):
                line = line.removeprefix("data:").strip()
            if line == "[DONE]":
                break
            chunk = json.loads(line)
            chunks.append(chunk)
            delta = (chunk.get("choices") or [{}])[0].get("delta") or {}
            content = delta.get("content")
            if isinstance(content, str):
                content_parts.append(content)
            reasoning = delta.get("reasoning") or delta.get("reasoning_content")
            if isinstance(reasoning, str):
                reasoning_parts.append(reasoning)
    text = "".join(content_parts).strip()
    return text, {
        "stream": True,
        "chunks": chunks,
        "text": text,
        "reasoning": "".join(reasoning_parts).strip() or None,
    }


def _call_openai_responses(
    config: ModelConfig,
    prompt: str,
    max_output_tokens: int | None,
    max_attempts: int,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    base_url = _with_v1(_base_url(config))
    url = f"{base_url}/responses"
    payload = {
        "model": _model_name(config),
        "input": [{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
        "max_output_tokens": _max_output_tokens(config, max_output_tokens),
        "store": False,
    }
    headers = _headers(config)
    timeout_seconds = _request_timeout(config)
    request = _request_record(
        provider=config.provider,
        url=url,
        headers=headers,
        payload=payload,
        max_attempts=max_attempts,
        timeout_seconds=timeout_seconds,
    )
    with httpx.Client(timeout=timeout_seconds) as client:
        try:
            response = _post_with_retry(
                client,
                url,
                max_attempts=max_attempts,
                headers=headers,
                json=payload,
            )
        except Exception as exc:
            raise ProviderCallError(str(exc), request) from exc
    raw = response.json()
    return _extract_responses_text(raw), raw, request


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


def _call_gemini(
    config: ModelConfig,
    prompt: str,
    max_output_tokens: int | None,
    max_attempts: int,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
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
    params = {"key": api_key}
    headers = {"Content-Type": "application/json", "x-goog-api-key": api_key}
    timeout_seconds = _request_timeout(config)
    request = _request_record(
        provider=config.provider,
        url=url,
        headers=headers,
        params=params,
        payload=payload,
        max_attempts=max_attempts,
        timeout_seconds=timeout_seconds,
    )
    with httpx.Client(timeout=timeout_seconds) as client:
        try:
            response = _post_with_retry(
                client,
                url,
                max_attempts=max_attempts,
                params=params,
                headers=headers,
                json=payload,
            )
        except Exception as exc:
            raise ProviderCallError(str(exc), request) from exc
    raw = response.json()
    parts = raw.get("candidates", [{}])[0].get("content", {}).get("parts", []) or []
    text = "\n".join(str(part.get("text", "")) for part in parts if isinstance(part, dict)).strip()
    return text, raw, request
