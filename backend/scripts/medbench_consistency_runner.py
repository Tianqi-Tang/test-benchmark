from __future__ import annotations

import argparse
import json
import os
import re
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from threading import Lock
from typing import Any
from unicodedata import normalize as unicode_normalize
from xml.sax.saxutils import escape


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.llm import providers as llm_providers  # noqa: E402
from app.llm.client import call_model  # noqa: E402
from scripts import medbench_answer_runner as answer_runner  # noqa: E402


DEFAULT_OUTPUT_ROOT = answer_runner.REPO_ROOT / "reports/MedBench_LLM_consistency"
DEFAULT_RAW_ROOT = DEFAULT_OUTPUT_ROOT / "raw_runs"
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_ROOT / "consistency_report.xlsx"
DEFAULT_ISSUES_PATH = DEFAULT_OUTPUT_ROOT / "consistency_issues.jsonl"
DEFAULT_RUN_LOG_PATH = DEFAULT_OUTPUT_ROOT / "run.log"
DEFAULT_CALL_LOG_PATH = DEFAULT_OUTPUT_ROOT / "calls.jsonl"
DEFAULT_ROUNDS = 3
SIMILARITY_THRESHOLD = 0.80
LENGTH_OUTLIER_RATIO = 0.50
LENGTH_OUTLIER_MIN_DELTA = 80
LOG_LOCK = Lock()
RUN_LOG_PATH: Path | None = None
CALL_LOG_PATH: Path | None = None


@dataclass(frozen=True)
class RoundRunSummary:
    model_name: str
    round_number: int
    answer_path: Path
    total: int
    attempted_this_run: int
    answered_this_run: int
    failures: int
    remaining: int


@dataclass(frozen=True)
class ConsistencyResult:
    status: str
    reason: str
    similarities: tuple[float | None, float | None, float | None]
    min_similarity: float | None
    lengths: tuple[int, ...]


def main() -> int:
    args = parse_args()
    configure_paths(args)
    os.environ["DATABASE_URL"] = args.database_url or os.getenv("DATABASE_URL") or answer_runner.DEFAULT_DATABASE_URL
    answer_runner.prefer_http_proxy_over_socks_fallback()
    configure_provider_timeout(args.request_timeout)

    targets = answer_runner.parse_model_targets(args.model)
    source_paths = answer_runner.resolve_source_paths(args.file, args.dataset_dir, args.all_medbench_files)
    selected_models = (
        selected_models_from_targets(targets)
        if args.report_only
        else answer_runner.load_model_configs(targets)
    )

    if not args.report_only:
        run_one_round(args, selected_models, source_paths)

    report_rows, issue_rows, summary_rows = build_report_rows(
        raw_root=args.raw_root,
        selected_models=selected_models,
        source_paths=source_paths,
        rounds=DEFAULT_ROUNDS,
        similarity_threshold=args.similarity_threshold,
    )
    write_xlsx(args.report, summary_rows, report_rows)
    write_issues_jsonl(args.issues, issue_rows)
    log(f"report written: {args.report.resolve()}")
    log(f"issues written: {args.issues.resolve()}")
    log(f"issue rows: {len(issue_rows)}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run MedBench_LLM questions repeatedly and produce a rule-based answer consistency report. "
            "The formal answer files are not modified."
        )
    )
    parser.add_argument(
        "--model",
        action="append",
        default=None,
        help=(
            "Model target. Repeat to run a subset, or use provider/model. "
            f"Default: {', '.join(answer_runner.DEFAULT_MODEL_NAMES)}."
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
        help=f"Run the six MedBench_LLM files: {', '.join(answer_runner.DEFAULT_FILE_NAMES)}.",
    )
    parser.add_argument("--dataset-dir", type=Path, default=answer_runner.DEFAULT_DATASET_DIR)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--raw-root", type=Path, default=None)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--issues", type=Path, default=None)
    parser.add_argument("--run-log", type=Path, default=None, help="Human-readable run log path.")
    parser.add_argument("--call-log", type=Path, default=None, help="JSONL model call log path.")
    parser.add_argument("--database-url", default=None)
    parser.add_argument(
        "--round",
        type=int,
        default=1,
        help="Repeated answer round to run. One script execution runs exactly one round.",
    )
    parser.add_argument("--max-output-tokens", type=int, default=None)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--request-timeout", type=float, default=120.0, help="HTTP timeout seconds per provider request.")
    parser.add_argument("--limit", type=int, default=None, help="Maximum unanswered rows to attempt per model/file/round.")
    parser.add_argument(
        "--parallel-models",
        type=int,
        default=len(answer_runner.DEFAULT_MODEL_NAMES),
        help="How many models to run concurrently.",
    )
    parser.add_argument("--parallel-files", type=int, default=1, help="How many files to run concurrently.")
    parser.add_argument(
        "--stop-after-consecutive-failures",
        type=int,
        default=3,
        help="Stop one model/file/round after this many consecutive failed calls. Use 0 to disable.",
    )
    parser.add_argument(
        "--similarity-threshold",
        type=float,
        default=SIMILARITY_THRESHOLD,
        help="Minimum pairwise text similarity for the text_similar status.",
    )
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="Do not call models; only rebuild the report from existing raw round files.",
    )
    args = parser.parse_args()
    if not 1 <= args.round <= DEFAULT_ROUNDS:
        raise SystemExit(f"--round must be between 1 and {DEFAULT_ROUNDS}.")
    args.output_root = args.output_root.resolve()
    args.raw_root = (args.raw_root or args.output_root / "raw_runs").resolve()
    args.report = (args.report or args.output_root / "consistency_report.xlsx").resolve()
    args.issues = (args.issues or args.output_root / "consistency_issues.jsonl").resolve()
    args.run_log = (args.run_log or args.output_root / "run.log").resolve()
    args.call_log = (args.call_log or args.output_root / "calls.jsonl").resolve()
    return args


