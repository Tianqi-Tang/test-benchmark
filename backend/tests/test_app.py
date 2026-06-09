from fastapi.testclient import TestClient
import pytest

from app.database import _database_url
from app.evaluation_runner import PROGRESS_COMPLETED_STATUSES
from app.main import _capability_values, _model_score_out, _result_is_retryable, app
from app.models import BenchmarkQuestion, EvaluationResult, ModelConfig
from app.scoring import normalize_choice, score_answer
from app.schemas import ModelConfigCreate, ModelConfigUpdate


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


def test_business_api_requires_auth_configuration(monkeypatch):
    monkeypatch.delenv("TEST_BENCHMARK_AUTH_PASSWORD", raising=False)
    client = TestClient(app)

    response = client.get("/api/models")

    assert response.status_code == 503


def test_login_sets_session_cookie(monkeypatch):
    monkeypatch.setenv("TEST_BENCHMARK_AUTH_PASSWORD", "local-secret")
    client = TestClient(app)

    response = client.post("/api/auth/login", json={"password": "local-secret"})

    assert response.status_code == 200
    assert response.json()["authenticated"] is True
    assert "test_benchmark_session" in response.cookies


def test_login_rejects_wrong_password(monkeypatch):
    monkeypatch.setenv("TEST_BENCHMARK_AUTH_PASSWORD", "local-secret")
    client = TestClient(app)

    response = client.post("/api/auth/login", json={"password": "wrong"})

    assert response.status_code == 401


def test_database_url_requires_postgresql(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///local.db")

    with pytest.raises(RuntimeError, match="PostgreSQL"):
        _database_url()


def test_choice_answer_extraction():
    assert normalize_choice("答案是 B。") == "B"
    assert normalize_choice("b") == "B"
    assert normalize_choice("选项：D") == "D"


def test_choice_scoring_uses_question_max_score():
    question = BenchmarkQuestion(question_type="choice", answer="B", max_score=2.5)

    extracted, correct, score = score_answer(question, "答案是 B。")

    assert extracted == "B"
    assert correct is True
    assert score == 2.5


def test_capability_values_parse_multiple_capabilities():
    assert _capability_values("text,vision") == {"text", "vision"}
    assert _capability_values(" text , vision , ") == {"text", "vision"}


def test_model_config_create_trims_required_strings():
    payload = ModelConfigCreate(name=" DeepSeek ", provider=" deepseek ", model=" deepseek-v4-pro ")

    assert payload.name == "DeepSeek"
    assert payload.provider == "deepseek"
    assert payload.model == "deepseek-v4-pro"


def test_model_config_create_rejects_blank_name_after_trim():
    with pytest.raises(ValueError):
        ModelConfigCreate(name="   ", provider="deepseek", model="deepseek-v4-pro")


def test_model_config_update_rejects_blank_name_after_trim():
    with pytest.raises(ValueError):
        ModelConfigUpdate(name="   ")


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


def test_result_is_retryable_for_judge_failed():
    assert _result_is_retryable(EvaluationResult(status="judge_failed")) is True


def test_result_is_retryable_for_completed_without_extracted_answer():
    result = EvaluationResult(status="completed", model_answer="模型回答", extracted_answer="")

    assert _result_is_retryable(result) is True


def test_result_is_not_retryable_for_successful_completed_result():
    result = EvaluationResult(status="completed", model_answer="模型回答", extracted_answer="A")

    assert _result_is_retryable(result) is False


def test_stopped_results_do_not_count_as_progress_completed():
    assert "completed" in PROGRESS_COMPLETED_STATUSES
    assert "failed" in PROGRESS_COMPLETED_STATUSES
    assert "judge_failed" in PROGRESS_COMPLETED_STATUSES
    assert "stopped" not in PROGRESS_COMPLETED_STATUSES
