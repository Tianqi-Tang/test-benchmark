from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import re
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.etree import ElementTree
from xml.sax.saxutils import escape, unescape

import httpx
from sqlalchemy import select


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.database import get_sessionmaker  # noqa: E402
from app.models import ModelConfig  # noqa: E402


SENSITIVE_QUERY_RE = re.compile(r"([?&](?:key|api_key|access_token)=)[^&\s'\"]+")
BEARER_TOKEN_RE = re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]+")
DEFAULT_DATABASE_URL = "postgresql+psycopg://test_benchmark:test_benchmark@localhost:18112/test_benchmark"
DEFAULT_IMAGE_DIR = Path("/Users/raymond/Desktop/AI/AIA/model-test/images")
DEFAULT_IMAGE_PATH = DEFAULT_IMAGE_DIR / "检查单1.jpg"
DEFAULT_OUTPUT_PATH = Path("reports/vision-image-report-three-models-all-images.xlsx")
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
DEFAULT_BASE_URLS = {
    "openai_responses": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "gemini": "https://generativelanguage.googleapis.com",
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "qwen_vision": "https://dashscope.aliyuncs.com/compatible-mode/v1",
}
PROVIDER_MODEL_ALIASES = {
    ("gemini", "Gemini-3.5-flash"): "gemini-3.5-flash",
}
DEFAULT_PROMPT = """\
你是医学视觉识别助手。请只根据图片内容进行识别，不要猜测图片之外的信息。

请输出一个 JSON 对象，不要使用 Markdown 代码块，字段如下：
{
  "image_type": "检查单 / 检验单 / 药盒 / 其他",
  "summary": "用中文简要概括图片中的核心内容",
  "items": [
    {
      "name": "可读出的项目名或药品信息",
      "value": "结果、规格或读数",
      "unit": "单位，没有则为空字符串",
      "reference_range": "参考范围，没有则为空字符串",
      "status": "正常 / 偏高 / 偏低 / 阳性 / 阴性 / 需关注 / 已读取 / 无法判断"
    }
  ],
  "conclusion": "基于图片本身的简短结论或需要关注的点",
  "limitations": "看不清、缺失或无法判断的内容"
}

要求：
- items 最多 12 项，优先列出异常项、关键结果、药品名称/规格等重要信息。
- 所有输出必须是中文。
- 如果图片不是医疗图片，也请按实际内容说明。
"""


@dataclass(frozen=True)
class ModelTarget:
    display_name: str
    provider_options: tuple[str, ...]
    model_names: tuple[str, ...]


DEFAULT_MODEL_TARGETS = (
    ModelTarget("ChatGPT gpt-5.5", ("openai_responses",), ("gpt-5.5",)),
    ModelTarget("Alibaba Qwen qwen3.7-plus", ("qwen_vision", "qwen"), ("qwen3.7-plus",)),
)
MODEL_TARGETS = {
    "gpt-5.5": DEFAULT_MODEL_TARGETS[0],
    "qwen3.7-plus": DEFAULT_MODEL_TARGETS[1],
    "Gemini-3.5-flash": ModelTarget("Gemini-3.5-flash", ("openrouter",), ("google/gemini-3.5-flash",)),
    "Gemini-3.5-flash-Google": ModelTarget("Gemini-3.5-flash", ("gemini",), ("Gemini-3.5-flash", "gemini-3.5-flash")),
}


@dataclass(frozen=True)
class VisionRunConfig:
    image_paths: tuple[Path, ...]
    output_path: Path
    prompt: str
    max_output_tokens: int
    timeout_seconds: float
    database_url: str


@dataclass(frozen=True)
class SelectedModel:
    target: ModelTarget
    config: ModelConfig | None
    error: str = ""