def selected_models_from_targets(
    targets: tuple[answer_runner.ModelTarget, ...],
) -> list[answer_runner.SelectedModel]:
    return [
        answer_runner.SelectedModel(target=target, config=None)  # type: ignore[arg-type]
        for target in targets
    ]


def configure_paths(args: argparse.Namespace) -> None:
    global RUN_LOG_PATH, CALL_LOG_PATH
    args.output_root.mkdir(parents=True, exist_ok=True)
    args.raw_root.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.issues.parent.mkdir(parents=True, exist_ok=True)
    args.run_log.parent.mkdir(parents=True, exist_ok=True)
    args.call_log.parent.mkdir(parents=True, exist_ok=True)
    RUN_LOG_PATH = args.run_log
    CALL_LOG_PATH = args.call_log


def configure_provider_timeout(timeout_seconds: float) -> None:
    llm_providers.REQUEST_TIMEOUT_SECONDS = timeout_seconds


def run_one_round(
    args: argparse.Namespace,
    selected_models: list[answer_runner.SelectedModel],
    source_paths: tuple[Path, ...],
) -> list[RoundRunSummary]:
    parallel_models = min(max(1, args.parallel_models), len(selected_models))
    parallel_files = min(max(1, args.parallel_files), len(source_paths))
    total_workers = min(
        parallel_models * parallel_files,
        len(selected_models) * len(source_paths),
    )
    log("sources:")
    for source_path in source_paths:
        log(f"- {source_path}")
    log(f"raw root: {args.raw_root}")
    log(f"round: {args.round}")
    log(
        f"models: {len(selected_models)}, parallel_models: {parallel_models}; "
        f"files: {len(source_paths)}, parallel_files: {parallel_files}; "
        f"total_workers: {total_workers}"
    )
    for selected_model in selected_models:
        log(
            "model: "
            f"{selected_model.target.display_name} -> config #{selected_model.config.id} "
            f"{selected_model.config.provider}/{selected_model.config.model}"
        )

    summaries: list[RoundRunSummary] = []
    round_number = args.round
    log(f"round_{round_number} start")
    with ThreadPoolExecutor(max_workers=total_workers) as executor:
        futures = {
            executor.submit(run_round_file, selected_model, source_path, round_number, args): (
                selected_model,
                source_path,
                round_number,
            )
            for source_path in source_paths
            for selected_model in selected_models
        }
        for future in as_completed(futures):
            selected_model, source_path, future_round_number = futures[future]
            try:
                summaries.append(future.result())
            except Exception as exc:
                log(
                    f"[{selected_model.target.display_name}] [{source_path.name}] "
                    f"[round_{future_round_number}] failed: {exc}"
                )
                summaries.append(
                    RoundRunSummary(
                        model_name=selected_model.target.display_name,
                        round_number=future_round_number,
                        answer_path=round_answer_path(
                            args.raw_root,
                            selected_model.target.display_name,
                            future_round_number,
                            source_path.name,
                        ),
                        total=0,
                        attempted_this_run=0,
                        answered_this_run=0,
                        failures=1,
                        remaining=0,
                    )
                )
    round_remaining = sum(summary.remaining for summary in summaries)
    log(f"round_{round_number} end: remaining_answers={round_remaining}")

    log("round run summary:")
    for summary in sorted(summaries, key=lambda item: (item.model_name, str(item.answer_path), item.round_number)):
        log(
            f"- {summary.model_name} round_{summary.round_number}: "
            f"attempted_this_run={summary.attempted_this_run}, "
            f"answered_this_run={summary.answered_this_run}, "
            f"failures={summary.failures}, remaining={summary.remaining}, file={summary.answer_path}"
        )
    return summaries


