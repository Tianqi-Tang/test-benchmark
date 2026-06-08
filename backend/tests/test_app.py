from fastapi.testclient import TestClient
import pytest

from app.database import _database_url
from app.evaluation_runner import PROGRESS_COMPLETED_STATUSES
from app.main import _capability_values, _model_score_out, app
from app.models import ModelConfig
from app.scoring import normalize_choice


def test_health_endpoint():
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["service"] == "test-benchmark"


def test_api_health_endpoint():
    client = TestClient(app)

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["service"] == "test-benchmark"


def test_database_url_requires_postgresql(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///local.db")

    with pytest.raises(RuntimeError, match="PostgreSQL"):
        _database_url()


def test_choice_answer_extraction():
    assert normalize_choice("答案是 B。") == "B"
    assert normalize_choice("b") == "B"
    assert normalize_choice("选项：D") == "D"


def test_capability_values_parse_multiple_capabilities():
    assert _capability_values("text,vision") == {"text", "vision"}
    assert _capability_values(" text , vision , ") == {"text", "vision"}


def test_model_score_out_includes_unevaluated_model():
    class EmptyDb:
        def scalar(self, _statement):
            return None

    model = ModelConfig(
        id=12,
        name="Gemini Test",
        provider="gemini",
        model="gemini-3.5-flash",
        capability="text,vision",
        enabled=True,
        max_output_tokens=2048,
    )

    score = _model_score_out(EmptyDb(), model)

    assert score.modelConfigId == 12
    assert score.modelName == "Gemini Test"
    assert score.latestRunId is None
    assert score.scoredCount == 0
    assert score.accuracy == 0.0


def test_stopped_results_do_not_count_as_progress_completed():
    assert "completed" in PROGRESS_COMPLETED_STATUSES
    assert "failed" in PROGRESS_COMPLETED_STATUSES
    assert "stopped" not in PROGRESS_COMPLETED_STATUSES
