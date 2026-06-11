from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


MAX_OUTPUT_TOKENS_LIMIT = 1048576


class LoginRequest(BaseModel):
    password: str = Field(min_length=1)


class SessionOut(BaseModel):
    authenticated: bool
    authConfigured: bool


class ModelConfigCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    provider: str = Field(min_length=1, max_length=80)
    model: str = Field(min_length=1, max_length=160)
    baseUrl: Optional[str] = None
    apiKey: Optional[str] = None
    capability: str = "text"
    enabled: bool = True
    maxOutputTokens: int = Field(default=2048, ge=128, le=MAX_OUTPUT_TOKENS_LIMIT)

    @field_validator("name", "provider", "model", mode="before")
    @classmethod
    def trim_required_string(cls, value: str) -> str:
        if isinstance(value, str):
            return value.strip()
        return value


class ModelConfigUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    provider: Optional[str] = Field(default=None, min_length=1, max_length=80)
    model: Optional[str] = Field(default=None, min_length=1, max_length=160)
    baseUrl: Optional[str] = None
    apiKey: Optional[str] = None
    clearApiKey: bool = False
    capability: Optional[str] = None
    enabled: Optional[bool] = None
    maxOutputTokens: Optional[int] = Field(default=None, ge=128, le=MAX_OUTPUT_TOKENS_LIMIT)

    @field_validator("name", "provider", "model", mode="before")
    @classmethod
    def trim_required_string(cls, value: str | None) -> str | None:
        if isinstance(value, str):
            return value.strip()
        return value


class ModelConfigOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    provider: str
    model: str
    baseUrl: Optional[str]
    apiKeyMasked: str
    capability: str
    enabled: bool
    maxOutputTokens: int
    lastTestStatus: Optional[str]
    lastTestLatencyMs: Optional[int]
    lastTestError: Optional[str]
    lastTestRawResponse: Optional[dict[str, Any]]
    lastTestedAt: Optional[datetime]
    createdAt: datetime
    updatedAt: datetime


class ModelTestOut(BaseModel):
    ok: bool
    message: str
    latencyMs: Optional[int] = None
    responseText: Optional[str] = None
    rawResponse: Optional[dict[str, Any]] = None


class ModelScoreOut(BaseModel):
    modelConfigId: int
    modelName: str
    provider: str
    model: str
    capability: str
    latestRunId: Optional[int]
    latestRunStatus: Optional[str]
    benchmarkSetName: Optional[str]
    latestEvaluatedAt: Optional[datetime]
    totalCount: int
    completedCount: int
    scoredCount: int
    correctCount: int
    accuracy: float


class BenchmarkSetOut(BaseModel):
    id: int
    name: str
    category: str
    sourcePath: Optional[str]
    modality: str
    questionCount: int
    requiresJudge: bool
    createdAt: datetime
    updatedAt: datetime


class BenchmarkSetUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=180)


class BenchmarkQuestionOut(BaseModel):
    id: int
    sourceRow: int
    questionType: str
    question: str
    options: Optional[str]
    answer: str
    maxScore: float


class BenchmarkQuestionUpdate(BaseModel):
    questionType: Optional[str] = None
    question: Optional[str] = Field(default=None, min_length=1)
    options: Optional[str] = None
    answer: Optional[str] = Field(default=None, min_length=1)


class ImportResultOut(BaseModel):
    importedSets: List[BenchmarkSetOut]
    totalQuestions: int


class EvaluationRunCreate(BaseModel):
    benchmarkSetId: int
    modelConfigIds: List[int] = Field(min_length=1)
    judgeModelConfigIds: dict[int, int] = Field(default_factory=dict)


class EvaluationRunOut(BaseModel):
    id: int
    benchmarkSetId: int
    benchmarkSetName: Optional[str] = None
    modelNames: List[str] = Field(default_factory=list)
    judgeModelName: Optional[str] = None
    status: str
    totalCount: int
    completedCount: int
    correctCount: int
    accuracy: float
    errorMessage: Optional[str]
    createdAt: datetime
    startedAt: Optional[datetime]
    finishedAt: Optional[datetime]


class EvaluationResultOut(BaseModel):
    id: int
    evaluationRunId: int
    modelConfigId: int
    modelName: Optional[str] = None
    benchmarkQuestionId: int
    questionSourceRow: Optional[int] = None
    question: Optional[str] = None
    options: Optional[str] = None
    questionType: Optional[str] = None
    status: str
    prompt: str
    expectedAnswer: str
    maxScore: float
    modelAnswer: Optional[str]
    rawResponse: Optional[dict]
    extractedAnswer: Optional[str]
    isCorrect: Optional[bool]
    score: Optional[float]
    judgeModelConfigId: Optional[int]
    judgeModelName: Optional[str] = None
    judgeStatus: Optional[str]
    judgeScoreRatio: Optional[float]
    judgeReason: Optional[str]
    judgePrompt: Optional[str] = None
    judgeRawResponse: Optional[dict]
    latencyMs: Optional[int]
    errorMessage: Optional[str]
    createdAt: datetime
    updatedAt: datetime