def main() -> int:
    args = parse_args()
    config = VisionRunConfig(
        image_paths=tuple(resolve_image_paths(args.image, args.image_dir)),
        output_path=args.output,
        prompt=args.prompt,
        max_output_tokens=args.max_output_tokens,
        timeout_seconds=args.timeout,
        database_url=args.database_url or os.getenv("DATABASE_URL") or DEFAULT_DATABASE_URL,
    )
    os.environ["DATABASE_URL"] = config.database_url

    selected_models = load_selected_models(parse_model_targets(args.model))
    rows: list[dict[str, str]] = [row for row in read_existing_rows(config.output_path) if row.get("status") == "success"]
    completed = completed_keys(rows)

    log(f"images: {len(config.image_paths)}")
    log(f"report: {config.output_path.resolve()}")
    log(f"models: {len(selected_models)}")
    log(f"existing rows: {len(rows)}, completed successes: {len(completed)}")
    total_tasks = len(config.image_paths) * len(selected_models)
    completed_or_skipped = 0
    for image_path in config.image_paths:
        pending: list[tuple[int, SelectedModel]] = []
        for selected_model in selected_models:
            completed_or_skipped += 1
            key = report_key(image_path.name, selected_model)
            if key in completed:
                log(f"[{completed_or_skipped}/{total_tasks}] skip completed: {image_path.name} {key[1]}/{key[2]}")
                continue
            pending.append((completed_or_skipped, selected_model))
        if not pending:
            continue
        log(f"image batch: {image_path.name}, parallel calls: {len(pending)}")
        with ThreadPoolExecutor(max_workers=len(pending)) as executor:
            futures = {
                executor.submit(run_single_image, image_path, selected_model, config, index, total_tasks): (index, selected_model)
                for index, selected_model in pending
            }
            for future in as_completed(futures):
                row = future.result()
                rows.append(row)
                if row["status"] == "success":
                    completed.add((row["file_name"], row["provider"], row["model"]))
                write_xlsx(config.output_path, rows)
                log(f"[{futures[future][0]}/{total_tasks}] report updated: {config.output_path.resolve()}")

    log("summary:")
    for row in rows:
        log(f"- {row['model_name']} ({row['provider']}/{row['model']}): {row['status']} {row['latency_ms']}ms")
        if row["error"]:
            log(f"  error: {row['error']}")
    log(f"done: {config.output_path.resolve()}")
    return 0 if any(row["status"] == "success" for row in rows) else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run configured vision models against images and write an XLSX report.")
    parser.add_argument("--image", type=Path, default=None, help="Single image path to recognize.")
    parser.add_argument("--image-dir", type=Path, default=DEFAULT_IMAGE_DIR, help="Directory of images to recognize when --image is omitted.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH, help="Output .xlsx path.")
    parser.add_argument(
        "--model",
        action="append",
        default=None,
        help="Optional provider/model target such as openrouter/google/gemini-3.5-flash, or a named target such as Gemini-3.5-flash. Repeat to run a subset. Defaults to gpt-5.5 and qwen3.7-plus.",
    )
    parser.add_argument("--prompt", default=DEFAULT_PROMPT, help="Prompt sent with the image.")
    parser.add_argument("--max-output-tokens", type=int, default=2000)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--database-url", default=None, help="PostgreSQL URL. Defaults to DATABASE_URL or local dev database.")
    return parser.parse_args()


def resolve_image_paths(image: Path | None, image_dir: Path) -> list[Path]:
    if image is not None:
        return [image]
    paths = [
        path
        for path in image_dir.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    ]
    return sorted(paths, key=lambda path: path.name)


def parse_model_targets(values: list[str] | None) -> tuple[ModelTarget, ...]:
    if not values:
        return DEFAULT_MODEL_TARGETS
    targets: list[ModelTarget] = []
    for value in values:
        if value in MODEL_TARGETS:
            targets.append(MODEL_TARGETS[value])
        elif "/" in value:
            provider, model = value.split("/", 1)
            targets.append(ModelTarget(value, (provider.strip(),), (model.strip(),)))
        else:
            model = value.strip()
            targets.append(ModelTarget(model, ("openai_responses", "openrouter", "gemini", "qwen_vision", "qwen"), (model,)))
    return tuple(targets)


def load_selected_models(targets: tuple[ModelTarget, ...]) -> list[SelectedModel]:
    SessionLocal = get_sessionmaker()
    with SessionLocal() as db:
        selected: list[SelectedModel] = []
        for target in targets:
            candidates = list(
                db.scalars(
                    select(ModelConfig)
                    .where(
                        ModelConfig.enabled.is_(True),
                        ModelConfig.provider.in_(target.provider_options),
                        ModelConfig.model.in_(target.model_names),
                    )
                    .order_by(ModelConfig.id)
                )
            )
            model_config = next((candidate for candidate in candidates if supports_capability(candidate, "vision")), None)
            if model_config is None:
                selected.append(SelectedModel(target=target, config=None, error=missing_model_message(target)))
                continue
            if not (model_config.api_key or "").strip():
                selected.append(SelectedModel(target=target, config=model_config, error=f"Model config {model_config.id} has no API key."))
                continue
            selected.append(SelectedModel(target=target, config=model_config))
    return selected


def missing_model_message(target: ModelTarget) -> str:
    providers = ", ".join(target.provider_options)
    models = ", ".join(target.model_names)
    return f"No enabled vision model config was found for providers [{providers}] and models [{models}]."


def log(message: str) -> None:
    print(sanitize_error_message(message), flush=True)


def sanitize_error_message(message: str) -> str:
    message = SENSITIVE_QUERY_RE.sub(r"\1***", message)
    return BEARER_TOKEN_RE.sub(r"\1***", message)


def report_key(file_name: str, selected_model: SelectedModel) -> tuple[str, str, str]:
    model_config = selected_model.config
    if model_config is None:
        return (file_name, ",".join(selected_model.target.provider_options), ",".join(selected_model.target.model_names))
    return (file_name, model_config.provider, model_config.model)


def completed_keys(rows: list[dict[str, str]]) -> set[tuple[str, str, str]]:
    return {
        (row.get("file_name", ""), row.get("provider", ""), row.get("model", ""))
        for row in rows
        if row.get("status") == "success"
    }


def supports_capability(model_config: ModelConfig, capability: str) -> bool:
    return capability.lower() in {part.strip().lower() for part in (model_config.capability or "").split(",") if part.strip()}


def run_single_image(image_path: Path, selected_model: SelectedModel, config: VisionRunConfig, index: int, total: int) -> dict[str, str]:
    row = empty_report_row(selected_model, image_path)
    if selected_model.error:
        log(f"[{index}/{total}] skip: {row['model_name']} ({row['provider']}/{row['model']})")
        log(f"[{index}/{total}] error: {selected_model.error}")
        row["status"] = "failed"
        row["error"] = selected_model.error
        return row

    model_config = selected_model.config
    if model_config is None:
        row["status"] = "failed"
        row["error"] = missing_model_message(selected_model.target)
        return row

    started = time.perf_counter()
    log(f"[{index}/{total}] start: {image_path.name} -> {model_config.name} ({model_config.provider}/{model_config.model})")
    log(f"[{index}/{total}] endpoint: {vision_endpoint(model_config)}")
    try:
        image_path.expanduser().resolve(strict=True)
        text = call_vision_model(
            model_config=model_config,
            image_path=image_path,
            prompt=config.prompt,
            max_output_tokens=config.max_output_tokens,
            timeout_seconds=config.timeout_seconds,
        )
        parsed = parse_json_object(text)
        row.update(
            {
                "status": "success",
                "image_type": str(parsed.get("image_type", "")) if parsed else "",
                "summary": str(parsed.get("summary", "")) if parsed else "",
                "items": format_items(parsed.get("items")) if parsed else "",
                "conclusion": str(parsed.get("conclusion", "")) if parsed else "",
                "limitations": str(parsed.get("limitations", "")) if parsed else "",
                "raw_output": text,
            }
        )
    except Exception as exc:
        row["status"] = "failed"
        row["error"] = sanitize_error_message(str(exc))
        log(f"[{index}/{total}] failed: {model_config.name}: {row['error']}")
    finally:
        row["latency_ms"] = str(int((time.perf_counter() - started) * 1000))
        log(f"[{index}/{total}] finished: {model_config.name} latency={row['latency_ms']}ms status={row['status']}")
    return row


def empty_report_row(selected_model: SelectedModel, image_path: Path) -> dict[str, str]:
    model_config = selected_model.config
    return {
        "file_name": image_path.name,
        "image_path": str(image_path),
        "model_config_id": str(model_config.id) if model_config is not None else "",
        "model_name": model_config.name if model_config is not None else selected_model.target.display_name,
        "provider": model_config.provider if model_config is not None else ",".join(selected_model.target.provider_options),
        "model": model_config.model if model_config is not None else ",".join(selected_model.target.model_names),
        "status": "",
        "image_type": "",
        "summary": "",
        "items": "",
        "conclusion": "",
        "limitations": "",
        "raw_output": "",
        "error": "",
        "latency_ms": "",
    }


def call_vision_model(
    *,
    model_config: ModelConfig,
    image_path: Path,
    prompt: str,
    max_output_tokens: int,
    timeout_seconds: float,
) -> str:
    if model_config.provider == "openai_responses":
        return call_openai_responses_image(
            model_config=model_config,
            image_path=image_path,
            prompt=prompt,
            max_output_tokens=max_output_tokens,
            timeout_seconds=timeout_seconds,
        )
    if model_config.provider == "openrouter":
        return call_openai_compatible_vision_image(
            model_config=model_config,
            image_path=image_path,
            prompt=prompt,
            max_output_tokens=max_output_tokens,
            timeout_seconds=timeout_seconds,
        )
    if model_config.provider == "gemini":
        return call_gemini_image(
            model_config=model_config,
            image_path=image_path,
            prompt=prompt,
            max_output_tokens=max_output_tokens,
            timeout_seconds=timeout_seconds,
        )
    if model_config.provider in {"qwen", "qwen_vision"}:
        return call_qwen_vision_image(
            model_config=model_config,
            image_path=image_path,
            prompt=prompt,
            max_output_tokens=max_output_tokens,
            timeout_seconds=timeout_seconds,
        )
    raise RuntimeError(f"Unsupported vision provider: {model_config.provider}")


def vision_endpoint(model_config: ModelConfig) -> str:
    if model_config.provider == "openai_responses":
        return f"{with_v1(model_config.base_url or DEFAULT_BASE_URLS['openai_responses'])}/responses"
    if model_config.provider == "openrouter":
        return f"{with_v1(model_config.base_url or DEFAULT_BASE_URLS['openrouter'])}/chat/completions"
    if model_config.provider == "gemini":
        return f"{(model_config.base_url or DEFAULT_BASE_URLS['gemini']).rstrip('/')}/v1beta/models/{model_name(model_config)}:generateContent"
    if model_config.provider in {"qwen", "qwen_vision"}:
        return f"{with_v1(model_config.base_url or DEFAULT_BASE_URLS['qwen_vision'])}/chat/completions"
    return f"unsupported:{model_config.provider}"


def call_openai_responses_image(
    *,
    model_config: ModelConfig,
    image_path: Path,
    prompt: str,
    max_output_tokens: int,
    timeout_seconds: float,
) -> str:
    base_url = with_v1(model_config.base_url or DEFAULT_BASE_URLS["openai_responses"])
    payload = build_openai_responses_image_payload(
        model=model_name(model_config),
        prompt=prompt,
        image_data_url=image_data_url(image_path),
        max_output_tokens=max_output_tokens,
    )
    headers = {
        "Authorization": f"Bearer {(model_config.api_key or '').strip()}",
        "Content-Type": "application/json",
    }
    with http_client(timeout_seconds) as client:
        response = client.post(f"{base_url}/responses", headers=headers, json=payload)
        raise_for_status_with_body(response)
    text = extract_responses_text(response.json())
    if not text:
        raise RuntimeError("The model returned an empty response.")
    return text.strip()


def call_gemini_image(
    *,
    model_config: ModelConfig,
    image_path: Path,
    prompt: str,
    max_output_tokens: int,
    timeout_seconds: float,
) -> str:
    api_key = (model_config.api_key or "").strip()
    base_url = (model_config.base_url or DEFAULT_BASE_URLS["gemini"]).rstrip("/")
    payload = build_gemini_image_payload(
        prompt=prompt,
        image_bytes=image_path.read_bytes(),
        mime_type=image_mime_type(image_path),
        max_output_tokens=max_output_tokens,
    )
    headers = {"Content-Type": "application/json", "x-goog-api-key": api_key}
    with http_client(timeout_seconds) as client:
        response = client.post(
            f"{base_url}/v1beta/models/{model_name(model_config)}:generateContent",
            params={"key": api_key},
            headers=headers,
            json=payload,
        )
        raise_for_status_with_body(response)
    text = extract_gemini_text(response.json())
    if not text:
        raise RuntimeError("The model returned an empty response.")
    return text.strip()


def call_qwen_vision_image(
    *,
    model_config: ModelConfig,
    image_path: Path,
    prompt: str,
    max_output_tokens: int,
    timeout_seconds: float,
) -> str:
    base_url = with_v1(model_config.base_url or DEFAULT_BASE_URLS["qwen_vision"])
    payload = build_qwen_vision_image_payload(
        model=model_name(model_config),
        prompt=prompt,
        image_data_url=image_data_url(image_path),
        max_output_tokens=max_output_tokens,
    )
    headers = {
        "Authorization": f"Bearer {(model_config.api_key or '').strip()}",
        "Content-Type": "application/json",
    }
    with http_client(timeout_seconds) as client:
        response = client.post(f"{base_url}/chat/completions", headers=headers, json=payload)
        raise_for_status_with_body(response)
    text = extract_chat_completion_text(response.json())
    if not text:
        raise RuntimeError("The model returned an empty response.")
    return text.strip()


def call_openai_compatible_vision_image(
    *,
    model_config: ModelConfig,
    image_path: Path,
    prompt: str,
    max_output_tokens: int,
    timeout_seconds: float,
) -> str:
    base_url = with_v1(model_config.base_url or DEFAULT_BASE_URLS.get(model_config.provider, ""))
    payload = build_qwen_vision_image_payload(
        model=model_name(model_config),
        prompt=prompt,
        image_data_url=image_data_url(image_path),
        max_output_tokens=max_output_tokens,
    )
    headers = {
        "Authorization": f"Bearer {(model_config.api_key or '').strip()}",
        "Content-Type": "application/json",
    }
    with http_client(timeout_seconds) as client:
        response = client.post(f"{base_url}/chat/completions", headers=headers, json=payload)
        raise_for_status_with_body(response)
    text = extract_chat_completion_text(response.json())
    if not text:
        raise RuntimeError("The model returned an empty response.")
    return text.strip()


def raise_for_status_with_body(response: httpx.Response) -> None:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        body = response.text[:1000]
        raise RuntimeError(f"{exc}; response_body={body}") from exc


def with_v1(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    return normalized if normalized.endswith("/v1") else f"{normalized}/v1"


def model_name(model_config: ModelConfig) -> str:
    return PROVIDER_MODEL_ALIASES.get((model_config.provider, model_config.model), model_config.model)


def http_client(timeout_seconds: float) -> httpx.Client:
    proxy = os.getenv("https_proxy") or os.getenv("HTTPS_PROXY") or os.getenv("http_proxy") or os.getenv("HTTP_PROXY")
    if proxy:
        return httpx.Client(timeout=timeout_seconds, trust_env=False, proxy=proxy)
    return httpx.Client(timeout=timeout_seconds, trust_env=False)


def image_mime_type(image_path: Path) -> str:
    return mimetypes.guess_type(str(image_path))[0] or "image/jpeg"


def image_data_url(image_path: Path) -> str:
    mime_type = image_mime_type(image_path)
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def build_openai_responses_image_payload(
    *,
    model: str,
    prompt: str,
    image_data_url: str,
    max_output_tokens: int,
) -> dict[str, Any]:
    return {
        "model": model,
        "input": [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {"type": "input_image", "image_url": image_data_url},
                ],
            }
        ],
        "max_output_tokens": max_output_tokens,
        "store": False,
    }


