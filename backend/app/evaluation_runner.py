from __future__ import annotations

import logging
from threading import Thread

from sqlalchemy import func, select, update

from .database import get_sessionmaker
from .judging import judge_qa_answer
from .llm import call_model
from .models import BenchmarkQuestion, EvaluationResult, EvaluationRun, ModelConfig, utc_now
from .prompt_builder import build_prompt
from .scoring import score_answer


PROGRESS_COMPLETED_STATUSES = ("completed", "failed", "judge_failed")
logger = logging.getLogger("uvicorn.error")


def start_evaluation_run(run_id: int) -> None:
    thread = Thread(target=run_evaluation, args=(run_id,), daemon=True)
    thread.start()


def stop_evaluation_run(db, run: EvaluationRun) -> None:
    if run.status in {"completed", "failed", "stopped"}:
        return
    _mark_remaining_stopped(db, run.id, commit=False)
    db.commit()
    db.refresh(run)


def run_evaluation(run_id: int) -> None:
    SessionLocal = get_sessionmaker()
    with SessionLocal() as db:
        run = db.get(EvaluationRun, run_id)
        if run is None:
            return
        if run.status == "stopped":
            _mark_remaining_stopped(db, run_id)
            return
        run.status = "running"
        run.started_at = utc_now()
        db.commit()

        result_ids = list(
            db.scalars(
                select(EvaluationResult.id)
                .where(EvaluationResult.evaluation_run_id == run_id)
                .order_by(EvaluationResult.id)
            )
        )

    for result_id in result_ids:
        with SessionLocal() as db:
            if _run_status(db, run_id) == "stopped":
                _mark_remaining_stopped(db, run_id)
                break

            result = db.get(EvaluationResult, result_id)
            if result is None:
                continue
            run_result_once(db, result)
            if _run_status(db, run_id) == "stopped":
                result.status = "stopped"
                result.error_message = "Run stopped by user."
                db.commit()
                _refresh_run_progress(db, run_id)
                break

    with SessionLocal() as db:
        run = db.get(EvaluationRun, run_id)
        if run is not None:
            if run.status == "stopped":
                _mark_remaining_stopped(db, run_id, commit=False)
                db.commit()
                return
            failed_count = db.scalar(
                select(func.count(EvaluationResult.id)).where(
                    EvaluationResult.evaluation_run_id == run_id,
                    EvaluationResult.status == "failed",
                )
            )
            run.status = "failed" if failed_count == run.total_count and run.total_count > 0 else "completed"
            run.finished_at = utc_now()
            _refresh_run_progress(db, run_id, commit=False)
            db.commit()


def prepare_run_items(
    db,
    run: EvaluationRun,
    model_configs: list[ModelConfig],
    questions: list[BenchmarkQuestion],
    judge_model_config_id: int | None = None,
) -> None:
    for model_config in model_configs:
        for question in questions:
            prompt = build_prompt(question.question, question.options)
            db.add(
                EvaluationResult(
                    evaluation_run_id=run.id,
                    model_config_id=model_config.id,
                    benchmark_question_id=question.id,
                    judge_model_config_id=judge_model_config_id if question.question_type == "qa" else None,
                    prompt=prompt,
                    expected_answer=question.answer,
                    max_score=question.max_score,
                    status="pending",
                )
            )


def run_result_once(db, result: EvaluationResult) -> EvaluationResult:
    model_config = db.get(ModelConfig, result.model_config_id)
    question = db.get(BenchmarkQuestion, result.benchmark_question_id)
    if model_config is None or question is None:
        result.status = "failed"
        result.error_message = "Model config or benchmark question no longer exists."
        return _finish_result_attempt(db, result)

    should_call_model = not result.model_answer
    _start_result_attempt(db, result, should_call_model)
    if should_call_model:
        if not _populate_model_answer(result, model_config):
            return _finish_result_attempt(db, result)

    if question.question_type == "choice":
        _score_choice_result(result, question)
    else:
        _score_qa_result(db, result, model_config, question)

    return _finish_result_attempt(db, result)


def _start_result_attempt(db, result: EvaluationResult, should_call_model: bool) -> None:
    result.status = "running"
    if should_call_model:
        result.model_answer = None
        result.latency_ms = None
        result.raw_response = None
    result.extracted_answer = None
    result.is_correct = None
    result.score = None
    result.judge_status = None
    result.judge_score_ratio = None
    result.judge_reason = None
    result.judge_raw_response = None
    result.error_message = None
    db.commit()


def _populate_model_answer(result: EvaluationResult, model_config: ModelConfig) -> bool:
    logger.info(
        "llm.call.start run_id=%s result_id=%s question_id=%s model_config_id=%s provider=%s model=%s",
        result.evaluation_run_id,
        result.id,
        result.benchmark_question_id,
        model_config.id,
        model_config.provider,
        model_config.model,
    )
    llm_result = call_model(model_config, result.prompt)
    result.latency_ms = llm_result.latency_ms
    result.raw_response = llm_result.raw_response

    if llm_result.ok:
        logger.info(
            "llm.call.success run_id=%s result_id=%s question_id=%s model_config_id=%s provider=%s model=%s latency_ms=%s",
            result.evaluation_run_id,
            result.id,
            result.benchmark_question_id,
            model_config.id,
            model_config.provider,
            model_config.model,
            llm_result.latency_ms,
        )
        result.model_answer = llm_result.text
        return True

    logger.warning(
        "llm.call.failed run_id=%s result_id=%s question_id=%s model_config_id=%s provider=%s model=%s latency_ms=%s error=%r",
        result.evaluation_run_id,
        result.id,
        result.benchmark_question_id,
        model_config.id,
        model_config.provider,
        model_config.model,
        llm_result.latency_ms,
        llm_result.error,
    )
    result.status = "failed"
    result.error_message = llm_result.error
    return False


