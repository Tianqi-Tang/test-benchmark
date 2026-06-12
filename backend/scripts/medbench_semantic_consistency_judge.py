from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import sys
import zipfile
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, Lock
from typing import Any
from xml.sax.saxutils import escape


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.llm import providers as llm_providers  # noqa: E402
from app.llm.client import call_model  # noqa: E402
from scripts import medbench_answer_runner as answer_runner  # noqa: E402
from scripts import medbench_consistency_runner as consistency_runner  # noqa: E402


DEFAULT_OUTPUT_ROOT = answer_runner.REPO_ROOT / "reports/MedBench_LLM_semantic_consistency"
DEFAULT_RESULTS_PATH = DEFAULT_OUTPUT_ROOT / "semantic_judgments.jsonl"
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_ROOT / "semantic_consistency_report.xlsx"
DEFAULT_RUN_LOG_PATH = DEFAULT_OUTPUT_ROOT / "run.log"
DEFAULT_CALL_LOG_PATH = DEFAULT_OUTPUT_ROOT / "calls.jsonl"
DEFAULT_RAW_ROOT = consistency_runner.DEFAULT_RAW_ROOT
DEFAULT_FORMAL_ANSWERS_ROOT = answer_runner.DEFAULT_OUTPUT_ROOT
DEFAULT_JUDGE_MODEL = "gpt-5.5"
ROUNDS = 4
LOG_LOCK = Lock()
RESULT_LOCK = Lock()
RUN_LOG_PATH: Path | None = None
CALL_LOG_PATH: Path | None = None
RESULTS_PATH: Path | None = None


PAYMENT_ERROR_PATTERNS = (
    "402",
    "payment required",
    "insufficient credit",
    "insufficient credits",
    "insufficient balance",
    "insufficient funds",
)
TRANSPORT_ERROR_PATTERNS = (
    "eof occurred in violation of protocol",
    "_ssl.c",
    "connection reset",
    "connection aborted",
    "remote end closed connection",
    "tls",
    "ssl",
)
MAX_CONSECUTIVE_TRANSPORT_ERRORS = 5


class StopJudgeRunError(RuntimeError):
    pass


def is_payment_error(error: str | None) -> bool:
    text = (error or "").lower()
    return any(pattern in text for pattern in PAYMENT_ERROR_PATTERNS)


def is_transport_error(error: str | None) -> bool:
    text = (error or "").lower()
    return any(pattern in text for pattern in TRANSPORT_ERROR_PATTERNS)


@dataclass(frozen=True)
class JudgeInput:
    key: str
    target_model: str
    file_name: str
    line: int
    question: str
    other: str
    answers: tuple[str, str, str, str]
    rule_label: str
    rule_reason: str
    min_similarity: float | None
    similarities: tuple[float | None, ...]