def run_round_file(
    selected_model: answer_runner.SelectedModel,
    source_path: Path,
    round_number: int,
    args: argparse.Namespace,
) -> RoundRunSummary:
    model_name = selected_model.target.display_name
    log_prefix = f"[{model_name}] [{source_path.name}] [round_{round_number}]"
    answer_path = ensure_round_answer_file(source_path, args.raw_root, model_name, round_number)
    rows = answer_runner.read_jsonl(answer_path)
    total = len(rows)
    unanswered = sum(1 for row in rows if not answer_runner.has_answer(row))
    log(f"{log_prefix} answers: {answer_path}")
    log(f"{log_prefix} rows: {total}, unanswered: {unanswered}")

    attempted_this_run = 0
    answered_this_run = 0
    failures = 0
    consecutive_failures = 0
    for index, row in enumerate(rows, start=1):
        if answer_runner.has_answer(row):
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

        question = answer_runner.normalize_text(row.get("question"))
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
            round_number=round_number,
            row_index=index,
            total=total,
            question=question,
            result=result,
        )
        if not result.ok:
            failures += 1
            consecutive_failures += 1
            log(f"{log_prefix} [{index}/{total}] call failed latency={result.latency_ms}ms error={result.error}")
            continue

        answer = answer_runner.normalize_text(result.text)
        if not answer:
            failures += 1
            consecutive_failures += 1
            log(f"{log_prefix} [{index}/{total}] empty response latency={result.latency_ms}ms")
            continue

        row["answer"] = answer
        answer_runner.atomic_write_jsonl(answer_path, rows)
        answered_this_run += 1
        consecutive_failures = 0
        log(f"{log_prefix} [{index}/{total}] answer saved latency={result.latency_ms}ms chars={len(answer)}")

    remaining = sum(1 for row in rows if not answer_runner.has_answer(row))
    log(
        f"{log_prefix} done: attempted_this_run={attempted_this_run}, "
        f"answered_this_run={answered_this_run}, failures={failures}, remaining={remaining}"
    )
    return RoundRunSummary(
        model_name=model_name,
        round_number=round_number,
        answer_path=answer_path,
        total=total,
        attempted_this_run=attempted_this_run,
        answered_this_run=answered_this_run,
        failures=failures,
        remaining=remaining,
    )


def ensure_round_answer_file(source_path: Path, raw_root: Path, model_name: str, round_number: int) -> Path:
    answer_path = round_answer_path(raw_root, model_name, round_number, source_path.name)
    answer_path.parent.mkdir(parents=True, exist_ok=True)
    if not answer_path.exists():
        rows = answer_runner.read_jsonl(source_path)
        for row in rows:
            row["answer"] = None
        answer_runner.atomic_write_jsonl(answer_path, rows)
        log(f"created round answer file: {answer_path}")
    return answer_path


def round_answer_path(raw_root: Path, model_name: str, round_number: int, file_name: str) -> Path:
    return raw_root / answer_runner.safe_dir_name(model_name) / f"round_{round_number}" / file_name


