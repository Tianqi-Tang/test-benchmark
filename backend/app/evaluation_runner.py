from __future__ import annotations

from threading import Thread

from sqlalchemy import func, select, update

from .database import get_sessionmaker
from .llm import call_model
from .models import BenchmarkQuestion, EvaluationResult, EvaluationRun, ModelConfig, utc_now
from .prompt_builder import build_prompt
from .scoring import score_answer


PROGRESS_COMPLETED_STATUSES = ("completed", "failed")


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


def prepare_run_items(db, run: EvaluationRun, model_configs: list[ModelConfig], questions: list[BenchmarkQuestion]) -> None:
    for model_config in model_configs:
        for question in questions:
            prompt = build_prompt(question.question, question.options)
            db.add(
                EvaluationResult(
                    evaluation_run_id=run.id,
                    model_config_id=model_config.id,
                    benchmark_question_id=question.id,
                    prompt=prompt,
                    expected_answer=question.answer,
                    status="pending",
                )
            )


def run_result_once(db, result: EvaluationResult) -> EvaluationResult:
    model_config = db.get(ModelConfig, result.model_config_id)
    question = db.get(BenchmarkQuestion, result.benchmark_question_id)
    if model_config is None or question is None:
        result.status = "failed"
        result.error_message = "Model config or benchmark question no longer exists."
        db.commit()
        _refresh_run_progress(db, result.evaluation_run_id)
        return result

    result.status = "running"
    result.model_answer = None
    result.extracted_answer = None
    result.is_correct = None
    result.score = None
    result.latency_ms = None
    result.error_message = None
    result.raw_response = None
    db.commit()

    llm_result = call_model(model_config, result.prompt)
    result.latency_ms = llm_result.latency_ms
    result.raw_response = llm_result.raw_response

    if llm_result.ok:
        result.model_answer = llm_result.text
        extracted, correct, score = score_answer(question, llm_result.text)
        result.extracted_answer = extracted
        result.is_correct = correct
        result.score = score
        result.status = "completed"
    else:
        result.status = "failed"
        result.error_message = llm_result.error

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
    scored_count = db.scalar(
        select(func.count(EvaluationResult.id)).where(
            EvaluationResult.evaluation_run_id == run_id,
            EvaluationResult.is_correct.is_not(None),
        )
    ) or 0
    run.completed_count = int(completed_count)
    run.correct_count = int(correct_count)
    run.accuracy = float(correct_count / scored_count) if scored_count else 0.0
    if commit:
        db.commit()
