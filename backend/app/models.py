from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ModelConfig(Base):
    __tablename__ = "model_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    provider: Mapped[str] = mapped_column(String(80), index=True)
    model: Mapped[str] = mapped_column(String(160))
    base_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    api_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    capability: Mapped[str] = mapped_column(String(40), default="text")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    max_output_tokens: Mapped[int] = mapped_column(Integer, default=2048)
    last_test_status: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    last_test_latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    last_test_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_test_raw_response: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    last_tested_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    results: Mapped[List["EvaluationResult"]] = relationship(
        back_populates="model_config",
        foreign_keys="EvaluationResult.model_config_id",
    )


class BenchmarkSet(Base):
    __tablename__ = "benchmark_sets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(180), unique=True, index=True)
    category: Mapped[str] = mapped_column(String(80), default="custom_medical_eval_sets")
    source_path: Mapped[Optional[str]] = mapped_column(String(800), nullable=True)
    modality: Mapped[str] = mapped_column(String(40), default="text")
    question_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    questions: Mapped[List["BenchmarkQuestion"]] = relationship(
        back_populates="benchmark_set",
        cascade="all, delete-orphan",
        order_by="BenchmarkQuestion.source_row",
    )
    runs: Mapped[List["EvaluationRun"]] = relationship(back_populates="benchmark_set")


class BenchmarkQuestion(Base):
    __tablename__ = "benchmark_questions"
    __table_args__ = (
        UniqueConstraint("benchmark_set_id", "source_row", name="uq_benchmark_question_source_row"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    benchmark_set_id: Mapped[int] = mapped_column(ForeignKey("benchmark_sets.id", ondelete="CASCADE"), index=True)
    source_row: Mapped[int] = mapped_column(Integer)
    question_type: Mapped[str] = mapped_column(String(40), default="qa")
    question: Mapped[str] = mapped_column(Text)
    options: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    answer: Mapped[str] = mapped_column(Text)
    max_score: Mapped[float] = mapped_column(Float, default=1.0)
    raw: Mapped[Dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    benchmark_set: Mapped["BenchmarkSet"] = relationship(back_populates="questions")
    results: Mapped[List["EvaluationResult"]] = relationship(back_populates="question")


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    benchmark_set_id: Mapped[int] = mapped_column(ForeignKey("benchmark_sets.id", ondelete="CASCADE"), index=True)
    judge_model_config_id: Mapped[Optional[int]] = mapped_column(ForeignKey("model_configs.id", ondelete="SET NULL"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(40), default="pending", index=True)
    total_count: Mapped[int] = mapped_column(Integer, default=0)
    completed_count: Mapped[int] = mapped_column(Integer, default=0)
    correct_count: Mapped[int] = mapped_column(Integer, default=0)
    accuracy: Mapped[float] = mapped_column(Float, default=0.0)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    benchmark_set: Mapped["BenchmarkSet"] = relationship(back_populates="runs")
    judge_model_config: Mapped[Optional["ModelConfig"]] = relationship(foreign_keys=[judge_model_config_id])
    results: Mapped[List["EvaluationResult"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
    )


class EvaluationResult(Base):
    __tablename__ = "evaluation_results"
    __table_args__ = (
        UniqueConstraint("evaluation_run_id", "model_config_id", "benchmark_question_id", name="uq_eval_result_item"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    evaluation_run_id: Mapped[int] = mapped_column(ForeignKey("evaluation_runs.id", ondelete="CASCADE"), index=True)
    model_config_id: Mapped[int] = mapped_column(ForeignKey("model_configs.id", ondelete="CASCADE"), index=True)
    benchmark_question_id: Mapped[int] = mapped_column(ForeignKey("benchmark_questions.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(40), default="pending", index=True)
    prompt: Mapped[str] = mapped_column(Text)
    expected_answer: Mapped[str] = mapped_column(Text)
    max_score: Mapped[float] = mapped_column(Float, default=1.0)
    model_answer: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    extracted_answer: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_correct: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    judge_model_config_id: Mapped[Optional[int]] = mapped_column(ForeignKey("model_configs.id", ondelete="SET NULL"), nullable=True, index=True)
    judge_status: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    judge_score_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    judge_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    judge_raw_response: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    raw_response: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    run: Mapped["EvaluationRun"] = relationship(back_populates="results")
    model_config: Mapped["ModelConfig"] = relationship(back_populates="results", foreign_keys=[model_config_id])
    judge_model_config: Mapped[Optional["ModelConfig"]] = relationship(foreign_keys=[judge_model_config_id])
    question: Mapped["BenchmarkQuestion"] = relationship(back_populates="results")
