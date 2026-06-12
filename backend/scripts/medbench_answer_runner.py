from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from sqlalchemy import select


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.database import get_sessionmaker  # noqa: E402
from app.llm import providers as llm_providers  # noqa: E402
from app.llm.client import call_model  # noqa: E402
from app.models import ModelConfig  # noqa: E402


DEFAULT_DATABASE_URL = "postgresql+psycopg://test_benchmark:test_benchmark@localhost:18112/test_benchmark"
DEFAULT_DATASET_DIR = REPO_ROOT / "data/benchmarks/MedBench_LLM"
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "reports/MedBench_LLM_answers"
DEFAULT_FILE_NAME = "MedMC.jsonl"
DEFAULT_FILE_NAMES = ("MedMC.jsonl", "MedHC.jsonl", "MedSpeQA.jsonl", "MedHG.jsonl", "MedPrimary.jsonl", "MedDiag.jsonl")
DEFAULT_MODEL_NAMES = ("AntAngelMed", "DeepSeek-v4-pro", "qwen3.7-plus", "gpt-5.5", "Gemini-3.5-flash")
LOG_LOCK = Lock()
RUN_LOG_PATH: Path | None = None
CALL_LOG_PATH: Path | None = None


PAYMENT_ERROR_PATTERNS = (
    "402",
    "payment required",
    "insufficient credit",
    "insufficient credits",
    "insufficient balance",
    "insufficient funds",
)


@dataclass(frozen=True)
class ModelTarget:
    display_name: str
    provider_options: tuple[str, ...]
    model_names: tuple[str, ...]


@dataclass(frozen=True)
class SelectedModel:
    target: ModelTarget
    config: ModelConfig


@dataclass(frozen=True)
class ModelRunSummary:
    model_name: str
    answer_path: Path
    total: int
    attempted_this_run: int
    answered_this_run: int
    failures: int
    remaining: int


MODEL_TARGETS = {
    "AntAngelMed": ModelTarget("AntAngelMed", ("ant_ling",), ("AntAngelMed",)),
    "DeepSeek-v4-pro": ModelTarget("DeepSeek-v4-pro", ("deepseek",), ("DeepSeek-v4-pro", "deepseek-v4-pro")),
    "qwen3.7-plus": ModelTarget("qwen3.7-plus", ("qwen",), ("qwen3.7-plus",)),
    "gpt-5.5": ModelTarget("gpt-5.5", ("openai_responses",), ("gpt-5.5",)),
    "Gemini-3.5-flash": ModelTarget("Gemini-3.5-flash", ("openrouter",), ("google/gemini-3.5-flash",)),
    "Gemini-3.5-flash-Google": ModelTarget("Gemini-3.5-flash", ("gemini",), ("Gemini-3.5-flash", "gemini-3.5-flash")),
}


def is_payment_error(error: str | None) -> bool:
    text = (error or "").lower()
    return any(pattern in text for pattern in PAYMENT_ERROR_PATTERNS)