def build_gemini_image_payload(
    *,
    prompt: str,
    image_bytes: bytes,
    mime_type: str,
    max_output_tokens: int,
) -> dict[str, Any]:
    return {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                    {
                        "inline_data": {
                            "mime_type": mime_type,
                            "data": base64.b64encode(image_bytes).decode("ascii"),
                        }
                    },
                ],
            }
        ],
        "generationConfig": {
            "temperature": 0.2,
            "topK": 40,
            "topP": 0.95,
            "maxOutputTokens": max_output_tokens,
        },
    }


def build_qwen_vision_image_payload(
    *,
    model: str,
    prompt: str,
    image_data_url: str,
    max_output_tokens: int,
) -> dict[str, Any]:
    return {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_data_url}},
                ],
            }
        ],
        "max_tokens": max_output_tokens,
        "temperature": 0.2,
    }


def extract_responses_text(payload: dict[str, Any]) -> str:
    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()
    parts: list[str] = []
    for item in payload.get("output", []) or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []) or []:
            if not isinstance(content, dict):
                continue
            text = content.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "\n".join(parts).strip()


def extract_gemini_text(payload: dict[str, Any]) -> str:
    parts: list[str] = []
    for candidate in payload.get("candidates", []) or []:
        if not isinstance(candidate, dict):
            continue
        content = candidate.get("content", {}) or {}
        for part in content.get("parts", []) or []:
            if not isinstance(part, dict):
                continue
            text = part.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "\n".join(parts).strip()


