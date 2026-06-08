from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
import os
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from .benchmark_importer import BenchmarkImportError, import_custom_medical_eval_sets, import_jsonl_lines
from .database import get_db, init_db
from .evaluation_runner import prepare_run_items, start_evaluation_run, stop_evaluation_run
from .llm_client import call_model
from .models import BenchmarkQuestion, BenchmarkSet, EvaluationResult, EvaluationRun, ModelConfig
from .schemas import (
    BenchmarkQuestionOut,
    BenchmarkQuestionUpdate,
    BenchmarkSetOut,
    EvaluationResultOut,
    EvaluationRunCreate,
    EvaluationRunOut,
    ImportResultOut,
    ModelConfigCreate,
    ModelConfigOut,
    ModelConfigUpdate,
    ModelScoreOut,
    ModelTestOut,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if os.getenv("DATABASE_URL"):
        init_db()
    yield


app = FastAPI(title="test-benchmark API", version="0.1.0", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "test-benchmark",
        "time": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/health")
def api_health() -> dict[str, str]:
    return health()


@app.get("/api/models", response_model=list[ModelConfigOut])
def list_models(db: Session = Depends(get_db)) -> list[ModelConfigOut]:
    rows = db.scalars(select(ModelConfig).order_by(ModelConfig.created_at.desc())).all()
    return [_model_out(row) for row in rows]


@app.post("/api/models", response_model=ModelConfigOut)
def create_model(payload: ModelConfigCreate, db: Session = Depends(get_db)) -> ModelConfigOut:
    model_config = ModelConfig(
        name=payload.name.strip(),
        provider=payload.provider.strip(),
        model=payload.model.strip(),
        base_url=_blank_to_none(payload.baseUrl),
        api_key=_blank_to_none(payload.apiKey),
        capability=payload.capability,
        enabled=payload.enabled,
        max_output_tokens=payload.maxOutputTokens,
    )
    db.add(model_config)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Model name already exists.") from exc
    db.refresh(model_config)
    return _model_out(model_config)


@app.get("/api/models/{model_id}", response_model=ModelConfigOut)
def get_model(model_id: int, db: Session = Depends(get_db)) -> ModelConfigOut:
    return _model_out(_get_model_or_404(db, model_id))


@app.put("/api/models/{model_id}", response_model=ModelConfigOut)
def update_model(model_id: int, payload: ModelConfigUpdate, db: Session = Depends(get_db)) -> ModelConfigOut:
    model_config = _get_model_or_404(db, model_id)
    updated_fields = payload.model_fields_set
    if "name" in updated_fields and payload.name is not None:
        model_config.name = payload.name.strip()
    if "provider" in updated_fields and payload.provider is not None:
        model_config.provider = payload.provider.strip()
    if "model" in updated_fields and payload.model is not None:
        model_config.model = payload.model.strip()
    if "baseUrl" in updated_fields:
        model_config.base_url = _blank_to_none(payload.baseUrl)
    if payload.clearApiKey:
        model_config.api_key = None
    elif payload.apiKey:
        model_config.api_key = payload.apiKey
    if "capability" in updated_fields and payload.capability is not None:
        model_config.capability = payload.capability
    if "enabled" in updated_fields and payload.enabled is not None:
        model_config.enabled = payload.enabled
    if "maxOutputTokens" in updated_fields and payload.maxOutputTokens is not None:
        model_config.max_output_tokens = payload.maxOutputTokens

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Model name already exists.") from exc
    db.refresh(model_config)
    return _model_out(model_config)


@app.post("/api/models/{model_id}/test", response_model=ModelTestOut)
def test_model(model_id: int, db: Session = Depends(get_db)) -> ModelTestOut:
    model_config = _get_model_or_404(db, model_id)
    result = call_model(model_config, "Reply with exactly: OK", max_output_tokens=20)
    model_config.last_test_status = "success" if result.ok else "failed"
    model_config.last_test_latency_ms = result.latency_ms
    model_config.last_test_error = None if result.ok else result.error or "Model call failed."
    model_config.last_tested_at = datetime.now(timezone.utc)
    db.commit()
    if not result.ok:
        return ModelTestOut(ok=False, message=result.error or "Model call failed.", latencyMs=result.latency_ms)
    return ModelTestOut(ok=True, message="Model call succeeded.", latencyMs=result.latency_ms, responseText=result.text)


@app.get("/api/benchmark-sets", response_model=list[BenchmarkSetOut])
def list_benchmark_sets(db: Session = Depends(get_db)) -> list[BenchmarkSetOut]:
    rows = db.scalars(select(BenchmarkSet).order_by(BenchmarkSet.created_at.desc())).all()
    return [_benchmark_set_out(row) for row in rows]


@app.post("/api/benchmark-sets/import/custom-medical", response_model=ImportResultOut)
def import_custom_medical(db: Session = Depends(get_db)) -> ImportResultOut:
    try:
        sets = import_custom_medical_eval_sets(db)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ImportResultOut(
        importedSets=[_benchmark_set_out(row) for row in sets],
        totalQuestions=sum(row.question_count for row in sets),
    )


@app.post("/api/benchmark-sets/import/jsonl", response_model=ImportResultOut)
async def import_jsonl_benchmark(file: UploadFile = File(...), db: Session = Depends(get_db)) -> ImportResultOut:
    filename = Path(file.filename or "benchmark.jsonl").name
    if not filename.lower().endswith(".jsonl"):
        raise HTTPException(status_code=400, detail="Only JSONL files are supported.")
    content = await file.read()
    try:
        text = content.decode("utf-8")
        benchmark_set = import_jsonl_lines(
            db,
            text.splitlines(),
            name=Path(filename).stem,
            source_path=f"upload://{filename}",
        )
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="File must be UTF-8 encoded.") from exc
    except BenchmarkImportError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSONL at line {exc.row_number}: {exc}") from exc
    return ImportResultOut(importedSets=[_benchmark_set_out(benchmark_set)], totalQuestions=benchmark_set.question_count)


@app.get("/api/benchmark-sets/{benchmark_set_id}", response_model=BenchmarkSetOut)
def get_benchmark_set(benchmark_set_id: int, db: Session = Depends(get_db)) -> BenchmarkSetOut:
    return _benchmark_set_out(_get_benchmark_set_or_404(db, benchmark_set_id))


@app.get("/api/benchmark-sets/{benchmark_set_id}/questions", response_model=list[BenchmarkQuestionOut])
def list_questions(
    benchmark_set_id: int,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[BenchmarkQuestionOut]:
    _get_benchmark_set_or_404(db, benchmark_set_id)
    rows = db.scalars(
        select(BenchmarkQuestion)
        .where(BenchmarkQuestion.benchmark_set_id == benchmark_set_id)
        .order_by(BenchmarkQuestion.source_row)
        .offset(offset)
        .limit(limit)
    ).all()
    return [_question_out(row) for row in rows]


@app.put("/api/benchmark-questions/{question_id}", response_model=BenchmarkQuestionOut)
def update_question(question_id: int, payload: BenchmarkQuestionUpdate, db: Session = Depends(get_db)) -> BenchmarkQuestionOut:
    question = db.get(BenchmarkQuestion, question_id)
    if question is None:
        raise HTTPException(status_code=404, detail="Benchmark question not found.")
    updated_fields = payload.model_fields_set
    if "questionType" in updated_fields and payload.questionType is not None:
        question.question_type = payload.questionType
    if "question" in updated_fields and payload.question is not None:
        question.question = payload.question.strip()
    if "options" in updated_fields:
        question.options = _blank_to_none(payload.options)
    if "answer" in updated_fields and payload.answer is not None:
        question.answer = payload.answer.strip()
    question.raw = {
        **(question.raw or {}),
        "question": question.question,
        "options": question.options,
        "answer": question.answer,
    }
    db.commit()
    db.refresh(question)
    return _question_out(question)


@app.delete("/api/benchmark-questions/{question_id}")
def delete_question(question_id: int, db: Session = Depends(get_db)) -> dict[str, bool]:
    question = db.get(BenchmarkQuestion, question_id)
    if question is None:
        raise HTTPException(status_code=404, detail="Benchmark question not found.")
    benchmark_set = db.get(BenchmarkSet, question.benchmark_set_id)
    db.delete(question)
    if benchmark_set is not None:
        benchmark_set.question_count = max(0, benchmark_set.question_count - 1)
    db.commit()
    return {"ok": True}


@app.post("/api/evaluation-runs", response_model=EvaluationRunOut)
def create_evaluation_run(payload: EvaluationRunCreate, db: Session = Depends(get_db)) -> EvaluationRunOut:
    benchmark_set = _get_benchmark_set_or_404(db, payload.benchmarkSetId)
    questions = db.scalars(
        select(BenchmarkQuestion)
        .where(BenchmarkQuestion.benchmark_set_id == benchmark_set.id)
        .order_by(BenchmarkQuestion.source_row)
    ).all()
    if not questions:
        raise HTTPException(status_code=400, detail="Benchmark set has no questions.")

    model_configs = db.scalars(
        select(ModelConfig).where(ModelConfig.id.in_(payload.modelConfigIds), ModelConfig.enabled.is_(True))
    ).all()
    if len(model_configs) != len(set(payload.modelConfigIds)):
        raise HTTPException(status_code=400, detail="One or more model configs do not exist or are disabled.")
    if any(not _model_supports_capability(model_config, "text") for model_config in model_configs):
        raise HTTPException(status_code=400, detail="Current text benchmarks require models with text capability.")

    run = EvaluationRun(
        benchmark_set_id=benchmark_set.id,
        status="pending",
        total_count=len(model_configs) * len(questions),
    )
    db.add(run)
    db.flush()
    prepare_run_items(db, run, list(model_configs), list(questions))
    db.commit()
    db.refresh(run)
    start_evaluation_run(run.id)
    return _run_out(run, benchmark_set.name)


@app.get("/api/evaluation-runs", response_model=list[EvaluationRunOut])
def list_evaluation_runs(db: Session = Depends(get_db)) -> list[EvaluationRunOut]:
    rows = db.scalars(
        select(EvaluationRun)
        .options(selectinload(EvaluationRun.benchmark_set))
        .order_by(EvaluationRun.created_at.desc())
        .limit(50)
    ).all()
    return [_run_out(row, row.benchmark_set.name if row.benchmark_set else None) for row in rows]


@app.get("/api/evaluation-runs/{run_id}", response_model=EvaluationRunOut)
def get_evaluation_run(run_id: int, db: Session = Depends(get_db)) -> EvaluationRunOut:
    run = db.scalar(
        select(EvaluationRun)
        .options(selectinload(EvaluationRun.benchmark_set))
        .where(EvaluationRun.id == run_id)
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Evaluation run not found.")
    return _run_out(run, run.benchmark_set.name if run.benchmark_set else None)


@app.post("/api/evaluation-runs/{run_id}/stop", response_model=EvaluationRunOut)
def stop_run(run_id: int, db: Session = Depends(get_db)) -> EvaluationRunOut:
    run = db.scalar(
        select(EvaluationRun)
        .options(selectinload(EvaluationRun.benchmark_set))
        .where(EvaluationRun.id == run_id)
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Evaluation run not found.")
    stop_evaluation_run(db, run)
    return _run_out(run, run.benchmark_set.name if run.benchmark_set else None)


@app.get("/api/evaluation-runs/{run_id}/results", response_model=list[EvaluationResultOut])
def list_evaluation_results(run_id: int, db: Session = Depends(get_db)) -> list[EvaluationResultOut]:
    if db.get(EvaluationRun, run_id) is None:
        raise HTTPException(status_code=404, detail="Evaluation run not found.")
    rows = db.scalars(
        select(EvaluationResult)
        .options(selectinload(EvaluationResult.model_config), selectinload(EvaluationResult.question))
        .where(EvaluationResult.evaluation_run_id == run_id)
        .order_by(EvaluationResult.id)
    ).all()
    return [_result_out(row) for row in rows]


@app.get("/api/dashboard/model-scores", response_model=list[ModelScoreOut])
def list_model_scores(db: Session = Depends(get_db)) -> list[ModelScoreOut]:
    model_configs = db.scalars(
        select(ModelConfig)
        .order_by(ModelConfig.name)
    ).all()
    return [_model_score_out(db, row) for row in model_configs]


def _get_model_or_404(db: Session, model_id: int) -> ModelConfig:
    model_config = db.get(ModelConfig, model_id)
    if model_config is None:
        raise HTTPException(status_code=404, detail="Model config not found.")
    return model_config


def _get_benchmark_set_or_404(db: Session, benchmark_set_id: int) -> BenchmarkSet:
    benchmark_set = db.get(BenchmarkSet, benchmark_set_id)
    if benchmark_set is None:
        raise HTTPException(status_code=404, detail="Benchmark set not found.")
    return benchmark_set


def _mask_key(api_key: str | None) -> str:
    if not api_key:
        return ""
    if len(api_key) <= 4:
        return "****"
    return f"****...{api_key[-4:]}"


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _capability_values(value: str | None) -> set[str]:
    return {part.strip() for part in (value or "").split(",") if part.strip()}


def _model_supports_capability(model_config: ModelConfig, capability: str) -> bool:
    return capability in _capability_values(model_config.capability)


def _model_out(row: ModelConfig) -> ModelConfigOut:
    return ModelConfigOut(
        id=row.id,
        name=row.name,
        provider=row.provider,
        model=row.model,
        baseUrl=row.base_url,
        apiKeyMasked=_mask_key(row.api_key),
        capability=row.capability,
        enabled=row.enabled,
        maxOutputTokens=row.max_output_tokens,
        lastTestStatus=row.last_test_status,
        lastTestLatencyMs=row.last_test_latency_ms,
        lastTestError=row.last_test_error,
        lastTestedAt=row.last_tested_at,
        createdAt=row.created_at,
        updatedAt=row.updated_at,
    )


def _benchmark_set_out(row: BenchmarkSet) -> BenchmarkSetOut:
    return BenchmarkSetOut(
        id=row.id,
        name=row.name,
        category=row.category,
        sourcePath=row.source_path,
        modality=row.modality,
        questionCount=row.question_count,
        createdAt=row.created_at,
        updatedAt=row.updated_at,
    )


def _question_out(row: BenchmarkQuestion) -> BenchmarkQuestionOut:
    return BenchmarkQuestionOut(
        id=row.id,
        sourceRow=row.source_row,
        questionType=row.question_type,
        question=row.question,
        options=row.options,
        answer=row.answer,
    )


def _run_out(row: EvaluationRun, benchmark_set_name: str | None = None) -> EvaluationRunOut:
    return EvaluationRunOut(
        id=row.id,
        benchmarkSetId=row.benchmark_set_id,
        benchmarkSetName=benchmark_set_name,
        status=row.status,
        totalCount=row.total_count,
        completedCount=row.completed_count,
        correctCount=row.correct_count,
        accuracy=row.accuracy,
        errorMessage=row.error_message,
        createdAt=row.created_at,
        startedAt=row.started_at,
        finishedAt=row.finished_at,
    )


def _result_out(row: EvaluationResult) -> EvaluationResultOut:
    question = row.question
    model_config = row.model_config
    return EvaluationResultOut(
        id=row.id,
        evaluationRunId=row.evaluation_run_id,
        modelConfigId=row.model_config_id,
        modelName=model_config.name if model_config else None,
        benchmarkQuestionId=row.benchmark_question_id,
        question=question.question if question else None,
        options=question.options if question else None,
        questionType=question.question_type if question else None,
        status=row.status,
        prompt=row.prompt,
        expectedAnswer=row.expected_answer,
        modelAnswer=row.model_answer,
        extractedAnswer=row.extracted_answer,
        isCorrect=row.is_correct,
        score=row.score,
        latencyMs=row.latency_ms,
        errorMessage=row.error_message,
        createdAt=row.created_at,
        updatedAt=row.updated_at,
    )


def _model_score_out(db: Session, model_config: ModelConfig) -> ModelScoreOut:
    latest_run = db.scalar(
        select(EvaluationRun)
        .join(EvaluationResult, EvaluationResult.evaluation_run_id == EvaluationRun.id)
        .options(selectinload(EvaluationRun.benchmark_set))
        .where(EvaluationResult.model_config_id == model_config.id)
        .order_by(EvaluationRun.created_at.desc(), EvaluationRun.id.desc())
        .limit(1)
    )
    if latest_run is None:
        return ModelScoreOut(
            modelConfigId=model_config.id,
            modelName=model_config.name,
            provider=model_config.provider,
            model=model_config.model,
            capability=model_config.capability,
            latestRunId=None,
            latestRunStatus=None,
            benchmarkSetName=None,
            latestEvaluatedAt=None,
            totalCount=0,
            scoredCount=0,
            correctCount=0,
            accuracy=0.0,
        )

    results = db.scalars(
        select(EvaluationResult).where(
            EvaluationResult.evaluation_run_id == latest_run.id,
            EvaluationResult.model_config_id == model_config.id,
        )
    ).all()
    scored_count = sum(1 for row in results if row.is_correct is not None)
    correct_count = sum(1 for row in results if row.is_correct is True)
    accuracy = float(correct_count / scored_count) if scored_count else 0.0
    latest_at = latest_run.finished_at or latest_run.started_at or latest_run.created_at
    return ModelScoreOut(
        modelConfigId=model_config.id,
        modelName=model_config.name,
        provider=model_config.provider,
        model=model_config.model,
        capability=model_config.capability,
        latestRunId=latest_run.id,
        latestRunStatus=latest_run.status,
        benchmarkSetName=latest_run.benchmark_set.name if latest_run.benchmark_set else None,
        latestEvaluatedAt=latest_at,
        totalCount=len(results),
        scoredCount=scored_count,
        correctCount=correct_count,
        accuracy=accuracy,
    )