def main() -> int:
    args = parse_args()
    configure_log_paths(args.output_root, args.run_log, args.call_log)
    os.environ["DATABASE_URL"] = args.database_url or os.getenv("DATABASE_URL") or DEFAULT_DATABASE_URL
    prefer_http_proxy_over_socks_fallback()
    configure_provider_timeout(args.request_timeout)

    targets = parse_model_targets(args.model)
    source_paths = resolve_source_paths(args.file, args.dataset_dir, args.all_medbench_files)
    selected_models = load_model_configs(targets)

    parallel_models = min(max(1, args.parallel_models), len(selected_models))
    parallel_files = min(max(1, args.parallel_files), len(source_paths))
    total_workers = min(parallel_models * parallel_files, len(selected_models) * len(source_paths))
    log("sources:")
    for source_path in source_paths:
        log(f"- {source_path}")
    log(f"models: {len(selected_models)}, parallel_models: {parallel_models}")
    log(f"files: {len(source_paths)}, parallel_files: {parallel_files}, total_workers: {total_workers}")
    for selected_model in selected_models:
        log(
            "model: "
            f"{selected_model.target.display_name} -> config #{selected_model.config.id} "
            f"{selected_model.config.provider}/{selected_model.config.model}"
        )

    summaries: list[ModelRunSummary] = []
    with ThreadPoolExecutor(max_workers=total_workers) as executor:
        futures = {
            executor.submit(run_model_file, selected_model, source_path, args): (selected_model, source_path)
            for selected_model in selected_models
            for source_path in source_paths
        }
        for future in as_completed(futures):
            selected_model, source_path = futures[future]
            try:
                summaries.append(future.result())
            except Exception as exc:
                log(f"[{selected_model.target.display_name}] [{source_path.name}] failed: {exc}")
                summaries.append(
                    ModelRunSummary(
                        model_name=selected_model.target.display_name,
                        answer_path=args.output_root / safe_dir_name(selected_model.target.display_name) / source_path.name,
                        total=0,
                        attempted_this_run=0,
                        answered_this_run=0,
                        failures=1,
                        remaining=0,
                    )
                )

    log("summary:")
    for summary in sorted(summaries, key=lambda item: item.model_name):
        log(
            f"- {summary.model_name}: attempted_this_run={summary.attempted_this_run}, "
            f"answered_this_run={summary.answered_this_run}, "
            f"failures={summary.failures}, remaining={summary.remaining}, file={summary.answer_path}"
        )
    return 0 if all(summary.failures == 0 for summary in summaries) else 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one configured model against one MedBench_LLM jsonl file and fill the answer field."
    )
    parser.add_argument(
        "--model",
        action="append",
        default=None,
        help=(
            "Model target. Repeat to run a subset, or use provider/model. "
            f"Default: {', '.join(DEFAULT_MODEL_NAMES)}."
        ),
    )
    parser.add_argument(
        "--file",
        action="append",
        default=None,
        help="Jsonl file name/path. Repeat to run multiple files. Default: MedMC.jsonl.",
    )
    parser.add_argument(
        "--all-medbench-files",
        action="store_true",
        help=f"Run the six MedBench_LLM files: {', '.join(DEFAULT_FILE_NAMES)}.",
    )
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET_DIR)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--run-log", type=Path, default=None, help="Human-readable run log path.")
    parser.add_argument("--call-log", type=Path, default=None, help="JSONL model call log path.")
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--max-output-tokens", type=int, default=None)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--request-timeout", type=float, default=120.0, help="HTTP timeout seconds per provider request.")
    parser.add_argument("--limit", type=int, default=None, help="Maximum unanswered rows to attempt per model this run.")
    parser.add_argument("--parallel-models", type=int, default=len(DEFAULT_MODEL_NAMES), help="How many models to run concurrently.")
    parser.add_argument("--parallel-files", type=int, default=1, help="How many files to run concurrently.")
    parser.add_argument(
        "--stop-after-consecutive-failures",
        type=int,
        default=3,
        help="Stop one model for the current file after this many consecutive failed calls. Use 0 to disable.",
    )
    return parser.parse_args()


def parse_model_targets(values: list[str] | None) -> tuple[ModelTarget, ...]:
    if not values:
        return tuple(MODEL_TARGETS[name] for name in DEFAULT_MODEL_NAMES)
    targets: list[ModelTarget] = []
    seen: set[tuple[tuple[str, ...], tuple[str, ...]]] = set()
    for raw_value in values:
        for value in raw_value.split(","):
            target = parse_model_target(value)
            key = (target.provider_options, target.model_names)
            if key not in seen:
                targets.append(target)
                seen.add(key)
    return tuple(targets)