def extract_chat_completion_text(payload: dict[str, Any]) -> str:
    choices = payload.get("choices", []) or []
    if not choices or not isinstance(choices[0], dict):
        return ""
    message = choices[0].get("message", {}) or {}
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(parts).strip()
    return ""


def parse_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if not match:
            return {}
        try:
            value = json.loads(match.group(0))
        except json.JSONDecodeError:
            return {}
    return value if isinstance(value, dict) else {}


def format_items(value: Any) -> str:
    if not isinstance(value, list):
        return ""
    lines: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            lines.append(str(item))
            continue
        name = str(item.get("name", "")).strip()
        result = str(item.get("value", "")).strip()
        unit = str(item.get("unit", "")).strip()
        reference_range = str(item.get("reference_range", "")).strip()
        status = str(item.get("status", "")).strip()
        pieces = [piece for piece in [name, result, unit, f"参考范围: {reference_range}" if reference_range else "", status] if piece]
        lines.append(" | ".join(pieces))
    return "\n".join(lines)


REPORT_COLUMNS = [
    ("file_name", "文件名"),
    ("model_name", "模型配置名称"),
    ("provider", "Provider"),
    ("model", "Model"),
    ("status", "状态"),
    ("summary", "摘要"),
    ("items", "关键识别项"),
    ("conclusion", "结论"),
    ("limitations", "限制/不确定内容"),
    ("image_type", "图片类型"),
    ("latency_ms", "耗时ms"),
    ("error", "错误信息"),
    ("raw_output", "模型原始输出"),
    ("image_path", "图片路径"),
    ("model_config_id", "模型配置ID"),
]