def build_report_rows(
    *,
    raw_root: Path,
    selected_models: list[answer_runner.SelectedModel],
    source_paths: tuple[Path, ...],
    rounds: int,
    similarity_threshold: float,
) -> tuple[list[dict[str, str]], list[dict[str, Any]], list[dict[str, str]]]:
    detail_rows: list[dict[str, str]] = []
    issue_rows: list[dict[str, Any]] = []
    summary_index: dict[tuple[str, str], dict[str, int]] = {}

    for selected_model in selected_models:
        model_name = selected_model.target.display_name
        for source_path in source_paths:
            source_rows = read_rows_by_line(source_path)
            round_rows = [
                read_rows_by_line(round_answer_path(raw_root, model_name, round_number, source_path.name))
                for round_number in range(1, rounds + 1)
            ]
            line_numbers = sorted(
                set(source_rows)
                | {line_number for rows in round_rows for line_number in rows}
            )
            for line_number in line_numbers:
                rows_for_line = [rows.get(line_number, {}) for rows in round_rows]
                source_row = source_rows.get(line_number, {})
                question = first_text([source_row, *rows_for_line], "question")
                other = first_text([source_row, *rows_for_line], "other")
                answers = tuple(answer_runner.normalize_text(row.get("answer")) for row in rows_for_line)
                result = classify_answers(answers, similarity_threshold=similarity_threshold)
                detail_row = build_detail_row(
                    model_name=model_name,
                    source_path=source_path,
                    line_number=line_number,
                    question=question,
                    other=other,
                    answers=answers,
                    result=result,
                )
                detail_rows.append(detail_row)
                update_summary(summary_index, model_name, source_path.name, result.status)
                if result.status not in {"exact_match", "text_similar"}:
                    issue_rows.append(issue_record(detail_row))

    summary_rows = build_summary_rows(summary_index)
    detail_rows.sort(key=lambda row: (row["model"], row["file"], int(row["line"])))
    return detail_rows, issue_rows, summary_rows


def read_rows_by_line(path: Path) -> dict[int, dict[str, Any]]:
    if not path.exists():
        return {}
    rows = answer_runner.read_jsonl(path)
    return {index: row for index, row in enumerate(rows, start=1)}


def first_text(rows: list[dict[str, Any]], key: str) -> str:
    for row in rows:
        value = row.get(key)
        if isinstance(value, str):
            return value
        if value is not None and key == "other":
            return json.dumps(value, ensure_ascii=False)
    return ""


def classify_answers(answers: tuple[str, ...], *, similarity_threshold: float = SIMILARITY_THRESHOLD) -> ConsistencyResult:
    lengths = tuple(len(answer) for answer in answers)
    invalid_reasons = [invalid_answer_reason(index, answer) for index, answer in enumerate(answers, start=1)]
    invalid_reasons = [reason for reason in invalid_reasons if reason]
    similarities = pairwise_similarities(answers)
    min_similarity = min((value for value in similarities if value is not None), default=None)

    if invalid_reasons:
        return ConsistencyResult(
            status="invalid",
            reason="; ".join(invalid_reasons),
            similarities=similarities,
            min_similarity=min_similarity,
            lengths=lengths,
        )

    normalized = [normalize_for_compare(answer) for answer in answers]
    if len(set(normalized)) == 1:
        return ConsistencyResult(
            status="exact_match",
            reason="normalized answers are identical",
            similarities=similarities,
            min_similarity=min_similarity,
            lengths=lengths,
        )

    if is_length_outlier(lengths):
        return ConsistencyResult(
            status="length_outlier",
            reason=f"answer length outlier: lengths={','.join(str(length) for length in lengths)}",
            similarities=similarities,
            min_similarity=min_similarity,
            lengths=lengths,
        )

    if min_similarity is not None and min_similarity >= similarity_threshold:
        return ConsistencyResult(
            status="text_similar",
            reason=f"minimum pairwise similarity {min_similarity:.3f} >= {similarity_threshold:.3f}",
            similarities=similarities,
            min_similarity=min_similarity,
            lengths=lengths,
        )

    similarity_text = "n/a" if min_similarity is None else f"{min_similarity:.3f}"
    return ConsistencyResult(
        status="needs_review",
        reason=f"minimum pairwise similarity {similarity_text} < {similarity_threshold:.3f}",
        similarities=similarities,
        min_similarity=min_similarity,
        lengths=lengths,
    )


def invalid_answer_reason(index: int, answer: str) -> str:
    if not answer.strip():
        return f"round_{index} empty answer"
    lowered = answer.lower()
    markers = (
        "429",
        "rate limit",
        "timed out",
        "timeout",
        "api error",
        "http error",
        "traceback",
        "请求失败",
        "调用失败",
        "接口调用",
        "抱歉，我无法",
        "抱歉，无法",
        "我不能提供",
        "无法提供医疗建议",
    )
    if any(marker in lowered for marker in markers):
        return f"round_{index} contains failure/refusal marker"
    return ""


def normalize_for_compare(value: str) -> str:
    value = unicode_normalize("NFKC", value)
    return re.sub(r"\s+", "", value).strip()