def parse_model_target(value: str) -> ModelTarget:
    value = value.strip()
    if value == "all":
        raise SystemExit("Use no --model argument to run all default models.")
    if value in MODEL_TARGETS:
        return MODEL_TARGETS[value]
    if "/" in value:
        provider, model = value.split("/", 1)
        provider = provider.strip()
        model = model.strip()
        return ModelTarget(model, (provider,), (model,))
    raise SystemExit(f"Unknown model target: {value}. Known: {', '.join(MODEL_TARGETS)}")


def resolve_source_path(file_value: str, dataset_dir: Path) -> Path:
    path = Path(file_value)
    if not path.is_absolute():
        path = dataset_dir / path
    path = path.resolve()
    if not path.exists():
        raise SystemExit(f"Source file not found: {path}")
    if path.suffix != ".jsonl":
        raise SystemExit(f"Source file must be .jsonl: {path}")
    return path


def resolve_source_paths(file_values: list[str] | None, dataset_dir: Path, all_medbench_files: bool) -> tuple[Path, ...]:
    selected_values = list(file_values or [])
    if all_medbench_files or any(value == "all" for value in selected_values):
        selected_values = list(DEFAULT_FILE_NAMES)
    if not selected_values:
        selected_values = [DEFAULT_FILE_NAME]
    paths: list[Path] = []
    seen: set[Path] = set()
    for file_value in selected_values:
        path = resolve_source_path(file_value, dataset_dir)
        if path not in seen:
            paths.append(path)
            seen.add(path)
    return tuple(paths)


def ensure_answer_file(source_path: Path, output_root: Path, model_name: str) -> Path:
    model_dir = output_root / safe_dir_name(model_name)
    model_dir.mkdir(parents=True, exist_ok=True)
    answer_path = model_dir / source_path.name
    if not answer_path.exists():
        shutil.copy2(source_path, answer_path)
        log(f"copied source to answer file: {answer_path}")
    return answer_path


def safe_dir_name(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
    return safe or "model"


def load_model_configs(targets: tuple[ModelTarget, ...]) -> list[SelectedModel]:
    SessionLocal = get_sessionmaker()
    with SessionLocal() as db:
        selected: list[SelectedModel] = []
        missing: list[str] = []
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
            if candidates:
                selected.append(SelectedModel(target=target, config=candidates[0]))
            else:
                missing.append(
                    f"{target.display_name}: providers={target.provider_options}, models={target.model_names}"
                )
    if missing:
        raise SystemExit(
            "No enabled model config found for:\n- " + "\n- ".join(missing)
        )
    return selected


def run_model_file(selected_model: SelectedModel, source_path: Path, args: argparse.Namespace) -> ModelRunSummary:
    model_name = selected_model.target.display_name
    log_prefix = f"[{model_name}] [{source_path.name}]"
    answer_path = ensure_answer_file(source_path, args.output_root, model_name)
    rows = read_jsonl(answer_path)
    total = len(rows)
    unanswered = sum(1 for row in rows if not has_answer(row))
    log(f"{log_prefix} answers: {answer_path}")
    log(f"{log_prefix} rows: {total}, unanswered: {unanswered}")

    attempted_this_run = 0
    answered_this_run = 0
    failures = 0
    consecutive_failures = 0
    for index, row in enumerate(rows, start=1):
        if has_answer(row):
            log(f"{log_prefix} [{index}/{total}] skip answered")
            consecutive_failures = 0
            continue
        if args.limit is not None and attempted_this_run >= args.limit:
            log(f"{log_prefix} limit reached: {args.limit}")
            break
        if (
            args.stop_after_consecutive_failures > 0
            and consecutive_failures >= args.stop_after_consecutive_failures
        ):
            log(
                f"{log_prefix} stopped after {consecutive_failures} consecutive failures; "
                "rerun later to continue"
            )
            break

        question = normalize_text(row.get("question"))
        if not question:
            failures += 1
            log(f"{log_prefix} [{index}/{total}] skip empty question")
            continue

        attempted_this_run += 1
        log(f"{log_prefix} [{index}/{total}] call start")
        result = call_model(
            selected_model.config,
            question,
            max_output_tokens=args.max_output_tokens,
            max_attempts=args.max_attempts,
        )
        append_call_log(
            selected_model=selected_model,
            source_path=source_path,
            answer_path=answer_path,
            row_index=index,
            total=total,
            question=question,
            result=result,
        )
        if not result.ok:
            failures += 1
            consecutive_failures += 1
            log(f"{log_prefix} [{index}/{total}] call failed latency={result.latency_ms}ms error={result.error}")
            if is_payment_error(result.error):
                log(
                    f"{log_prefix} payment-related error detected; "
                    "stop this model/file and rerun after billing is fixed"
                )
                break
            continue

        answer = normalize_text(result.text)
        if not answer:
            failures += 1
            consecutive_failures += 1
            log(f"{log_prefix} [{index}/{total}] empty response latency={result.latency_ms}ms")
            continue

        row["answer"] = answer
        atomic_write_jsonl(answer_path, rows)
        answered_this_run += 1
        consecutive_failures = 0
        log(f"{log_prefix} [{index}/{total}] answer saved latency={result.latency_ms}ms chars={len(answer)}")

    remaining = sum(1 for row in rows if not has_answer(row))
    log(
        f"{log_prefix} done: attempted_this_run={attempted_this_run}, "
        f"answered_this_run={answered_this_run}, failures={failures}, remaining={remaining}"
    )
    return ModelRunSummary(
        model_name=model_name,
        answer_path=answer_path,
        total=total,
        attempted_this_run=attempted_this_run,
        answered_this_run=answered_this_run,
        failures=failures,
        remaining=remaining,
    )


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"Invalid JSON at {path}:{line_number}: {exc}") from exc
            if not isinstance(row, dict):
                raise SystemExit(f"Expected JSON object at {path}:{line_number}")
            rows.append(row)
    return rows