def write_xlsx(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet_xml = build_sheet_xml(rows)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", CONTENT_TYPES_XML)
        archive.writestr("_rels/.rels", ROOT_RELS_XML)
        archive.writestr("xl/workbook.xml", WORKBOOK_XML)
        archive.writestr("xl/_rels/workbook.xml.rels", WORKBOOK_RELS_XML)
        archive.writestr("xl/styles.xml", STYLES_XML)
        archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)


def read_existing_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        legacy_path = Path("reports/vision-image-report-three-models-checklist1.xlsx")
        if path == DEFAULT_OUTPUT_PATH and legacy_path.exists():
            return read_existing_rows(legacy_path)
        return []
    try:
        with zipfile.ZipFile(path) as archive:
            shared_strings = read_shared_strings(archive)
            xml = archive.read("xl/worksheets/sheet1.xml")
    except Exception:
        return []

    namespace = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    root = ElementTree.fromstring(xml)
    parsed_rows: list[list[str]] = []
    for row_element in root.findall(".//main:sheetData/main:row", namespace):
        values: list[str] = []
        for cell in row_element.findall("main:c", namespace):
            cell_ref = cell.attrib.get("r", "")
            column_index = cell_column_index(cell_ref) if cell_ref else len(values)
            while len(values) <= column_index:
                values.append("")
            values[column_index] = read_cell_value(cell, shared_strings, namespace)
        parsed_rows.append(values)

    rows: list[dict[str, str]] = []
    for values in parsed_rows[1:]:
        row = {key: values[index] if index < len(values) else "" for index, (key, _label) in enumerate(REPORT_COLUMNS)}
        if row.get("file_name"):
            rows.append(row)
    return rows


