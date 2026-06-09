from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


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
    maxOutputTokens: int = Field(default=2048, ge=128, le=32768)

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
    maxOutputTokens: Optional[int] = Field(default=None, ge=128, le=32768)

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
    lastTestedAt: Optional[datetime]
    createdAt: datetime
    updatedAt: datetime


class ModelTestOut(BaseModel):
    ok: bool
    message: str
    latencyMs: Optional[int] = None
    responseText: Optional[str] = None


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


class EvaluationRunOut(BaseModel):
    id: int
    benchmarkSetId: int
    benchmarkSetName: Optional[str] = None
    modelNames: List[str] = Field(default_factory=list)
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
    question: Optional[str] = None
    options: Optional[str] = None
    questionType: Optional[str] = None
    status: str
    prompt: str
    expectedAnswer: str
    modelAnswer: Optional[str]
    extractedAnswer: Optional[str]
    isCorrect: Optional[bool]
    score: Optional[float]
    latencyMs: Optional[int]
    errorMessage: Optional[str]
    createdAt: datetime
    updatedAt: datetime