def main() -> int:
    args = parse_args()
    configure_paths(args)
    os.environ["DATABASE_URL"] = args.database_url or os.getenv("DATABASE_URL") or answer_runner.DEFAULT_DATABASE_URL
    answer_runner.prefer_http_proxy_over_socks_fallback()
    llm_providers.REQUEST_TIMEOUT_SECONDS = args.request_timeout

    judge_model = answer_runner.load_model_configs(answer_runner.parse_model_targets([args.judge_model]))[0]
    target_models = [target.display_name for target in answer_runner.parse_model_targets(args.model)]
    source_paths = answer_runner.resolve_source_paths(args.file, args.dataset_dir, args.all_medbench_files)
    inputs = build_judge_inputs(
        target_models=target_models,
        source_paths=source_paths,
        raw_root=args.raw_root,
        formal_answers_root=args.formal_answers_root,
        similarity_threshold=args.similarity_threshold,
    )
    existing = load_existing_results(args.results)
    pending = [item for item in inputs if item.key not in existing]

    log(f"judge model: {judge_model.target.display_name} -> config #{judge_model.config.id} {judge_model.config.provider}/{judge_model.config.model}")
    log(f"target models: {', '.join(target_models)}")
    log(f"files: {', '.join(path.name for path in source_paths)}")
    log(f"total combinations: {len(inputs)}, existing judgments: {len(existing)}, pending: {len(pending)}")
    log(f"results: {args.results}")
    log(f"report: {args.report}")

    if pending and not args.report_only:
        run_judgments(
            pending=pending,
            existing=existing,
            judge_model=judge_model,
            parallel=args.parallel,
            max_output_tokens=args.max_output_tokens,
            max_attempts=args.max_attempts,
        )
    elif args.report_only:
        log("report-only mode: no judge calls")

    rows = [existing[item.key] for item in inputs if item.key in existing]
    missing = [item for item in inputs if item.key not in existing]
    write_xlsx(args.report, rows, missing)
    log(f"report written: {args.report}")
    log(f"judged: {len(rows)}, missing: {len(missing)}")
    return 0 if not missing else 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Judge semantic consistency across four MedBench_LLM answers for each model/question."
    )
    parser.add_argument("--judge-model", default=DEFAULT_JUDGE_MODEL)
    parser.add_argument("--model", action="append", default=None)
    parser.add_argument("--file", action="append", default=None)
    parser.add_argument("--all-medbench-files", action="store_true")
    parser.add_argument("--dataset-dir", type=Path, default=answer_runner.DEFAULT_DATASET_DIR)
    parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_ROOT)
    parser.add_argument("--formal-answers-root", type=Path, default=DEFAULT_FORMAL_ANSWERS_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--results", type=Path, default=None)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--run-log", type=Path, default=None)
    parser.add_argument("--call-log", type=Path, default=None)
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--parallel", type=int, default=3)
    parser.add_argument("--max-output-tokens", type=int, default=2048)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--request-timeout", type=float, default=180.0)
    parser.add_argument("--similarity-threshold", type=float, default=consistency_runner.SIMILARITY_THRESHOLD)
    parser.add_argument("--report-only", action="store_true")
    args = parser.parse_args()
    args.output_root = args.output_root.resolve()
    args.raw_root = args.raw_root.resolve()
    args.formal_answers_root = args.formal_answers_root.resolve()
    args.results = (args.results or args.output_root / DEFAULT_RESULTS_PATH.name).resolve()
    args.report = (args.report or args.output_root / DEFAULT_REPORT_PATH.name).resolve()
    args.run_log = (args.run_log or args.output_root / DEFAULT_RUN_LOG_PATH.name).resolve()
    args.call_log = (args.call_log or args.output_root / DEFAULT_CALL_LOG_PATH.name).resolve()
    return args


def configure_paths(args: argparse.Namespace) -> None:
    global RUN_LOG_PATH, CALL_LOG_PATH, RESULTS_PATH
    args.output_root.mkdir(parents=True, exist_ok=True)
    args.results.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.run_log.parent.mkdir(parents=True, exist_ok=True)
    args.call_log.parent.mkdir(parents=True, exist_ok=True)
    RUN_LOG_PATH = args.run_log
    CALL_LOG_PATH = args.call_log
    RESULTS_PATH = args.results


def build_judge_inputs(
    *,
    target_models: list[str],
    source_paths: tuple[Path, ...],
    raw_root: Path,
    formal_answers_root: Path,
    similarity_threshold: float,
) -> list[JudgeInput]:
    items: list[JudgeInput] = []
    for model_name in target_models:
        safe_model = answer_runner.safe_dir_name(model_name)
        for source_path in source_paths:
            source_rows = consistency_runner.read_rows_by_line(source_path)
            round_rows = [
                consistency_runner.read_rows_by_line(
                    raw_root / safe_model / f"round_{round_number}" / source_path.name
                )
                for round_number in range(1, 4)
            ]
            formal_rows = consistency_runner.read_rows_by_line(
                formal_answers_root / safe_model / source_path.name
            )
            all_rows = [*round_rows, formal_rows]
            for line in sorted(source_rows):
                source_row = source_rows[line]
                rows_for_line = [rows.get(line, {}) for rows in all_rows]
                answers = tuple(answer_runner.normalize_text(row.get("answer")) for row in rows_for_line)
                if len(answers) != ROUNDS:
                    raise RuntimeError("internal error: expected four answers")
                result = consistency_runner.classify_answers(
                    answers,
                    similarity_threshold=similarity_threshold,
                )
                items.append(
                    JudgeInput(
                        key=record_key(model_name, source_path.name, line),
                        target_model=model_name,
                        file_name=source_path.name,
                        line=line,
                        question=answer_runner.normalize_text(source_row.get("question")),
                        other=consistency_runner.first_text([source_row], "other"),
                        answers=answers,  # type: ignore[arg-type]
                        rule_label=result.status,
                        rule_reason=result.reason,
                        min_similarity=result.min_similarity,
                        similarities=result.similarities,
                    )
                )
    return items