def read_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    namespace = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
    values: list[str] = []
    for item in root.findall("main:si", namespace):
        parts = [text_element.text or "" for text_element in item.findall(".//main:t", namespace)]
        values.append(unescape("".join(parts)))
    return values


def read_cell_value(cell: ElementTree.Element, shared_strings: list[str], namespace: dict[str, str]) -> str:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        return unescape("".join(text_element.text or "" for text_element in cell.findall(".//main:t", namespace)))
    value_element = cell.find("main:v", namespace)
    value = value_element.text if value_element is not None and value_element.text is not None else ""
    if cell_type == "s" and value.isdigit():
        index = int(value)
        if 0 <= index < len(shared_strings):
            return shared_strings[index]
    return unescape(value)


def cell_column_index(cell_ref: str) -> int:
    letters = "".join(char for char in cell_ref if char.isalpha())
    index = 0
    for char in letters:
        index = index * 26 + ord(char.upper()) - ord("A") + 1
    return max(index - 1, 0)


def build_sheet_xml(rows: list[dict[str, str]]) -> str:
    xml_rows = [build_row_xml(1, [label for _key, label in REPORT_COLUMNS], style="1")]
    for index, row in enumerate(rows, start=2):
        xml_rows.append(build_row_xml(index, [row.get(key, "") for key, _label in REPORT_COLUMNS], style="2"))
    columns = "".join(f'<col min="{idx}" max="{idx}" width="{width}" customWidth="1"/>' for idx, width in enumerate(column_widths(), start=1))
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<cols>{columns}</cols>"
        "<sheetViews><sheetView workbookViewId=\"0\"><pane ySplit=\"1\" topLeftCell=\"A2\" activePane=\"bottomLeft\" state=\"frozen\"/></sheetView></sheetViews>"
        f"<sheetData>{''.join(xml_rows)}</sheetData>"
        f"<autoFilter ref=\"A1:{column_name(len(REPORT_COLUMNS))}1\"/>"
        "</worksheet>"
    )