def pairwise_similarities(answers: tuple[str, ...]) -> tuple[float | None, float | None, float | None]:
    normalized = [normalize_for_compare(answer) for answer in answers]
    pairs = ((0, 1), (0, 2), (1, 2))
    values: list[float | None] = []
    for left, right in pairs:
        if left >= len(normalized) or right >= len(normalized):
            values.append(None)
            continue
        if not normalized[left] or not normalized[right]:
            values.append(None)
            continue
        values.append(SequenceMatcher(None, normalized[left], normalized[right], autojunk=False).ratio())
    return tuple(values)  # type: ignore[return-value]


def is_length_outlier(lengths: tuple[int, ...]) -> bool:
    non_zero = [length for length in lengths if length > 0]
    if len(non_zero) < len(lengths):
        return True
    shortest = min(non_zero)
    longest = max(non_zero)
    if longest == 0:
        return True
    return shortest / longest < LENGTH_OUTLIER_RATIO and longest - shortest >= LENGTH_OUTLIER_MIN_DELTA


def build_detail_row(
    *,
    model_name: str,
    source_path: Path,
    line_number: int,
    question: str,
    other: str,
    answers: tuple[str, ...],
    result: ConsistencyResult,
) -> dict[str, str]:
    row = {
        "model": model_name,
        "file": source_path.name,
        "line": str(line_number),
        "question": question,
        "other": other,
        "status": result.status,
        "reason": result.reason,
        "min_similarity": format_score(result.min_similarity),
        "similarity_12": format_score(result.similarities[0]),
        "similarity_13": format_score(result.similarities[1]),
        "similarity_23": format_score(result.similarities[2]),
    }
    for index, answer in enumerate(answers, start=1):
        row[f"answer_round_{index}"] = answer
        row[f"chars_round_{index}"] = str(len(answer))
    return row


def format_score(value: float | None) -> str:
    return "" if value is None else f"{value:.3f}"


def update_summary(summary_index: dict[tuple[str, str], dict[str, int]], model_name: str, file_name: str, status: str) -> None:
    key = (model_name, file_name)
    counters = summary_index.setdefault(
        key,
        {
            "total": 0,
            "exact_match": 0,
            "text_similar": 0,
            "length_outlier": 0,
            "invalid": 0,
            "needs_review": 0,
        },
    )
    counters["total"] += 1
    counters[status] = counters.get(status, 0) + 1


def build_summary_rows(summary_index: dict[tuple[str, str], dict[str, int]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for (model_name, file_name), counters in sorted(summary_index.items()):
        total = counters["total"]
        stable = counters.get("exact_match", 0) + counters.get("text_similar", 0)
        issue_count = total - stable
        rows.append(
            {
                "model": model_name,
                "file": file_name,
                "total": str(total),
                "stable": str(stable),
                "stable_rate": format_score(stable / total if total else None),
                "exact_match": str(counters.get("exact_match", 0)),
                "text_similar": str(counters.get("text_similar", 0)),
                "length_outlier": str(counters.get("length_outlier", 0)),
                "invalid": str(counters.get("invalid", 0)),
                "needs_review": str(counters.get("needs_review", 0)),
                "issue_count": str(issue_count),
            }
        )
    return rows


def issue_record(detail_row: dict[str, str]) -> dict[str, Any]:
    return {
        "model": detail_row["model"],
        "file": detail_row["file"],
        "line": int(detail_row["line"]),
        "question": detail_row["question"],
        "status": detail_row["status"],
        "reason": detail_row["reason"],
        "min_similarity": detail_row["min_similarity"],
        "similarity_12": detail_row["similarity_12"],
        "similarity_13": detail_row["similarity_13"],
        "similarity_23": detail_row["similarity_23"],
    }


def write_issues_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False))
            handle.write("\n")


SUMMARY_COLUMNS = [
    ("model", "模型"),
    ("file", "文件"),
    ("total", "总题数"),
    ("stable", "稳定题数"),
    ("stable_rate", "稳定率"),
    ("exact_match", "完全一致"),
    ("text_similar", "文本相似"),
    ("length_outlier", "长度异常"),
    ("invalid", "无效回答"),
    ("needs_review", "待复核"),
    ("issue_count", "问题数"),
]