def record_key(model_name: str, file_name: str, line: int) -> str:
    return f"{model_name}\t{file_name}\t{line}"


def load_existing_results(path: Path) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            if not raw_line.strip():
                continue
            row = json.loads(raw_line)
            if row.get("judge_error"):
                continue
            key = record_key(row["model"], row["file"], int(row["line"]))
            rows[key] = row
    return rows


def run_judgments(
    *,
    pending: list[JudgeInput],
    existing: dict[str, dict[str, Any]],
    judge_model: answer_runner.SelectedModel,
    parallel: int,
    max_output_tokens: int,
    max_attempts: int,
) -> None:
    total = len(pending)
    parallel = min(max(1, parallel), total)
    stop_event = Event()
    consecutive_transport_errors = 0
    log(f"judge calls start: pending={total}, parallel={parallel}")
    with ThreadPoolExecutor(max_workers=parallel) as executor:
        next_index = 0
        futures = {}

        def submit_next() -> None:
            nonlocal next_index
            if stop_event.is_set() or next_index >= total:
                return
            item = pending[next_index]
            index = next_index + 1
            next_index += 1
            futures[
                executor.submit(
                    judge_one,
                    item,
                    judge_model,
                    index,
                    total,
                    max_output_tokens,
                    max_attempts,
                    stop_event,
                )
            ] = item

        for _ in range(parallel):
            submit_next()

        while futures:
            done, _not_done = wait(futures, return_when=FIRST_COMPLETED)
            for future in done:
                item = futures.pop(future)
                try:
                    row = future.result()
                except StopJudgeRunError as exc:
                    stop_event.set()
                    log(f"fatal judge error detected; stopping remaining judge calls: {exc}")
                    row = fallback_error_row(item, str(exc))
                except Exception as exc:
                    row = fallback_error_row(item, f"worker exception: {exc}")

                error = row.get("judge_error") or ""
                if error and is_transport_error(error):
                    consecutive_transport_errors += 1
                    if consecutive_transport_errors >= MAX_CONSECUTIVE_TRANSPORT_ERRORS:
                        stop_event.set()
                        log(
                            "transport errors reached "
                            f"{consecutive_transport_errors}; stopping remaining judge calls: {error}"
                        )
                elif not error:
                    consecutive_transport_errors = 0

                with RESULT_LOCK:
                    existing[item.key] = row
                    if row.get("judge_error"):
                        log(
                            f"[{item.target_model}] [{item.file_name}:{item.line}] "
                            "not written to results because judge_error is present"
                        )
                    else:
                        append_result(row)
                submit_next()
        if stop_event.is_set():
            log("judge calls stopped early because a fatal or repeated transport error was detected")
    log("judge calls end")