def build_row_xml(row_index: int, values: list[str], style: str) -> str:
    cells = []
    for column_index, value in enumerate(values, start=1):
        cell_ref = f"{column_name(column_index)}{row_index}"
        safe_value = excel_cell_text(str(value))
        cells.append(f'<c r="{cell_ref}" s="{style}" t="inlineStr"><is><t>{safe_value}</t></is></c>')
    return f'<row r="{row_index}">{"".join(cells)}</row>'


def column_name(index: int) -> str:
    name = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


def column_widths() -> list[int]:
    return [18, 26, 18, 18, 12, 42, 66, 42, 38, 14, 12, 40, 88, 48, 12]


def excel_cell_text(value: str) -> str:
    value = "".join(ch for ch in value if ch == "\n" or ch == "\t" or ord(ch) >= 32)
    return escape(value[:32767], {'"': "&quot;"})


CONTENT_TYPES_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>"""

ROOT_RELS_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""

WORKBOOK_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="Vision Report" sheetId="1" r:id="rId1"/>
  </sheets>
</workbook>"""

WORKBOOK_RELS_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""

STYLES_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <fonts count="2">
    <font><sz val="11"/><name val="Arial"/></font>
    <font><b/><sz val="11"/><name val="Arial"/></font>
  </fonts>
  <fills count="2">
    <fill><patternFill patternType="none"/></fill>
    <fill><patternFill patternType="gray125"/></fill>
  </fills>
  <borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
  <cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
  <cellXfs count="3">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
    <xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1" applyAlignment="1"><alignment wrapText="1" vertical="top"/></xf>
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment wrapText="1" vertical="top"/></xf>
  </cellXfs>
  <cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>"""


if __name__ == "__main__":
    raise SystemExit(main())