def atomic_write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    tmp_path = path.with_name(f".{path.name}.tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False))
            handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_path, path)


def has_answer(row: dict[str, Any]) -> bool:
    return bool(normalize_text(row.get("answer")))


def normalize_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def prefer_http_proxy_over_socks_fallback() -> None:
    if os.getenv("https_proxy") or os.getenv("HTTPS_PROXY"):
        os.environ.pop("all_proxy", None)
        os.environ.pop("ALL_PROXY", None)


def configure_provider_timeout(timeout_seconds: float) -> None:
    llm_providers.REQUEST_TIMEOUT_SECONDS = timeout_seconds


def configure_log_paths(output_root: Path, run_log: Path | None, call_log: Path | None) -> None:
    global RUN_LOG_PATH, CALL_LOG_PATH
    RUN_LOG_PATH = run_log or output_root / "run.log"
    CALL_LOG_PATH = call_log or output_root / "calls.jsonl"
    RUN_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CALL_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)


def log(message: str) -> None:
    with LOG_LOCK:
        print(message, flush=True)
        if RUN_LOG_PATH is not None:
            with RUN_LOG_PATH.open("a", encoding="utf-8") as handle:
                handle.write(f"{utc_timestamp()} {message}\n")


def append_call_log(
    *,
    selected_model: SelectedModel,
    source_path: Path,
    answer_path: Path,
    row_index: int,
    total: int,
    question: str,
    result: Any,
) -> None:
    record = {
        "timestamp": utc_timestamp(),
        "source_file": source_path.name,
        "source_path": str(source_path),
        "answer_path": str(answer_path),
        "row_index": row_index,
        "total_rows": total,
        "model_name": selected_model.target.display_name,
        "model_config_id": selected_model.config.id,
        "provider": selected_model.config.provider,
        "model": selected_model.config.model,
        "prompt": question,
        "ok": result.ok,
        "latency_ms": result.latency_ms,
        "text": result.text,
        "error": result.error,
        "request": result.request,
        "raw_response": result.raw_response,
    }
    with LOG_LOCK:
        if CALL_LOG_PATH is not None:
            with CALL_LOG_PATH.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False, default=str))
                handle.write("\n")


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