def judge_one(
    item: JudgeInput,
    judge_model: answer_runner.SelectedModel,
    index: int,
    total: int,
    max_output_tokens: int,
    max_attempts: int,
    stop_event: Event,
) -> dict[str, Any]:
    log_prefix = f"[{index}/{total}] [{item.target_model}] [{item.file_name}:{item.line}]"
    if stop_event.is_set():
        log(f"{log_prefix} skip because stop was already triggered")
        return fallback_error_row(item, "skipped after judge stop was triggered")

    prompt = build_judge_prompt(item)
    log(f"{log_prefix} judge start")
    result = call_model(
        judge_model.config,
        prompt,
        max_output_tokens=max_output_tokens,
        max_attempts=max_attempts,
    )
    append_call_log(item=item, judge_model=judge_model, prompt=prompt, result=result)
    if not result.ok:
        log(f"{log_prefix} judge failed latency={result.latency_ms}ms error={result.error}")
        if is_payment_error(result.error):
            stop_event.set()
            raise StopJudgeRunError(result.error or "payment-related judge call failure")
        return fallback_error_row(item, result.error or "judge call failed", latency_ms=result.latency_ms)

    parsed, parse_error = parse_judge_json(result.text or "")
    if parse_error:
        log(f"{log_prefix} parse failed latency={result.latency_ms}ms error={parse_error}")
        return fallback_error_row(
            item,
            parse_error,
            latency_ms=result.latency_ms,
            raw_text=result.text or "",
        )

    row = base_result_row(item)
    row.update(
        {
            "semantic_label": normalize_label(parsed.get("semantic_label")),
            "semantic_score": normalize_score(parsed.get("semantic_score")),
            "key_findings_consistent": normalize_bool_text(parsed.get("key_findings_consistent")),
            "diagnosis_consistent": normalize_bool_text(parsed.get("diagnosis_consistent")),
            "treatment_consistent": normalize_bool_text(parsed.get("treatment_consistent")),
            "has_contradiction": normalize_bool_text(parsed.get("has_contradiction")),
            "critical_difference": normalize_text_value(parsed.get("critical_difference")),
            "reason": normalize_text_value(parsed.get("reason")),
            "judge_error": "",
            "judge_latency_ms": result.latency_ms,
        }
    )
    log(
        f"{log_prefix} judge saved latency={result.latency_ms}ms "
        f"label={row['semantic_label']} score={row['semantic_score']}"
    )
    return row


def build_judge_prompt(item: JudgeInput) -> str:
    answers = "\n\n".join(
        f"【回答{label}】\n{answer}"
        for label, _round_number, answer in blind_answers(item)
    )
    return f"""你是医学问答一致性评审员。请比较同一个匿名系统给出的 4 份回答，判断它们在医学语义上是否一致。

评审重点：
1. 医学结论、诊断方向、处理建议、关键事实是否一致。
2. 不因为措辞、段落顺序、详略程度不同而判为不一致。
3. 如果某份回答遗漏关键结论、给出相反结论、处理建议冲突、诊断方向改变，应标记为不一致。
4. 只判断 4 份回答彼此是否一致，不评价哪一份医学上更正确。
5. 你不会看到原始问题、系统名称、模型名称、文件名或题目编号，请只根据 4 份回答内容判断。

请只输出 JSON，不要输出 Markdown，不要添加解释性前后缀。JSON 字段如下：
{{
  "semantic_label": "consistent | mostly_consistent | partially_inconsistent | contradictory | invalid",
  "semantic_score": 0.0,
  "key_findings_consistent": "yes | no | not_applicable",
  "diagnosis_consistent": "yes | no | not_applicable",
  "treatment_consistent": "yes | no | not_applicable",
  "has_contradiction": "yes | no",
  "critical_difference": "如果存在关键差异，用一句话说明；没有则写无",
  "reason": "用一到两句话说明判断依据"
}}

semantic_score 取值范围 0 到 1：
- 1.0 表示语义完全一致
- 0.8 到 0.99 表示基本一致，只有详略或措辞差异
- 0.5 到 0.79 表示部分不一致或存在关键遗漏
- 0.1 到 0.49 表示明显矛盾或核心结论冲突
- 0 表示空答、拒答、无法判断或无效回答

{answers}
"""


def blind_answers(item: JudgeInput) -> list[tuple[str, int, str]]:
    order = list(range(ROUNDS))
    seed = int.from_bytes(hashlib.sha256(item.key.encode("utf-8")).digest()[:8], "big")
    random.Random(seed).shuffle(order)
    labels = ("A", "B", "C", "D")
    return [
        (label, answer_index + 1, item.answers[answer_index])
        for label, answer_index in zip(labels, order)
    ]


def blind_order_text(item: JudgeInput) -> str:
    return "; ".join(
        f"{label}=round_{round_number}"
        for label, round_number, _answer in blind_answers(item)
    )


def parse_judge_json(text: str) -> tuple[dict[str, Any], str]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    match = re.search(r"\{.*\}", cleaned, flags=re.S)
    if match:
        cleaned = match.group(0)
    try:
        value = json.loads(cleaned)
    except Exception as exc:
        return {}, f"invalid judge JSON: {exc}"
    if not isinstance(value, dict):
        return {}, "judge JSON is not an object"
    return value, ""