DETAIL_COLUMNS = [
    ("model", "模型"),
    ("file", "文件"),
    ("line", "行号"),
    ("question", "问题"),
    ("status", "规则标签"),
    ("reason", "规则原因"),
    ("min_similarity", "最低相似度"),
    ("similarity_12", "相似度1-2"),
    ("similarity_13", "相似度1-3"),
    ("similarity_23", "相似度2-3"),
    ("chars_round_1", "第1轮字数"),
    ("chars_round_2", "第2轮字数"),
    ("chars_round_3", "第3轮字数"),
    ("answer_round_1", "第1轮答案"),
    ("answer_round_2", "第2轮答案"),
    ("answer_round_3", "第3轮答案"),
    ("other", "other"),
]


def write_xlsx(path: Path, summary_rows: list[dict[str, str]], detail_rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sheets = [
        ("Summary", SUMMARY_COLUMNS, summary_rows, [22, 18, 10, 12, 10, 10, 10, 10, 10, 10, 10]),
        ("Details", DETAIL_COLUMNS, detail_rows, [22, 18, 8, 54, 16, 46, 12, 12, 12, 12, 12, 12, 12, 72, 72, 72, 30]),
    ]
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types_xml(len(sheets)))
        archive.writestr("_rels/.rels", ROOT_RELS_XML)
        archive.writestr("xl/workbook.xml", workbook_xml([sheet[0] for sheet in sheets]))
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels_xml(len(sheets)))
        archive.writestr("xl/styles.xml", STYLES_XML)
        for index, (_name, columns, rows, widths) in enumerate(sheets, start=1):
            archive.writestr(f"xl/worksheets/sheet{index}.xml", build_sheet_xml(columns, rows, widths))


def build_sheet_xml(columns: list[tuple[str, str]], rows: list[dict[str, str]], widths: list[int]) -> str:
    xml_rows = [build_row_xml(1, [label for _key, label in columns], style="1")]
    for index, row in enumerate(rows, start=2):
        xml_rows.append(build_row_xml(index, [row.get(key, "") for key, _label in columns], style="2"))
    column_xml = "".join(
        f'<col min="{idx}" max="{idx}" width="{width}" customWidth="1"/>'
        for idx, width in enumerate(widths, start=1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<cols>{column_xml}</cols>"
        "<sheetViews><sheetView workbookViewId=\"0\"><pane ySplit=\"1\" topLeftCell=\"A2\" "
        "activePane=\"bottomLeft\" state=\"frozen\"/></sheetView></sheetViews>"
        f"<sheetData>{''.join(xml_rows)}</sheetData>"
        f"<autoFilter ref=\"A1:{column_name(len(columns))}1\"/>"
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


def excel_cell_text(value: str) -> str:
    value = "".join(ch for ch in value if ch == "\n" or ch == "\t" or ord(ch) >= 32)
    return escape(value[:32767], {'"': "&quot;"})


def content_types_xml(sheet_count: int) -> str:
    worksheet_overrides = "".join(
        f'<Override PartName="/xl/worksheets/sheet{index}.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for index in range(1, sheet_count + 1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/styles.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        f"{worksheet_overrides}"
        "</Types>"
    )


def workbook_xml(sheet_names: list[str]) -> str:
    sheets = "".join(
        f'<sheet name="{excel_cell_text(name)}" sheetId="{index}" r:id="rId{index}"/>'
        for index, name in enumerate(sheet_names, start=1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<sheets>{sheets}</sheets>"
        "</workbook>"
    )


def workbook_rels_xml(sheet_count: int) -> str:
    relationships = "".join(
        f'<Relationship Id="rId{index}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        f'Target="worksheets/sheet{index}.xml"/>'
        for index in range(1, sheet_count + 1)
    )
    relationships += (
        f'<Relationship Id="rId{sheet_count + 1}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
        'Target="styles.xml"/>'
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f"{relationships}"
        "</Relationships>"
    )


ROOT_RELS_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
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


def append_call_log(
    *,
    selected_model: answer_runner.SelectedModel,
    source_path: Path,
    answer_path: Path,
    round_number: int,
    row_index: int,
    total: int,
    question: str,
    result: Any,
) -> None:
    record = {
        "timestamp": utc_timestamp(),
        "round": round_number,
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


def log(message: str) -> None:
    with LOG_LOCK:
        print(message, flush=True)
        if RUN_LOG_PATH is not None:
            with RUN_LOG_PATH.open("a", encoding="utf-8") as handle:
                handle.write(f"{utc_timestamp()} {message}\n")


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