def _score_choice_result(result: EvaluationResult, question: BenchmarkQuestion) -> None:
    extracted, correct, score = score_answer(question, result.model_answer)
    result.extracted_answer = extracted
    result.is_correct = correct
    result.score = score
    result.status = "completed"


def _score_qa_result(
    db,
    result: EvaluationResult,
    model_config: ModelConfig,
    question: BenchmarkQuestion,
) -> None:
    judge_model = db.get(ModelConfig, result.judge_model_config_id) if result.judge_model_config_id else None
    if judge_model is None:
        result.status = "judge_failed"
        result.judge_status = "failed"
        result.error_message = "Judge model is not configured."
        return

    try:
        logger.info(
            "judge.call.start run_id=%s result_id=%s question_id=%s model_config_id=%s judge_model_config_id=%s provider=%s model=%s",
            result.evaluation_run_id,
            result.id,
            result.benchmark_question_id,
            model_config.id,
            judge_model.id,
            judge_model.provider,
            judge_model.model,
        )
        judge_score = judge_qa_answer(judge_model, question, result.model_answer or "")
        logger.info(
            "judge.call.success run_id=%s result_id=%s question_id=%s model_config_id=%s judge_model_config_id=%s provider=%s model=%s score_ratio=%.4f",
            result.evaluation_run_id,
            result.id,
            result.benchmark_question_id,
            model_config.id,
            judge_model.id,
            judge_model.provider,
            judge_model.model,
            judge_score.score_ratio,
        )
        result.extracted_answer = result.model_answer
        result.is_correct = judge_score.score_ratio >= 1.0
        result.judge_status = "completed"
        result.judge_score_ratio = judge_score.score_ratio
        result.judge_reason = judge_score.reason
        result.judge_raw_response = {
            "parsed": judge_score.raw_json,
            "raw_response": judge_score.raw_response,
        }
        result.score = result.max_score * judge_score.score_ratio
        result.status = "completed"
    except ValueError as exc:
        logger.warning(
            "judge.call.failed run_id=%s result_id=%s question_id=%s model_config_id=%s judge_model_config_id=%s provider=%s model=%s error=%r",
            result.evaluation_run_id,
            result.id,
            result.benchmark_question_id,
            model_config.id,
            judge_model.id,
            judge_model.provider,
            judge_model.model,
            str(exc),
        )
        result.status = "judge_failed"
        result.judge_status = "failed"
        result.error_message = str(exc)


def _finish_result_attempt(db, result: EvaluationResult) -> EvaluationResult:
    db.commit()
    _refresh_run_progress(db, result.evaluation_run_id)
    db.refresh(result)
    return result


def refresh_run_completion_status(db, run_id: int) -> None:
    run = db.get(EvaluationRun, run_id)
    if run is None or run.status in {"pending", "running", "stopped"}:
        return
    failed_count = db.scalar(
        select(func.count(EvaluationResult.id)).where(
            EvaluationResult.evaluation_run_id == run_id,
            EvaluationResult.status == "failed",
        )
    ) or 0
    run.status = "failed" if failed_count == run.total_count and run.total_count > 0 else "completed"
    run.finished_at = run.finished_at or utc_now()
    _refresh_run_progress(db, run_id, commit=False)
    db.commit()


def _run_status(db, run_id: int) -> str | None:
    return db.scalar(select(EvaluationRun.status).where(EvaluationRun.id == run_id))


def _mark_remaining_stopped(db, run_id: int, commit: bool = True) -> None:
    now = utc_now()
    run = db.get(EvaluationRun, run_id)
    if run is not None:
        run.status = "stopped"
        run.finished_at = run.finished_at or now
    db.execute(
        update(EvaluationResult)
        .where(
            EvaluationResult.evaluation_run_id == run_id,
            EvaluationResult.status.in_(["pending", "running"]),
        )
        .values(status="stopped", error_message="Run stopped by user.", updated_at=now)
    )
    _refresh_run_progress(db, run_id, commit=False)
    if commit:
        db.commit()


def _refresh_run_progress(db, run_id: int, commit: bool = True) -> None:
    run = db.get(EvaluationRun, run_id)
    if run is None:
        return
    completed_count = db.scalar(
        select(func.count(EvaluationResult.id)).where(
            EvaluationResult.evaluation_run_id == run_id,
            EvaluationResult.status.in_(PROGRESS_COMPLETED_STATUSES),
        )
    ) or 0
    correct_count = db.scalar(
        select(func.count(EvaluationResult.id)).where(
            EvaluationResult.evaluation_run_id == run_id,
            EvaluationResult.is_correct.is_(True),
        )
    ) or 0
    total_score = db.scalar(
        select(func.coalesce(func.sum(EvaluationResult.score), 0.0)).where(
            EvaluationResult.evaluation_run_id == run_id,
            EvaluationResult.score.is_not(None),
        )
    ) or 0.0
    total_max_score = db.scalar(
        select(func.coalesce(func.sum(EvaluationResult.max_score), 0.0)).where(
            EvaluationResult.evaluation_run_id == run_id,
            EvaluationResult.score.is_not(None),
        )
    ) or 0.0
    run.completed_count = int(completed_count)
    run.correct_count = int(correct_count)
    run.accuracy = float(total_score / total_max_score) if total_max_score else 0.0
    if commit:
        db.commit()