def normalize_label(value: Any) -> str:
    label = str(value or "").strip().lower()
    allowed = {"consistent", "mostly_consistent", "partially_inconsistent", "contradictory", "invalid"}
    return label if label in allowed else "invalid"


def normalize_score(value: Any) -> str:
    try:
        score = float(value)
    except Exception:
        return ""
    score = max(0.0, min(1.0, score))
    return f"{score:.2f}"


def normalize_bool_text(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"yes", "no", "not_applicable"}:
        return text
    if text in {"true", "是"}:
        return "yes"
    if text in {"false", "否"}:
        return "no"
    return "not_applicable"


def normalize_text_value(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def base_result_row(item: JudgeInput) -> dict[str, Any]:
    row: dict[str, Any] = {
        "model": item.target_model,
        "file": item.file_name,
        "line": item.line,
        "question": item.question,
        "other": item.other,
        "rule_label": item.rule_label,
        "rule_reason": item.rule_reason,
        "min_similarity": consistency_runner.format_score(item.min_similarity),
        "blind_order": blind_order_text(item),
    }
    for index, similarity in enumerate(item.similarities, start=1):
        row[f"similarity_{index}"] = consistency_runner.format_score(similarity)
    for index, answer in enumerate(item.answers, start=1):
        row[f"chars_round_{index}"] = len(answer)
        row[f"answer_round_{index}"] = answer
    return row


def fallback_error_row(
    item: JudgeInput,
    error: str,
    *,
    latency_ms: int | None = None,
    raw_text: str = "",
) -> dict[str, Any]:
    row = base_result_row(item)
    row.update(
        {
            "semantic_label": "invalid",
            "semantic_score": "0.00",
            "key_findings_consistent": "not_applicable",
            "diagnosis_consistent": "not_applicable",
            "treatment_consistent": "not_applicable",
            "has_contradiction": "no",
            "critical_difference": "",
            "reason": "",
            "judge_error": error,
            "judge_raw_text": raw_text,
            "judge_latency_ms": latency_ms if latency_ms is not None else "",
        }
    )
    return row


def append_result(row: dict[str, Any]) -> None:
    if RESULTS_PATH is None:
        return
    with RESULTS_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, default=str))
        handle.write("\n")


def append_call_log(
    *,
    item: JudgeInput,
    judge_model: answer_runner.SelectedModel,
    prompt: str,
    result: Any,
) -> None:
    if CALL_LOG_PATH is None:
        return
    record = {
        "timestamp": utc_timestamp(),
        "target_model": item.target_model,
        "file": item.file_name,
        "line": item.line,
        "judge_model_name": judge_model.target.display_name,
        "judge_model_config_id": judge_model.config.id,
        "judge_provider": judge_model.config.provider,
        "judge_model": judge_model.config.model,
        "prompt": prompt,
        "ok": result.ok,
        "latency_ms": result.latency_ms,
        "text": result.text,
        "error": result.error,
        "request": result.request,
        "raw_response": result.raw_response,
    }
    with LOG_LOCK:
        with CALL_LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, default=str))
            handle.write("\n")


MODEL_COLUMNS = [
    ("model", "模型"),
    ("total", "总题数"),
    ("consistent_count", "语义一致/基本一致"),
    ("consistent_rate", "语义一致率"),
    ("consistent", "完全一致"),
    ("mostly_consistent", "基本一致"),
    ("partially_inconsistent", "部分不一致"),
    ("contradictory", "存在矛盾"),
    ("invalid", "无效答案"),
]

MODEL_SUMMARY_README_ROWS = [
    "评测说明",
    "1. 本报告评测内容：评测同一个医学大模型在同一批医学问题上多次回答是否保持语义一致。每个模型、每道题包含4轮答案，评审模型只比较这4轮答案之间的语义一致性。",
    "2. 数据来源：问题来自MedBench_LLM中的6个医学问答文件，包括MedMC、MedHC、MedSpeQA、MedHG、MedPrimary、MedDiag。前3轮答案来自一致性验证重复运行结果，第4轮答案来自此前用于提交评测的正式答案文件。",
    "3. 为什么可以评测一致性：一致性关注的是同一输入下多次输出是否稳定，因此核心是比较同一模型对同一问题的多轮回答。如果核心医学结论、诊断方向、处理建议基本一致，则说明该模型在该问题上的回答较稳定；如果出现结论差异、建议冲突或无效回答，则说明存在一致性风险。",
    "4. 评测边界：本报告评测的是回答稳定性/一致性，不等同于医学正确性评测。答案是否医学正确，需要结合标准答案、专家审核或正式评测成绩另行判断。",
    "",
    "阅读说明",
    "1. 模型汇总：每行代表一个被评模型，用于横向比较各模型四轮回答的一致性。总题数为该模型参与评审的题目数；语义一致/基本一致 = 完全一致 + 基本一致；语义一致率 = 语义一致/基本一致 / 总题数。",
    "2. 分类含义：完全一致表示四轮答案核心语义一致；基本一致表示核心结论一致但表达或细节有差异；部分不一致、存在矛盾、无效答案建议进入人工复核。",
    "3. 明细：保留每个模型、每道题、四轮答案和语义评审结果，适合追溯单题判断依据。语义分和最低字符相似度均按百分比展示。",
    "4. 需复核项：从明细中筛选出部分不一致、存在矛盾、无效答案或评审错误的记录，方便优先查看可能存在一致性风险的问题。",
    "",
]

DETAIL_COLUMNS = [
    ("model", "模型"),
    ("file", "文件"),
    ("line", "行号"),
    ("question", "问题"),
    ("blind_order", "盲评映射"),
    ("semantic_label", "语义标签"),
    ("semantic_score", "语义分"),
    ("has_contradiction", "是否矛盾"),
    ("critical_difference", "关键差异"),
    ("reason", "语义判断理由"),
    ("rule_label", "规则标签"),
    ("rule_reason", "规则原因"),
    ("min_similarity", "最低字符相似度"),
    ("chars_round_1", "第1轮字数"),
    ("chars_round_2", "第2轮字数"),
    ("chars_round_3", "第3轮字数"),
    ("chars_round_4", "第4轮字数"),
    ("answer_round_1", "第1轮答案"),
    ("answer_round_2", "第2轮答案"),
    ("answer_round_3", "第3轮答案"),
    ("answer_round_4", "第4轮答案"),
    ("judge_error", "评审错误"),
    ("other", "来源信息"),
]

ISSUE_COLUMNS = [
    ("model", "模型"),
    ("file", "文件"),
    ("line", "行号"),
    ("question", "问题"),
    ("blind_order", "盲评映射"),
    ("semantic_label", "语义标签"),
    ("semantic_score", "语义分"),
    ("has_contradiction", "是否矛盾"),
    ("critical_difference", "关键差异"),
    ("reason", "语义判断理由"),
    ("rule_label", "规则标签"),
    ("min_similarity", "最低字符相似度"),
    ("judge_error", "评审错误"),
]


def write_xlsx(path: Path, rows: list[dict[str, Any]], missing: list[JudgeInput]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(rows, key=lambda row: (row["model"], row["file"], int(row["line"])))
    issue_rows = [
        row
        for row in rows
        if row.get("semantic_label") not in {"consistent", "mostly_consistent"}
        or row.get("judge_error")
    ]
    model_rows = build_model_rows(rows)
    detail_rows = [format_display_row(row) for row in rows]
    issue_display_rows = [format_display_row(row) for row in issue_rows]
    sheets = [
        ("模型汇总", MODEL_COLUMNS, model_rows, [24, 10, 18, 14, 12, 18, 24, 14, 10], MODEL_SUMMARY_README_ROWS),
        ("明细", DETAIL_COLUMNS, detail_rows, [22, 18, 8, 54, 24, 20, 10, 12, 42, 54, 16, 44, 14, 12, 12, 12, 12, 72, 72, 72, 72, 32, 28], []),
        ("需复核项", ISSUE_COLUMNS, issue_display_rows, [22, 18, 8, 54, 24, 20, 10, 12, 42, 54, 16, 14, 32], []),
    ]
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types_xml(len(sheets)))
        archive.writestr("_rels/.rels", ROOT_RELS_XML)
        archive.writestr("xl/workbook.xml", workbook_xml([sheet[0] for sheet in sheets]))
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels_xml(len(sheets)))
        archive.writestr("xl/styles.xml", STYLES_XML)
        for index, (_name, columns, sheet_rows, widths, intro_rows) in enumerate(sheets, start=1):
            archive.writestr(
                f"xl/worksheets/sheet{index}.xml",
                build_sheet_xml(columns, sheet_rows, widths, intro_rows=intro_rows),
            )


def format_display_row(row: dict[str, Any]) -> dict[str, Any]:
    display = dict(row)
    display["semantic_score"] = format_score_percent(row.get("semantic_score"))
    display["min_similarity"] = format_score_percent(row.get("min_similarity"))
    return display


def build_model_rows(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    by_model: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_model.setdefault(str(row["model"]), []).append(row)
    output: list[dict[str, str]] = []
    for model, model_rows in sorted(by_model.items()):
        total = len(model_rows)
        labels = count_by(model_rows, "semantic_label")
        consistent = labels.get("consistent", 0) + labels.get("mostly_consistent", 0)
        output.append(
            {
                "model": model,
                "total": str(total),
                "consistent_count": str(consistent),
                "consistent_rate": format_percent(consistent / total if total else None),
                "consistent": str(labels.get("consistent", 0)),
                "mostly_consistent": str(labels.get("mostly_consistent", 0)),
                "partially_inconsistent": str(labels.get("partially_inconsistent", 0)),
                "contradictory": str(labels.get("contradictory", 0)),
                "invalid": str(labels.get("invalid", 0)),
            }
        )
    return output


def count_by(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key) or "")
        counts[value] = counts.get(value, 0) + 1
    return counts


def format_percent(value: float | None) -> str:
    return "" if value is None else f"{value:.1%}"


def format_score_percent(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        return f"{float(text):.1%}"
    except ValueError:
        return text


def build_sheet_xml(
    columns: list[tuple[str, str]],
    rows: list[dict[str, Any]],
    widths: list[int],
    *,
    intro_rows: list[str] | None = None,
) -> str:
    intro_rows = intro_rows or []
    header_row_index = 1
    data_start_row_index = header_row_index + 1
    xml_rows: list[str] = []
    xml_rows.append(build_row_xml(header_row_index, [label for _key, label in columns], style="1"))
    for index, row in enumerate(rows, start=data_start_row_index):
        xml_rows.append(build_row_xml(index, [str(row.get(key, "")) for key, _label in columns], style="2"))
    intro_start_row_index = data_start_row_index + len(rows) + 1
    for offset, text in enumerate(intro_rows):
        xml_rows.append(build_intro_row_xml(intro_start_row_index + offset, text, max(1, len(columns))))
    column_xml = "".join(
        f'<col min="{idx}" max="{idx}" width="{width}" customWidth="1"/>'
        for idx, width in enumerate(widths, start=1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<cols>{column_xml}</cols>"
        f"<sheetViews><sheetView workbookViewId=\"0\"><pane ySplit=\"{header_row_index}\" topLeftCell=\"A{data_start_row_index}\" "
        "activePane=\"bottomLeft\" state=\"frozen\"/></sheetView></sheetViews>"
        f"<sheetData>{''.join(xml_rows)}</sheetData>"
        f"<autoFilter ref=\"A{header_row_index}:{column_name(len(columns))}{header_row_index}\"/>"
        "</worksheet>"
    )


def build_intro_row_xml(row_index: int, text: str, column_count: int) -> str:
    values = [text] + [""] * (column_count - 1)
    style = "3" if text else "2"
    return build_row_xml(row_index, values, style=style)


def build_row_xml(row_index: int, values: list[str], style: str) -> str:
    cells = []
    for column_index, value in enumerate(values, start=1):
        cell_ref = f"{column_name(column_index)}{row_index}"
        cells.append(f'<c r="{cell_ref}" s="{style}" t="inlineStr"><is><t>{excel_cell_text(value)}</t></is></c>')
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
  <cellXfs count="4">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
    <xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1" applyAlignment="1"><alignment wrapText="1" vertical="top"/></xf>
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment wrapText="1" vertical="top"/></xf>
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment wrapText="1" vertical="top"/></xf>
  </cellXfs>
  <cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>"""


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
