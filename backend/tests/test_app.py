from fastapi.testclient import TestClient
import pytest

from app.database import _database_url
from app import evaluation_runner
from app.evaluation_runner import PROGRESS_COMPLETED_STATUSES
from app.llm import providers
from app.llm.client import call_model
from app.main import _capability_values, _model_score_out, _result_is_retryable, app
from app.models import BenchmarkQuestion, EvaluationResult, EvaluationRun, ModelConfig
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


def test_model_config_allows_large_max_output_tokens():
    payload = ModelConfigCreate(
        name="Large Context",
        provider="openai_responses",
        model="large-output-model",
        maxOutputTokens=200000,
    )

    assert payload.maxOutputTokens == 200000


def test_model_config_rejects_extreme_max_output_tokens():
    with pytest.raises(ValueError):
        ModelConfigCreate(
            name="Too Large",
            provider="openai_responses",
            model="large-output-model",
            maxOutputTokens=1048577,
        )


def test_model_config_create_rejects_blank_name_after_trim():
    with pytest.raises(ValueError):
        ModelConfigCreate(name="   ", provider="deepseek", model="deepseek-v4-pro")


def test_model_config_update_rejects_blank_name_after_trim():
    with pytest.raises(ValueError):
        ModelConfigUpdate(name="   ")


def test_nvidia_provider_uses_nim_model_alias_and_payload(monkeypatch):
    captured = {}

    def fake_stream_chat_completion(_client, url, headers, payload):
        captured["url"] = url
        captured["headers"] = headers
        captured["payload"] = payload
        return "OK", {"stream": True, "text": "OK", "chunks": []}

    monkeypatch.setattr(providers, "_stream_chat_completion", fake_stream_chat_completion)
    config = ModelConfig(
        provider="nvidia",
        model="deepseek-v4-pro",
        api_key="nvidia-key",
        max_output_tokens=16384,
    )

    text, _raw, request = providers.call_provider(config, "hello", None, max_attempts=1)

    payload = captured["payload"]
    assert text == "OK"
    assert captured["url"] == "https://integrate.api.nvidia.com/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer nvidia-key"
    assert request["url"] == "https://integrate.api.nvidia.com/v1/chat/completions"
    assert request["headers"]["Authorization"] == "Bearer ***"
    assert payload["model"] == "deepseek-ai/deepseek-v4-pro"
    assert request["json"]["model"] == "deepseek-ai/deepseek-v4-pro"
    assert payload["max_tokens"] == 16384
    assert payload["chat_template_kwargs"] == {"thinking": False}
    assert payload["stream"] is True
    assert "extra_body" not in payload


def test_nvidia_flash_uses_streaming_payload(monkeypatch):
    captured = {}

    def fake_stream_chat_completion(_client, url, headers, payload):
        captured["url"] = url
        captured["headers"] = headers
        captured["payload"] = payload
        return "OK", {"stream": True, "text": "OK", "chunks": []}

    monkeypatch.setattr(providers, "_stream_chat_completion", fake_stream_chat_completion)
    config = ModelConfig(
        provider="nvidia",
        model="deepseek-v4-flash",
        api_key="nvidia-key",
        max_output_tokens=16384,
    )

    text, _raw, request = providers.call_provider(config, "hello", None, max_attempts=1)

    payload = captured["payload"]
    assert text == "OK"
    assert payload["model"] == "deepseek-ai/deepseek-v4-flash"
    assert request["json"]["model"] == "deepseek-ai/deepseek-v4-flash"
    assert payload["chat_template_kwargs"] == {"thinking": False}
    assert payload["stream"] is True


def test_openrouter_claude_fable_uses_anthropic_provider_route(monkeypatch):
    captured = {}

    class FakeClient:
        def __init__(self, timeout):
            captured["timeout"] = timeout

        def __enter__(self):
            return self

        def __exit__(self, _exc_type, _exc, _traceback):
            return False

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "OK"}}]}

    def fake_post_with_retry(client, url, max_attempts=1, **kwargs):
        captured["client"] = client
        captured["url"] = url
        captured["max_attempts"] = max_attempts
        captured["headers"] = kwargs["headers"]
        captured["payload"] = kwargs["json"]
        return FakeResponse()

    monkeypatch.setattr(providers.httpx, "Client", FakeClient)
    monkeypatch.setattr(providers, "_post_with_retry", fake_post_with_retry)
    config = ModelConfig(
        provider="openrouter",
        model="anthropic/claude-fable-5",
        api_key="openrouter-key",
        max_output_tokens=128000,
    )

    text, _raw, request = providers.call_provider(config, "hello", None, max_attempts=1)

    payload = captured["payload"]
    assert text == "OK"
    assert captured["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer openrouter-key"
    assert request["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert request["headers"]["Authorization"] == "Bearer ***"
    assert payload["model"] == "anthropic/claude-fable-5"
    assert payload["max_tokens"] == 128000
    assert payload["provider"] == {"only": ["anthropic"], "allow_fallbacks": False}
    assert request["json"]["provider"] == {"only": ["anthropic"], "allow_fallbacks": False}
    assert "stream" not in payload


@pytest.mark.parametrize(
    "model_name",
    [
        "qwen/qwen3.7-plus",
        "openai/gpt-5.5",
        "openai/gpt-5.5-pro",
        "deepseek/deepseek-v4-pro",
    ],
)
def test_openrouter_default_provider_route_uses_requested_model(monkeypatch, model_name):
    captured = {}

    class FakeClient:
        def __init__(self, timeout):
            captured["timeout"] = timeout

        def __enter__(self):
            return self

        def __exit__(self, _exc_type, _exc, _traceback):
            return False

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "OK"}}]}

    def fake_post_with_retry(client, url, max_attempts=1, **kwargs):
        captured["client"] = client
        captured["url"] = url
        captured["max_attempts"] = max_attempts
        captured["headers"] = kwargs["headers"]
        captured["payload"] = kwargs["json"]
        return FakeResponse()

    monkeypatch.setattr(providers.httpx, "Client", FakeClient)
    monkeypatch.setattr(providers, "_post_with_retry", fake_post_with_retry)
    config = ModelConfig(
        provider="openrouter",
        model=model_name,
        api_key="openrouter-key",
        max_output_tokens=65536,
    )

    text, _raw, request = providers.call_provider(config, "hello", None, max_attempts=1)

    payload = captured["payload"]
    assert text == "OK"
    assert captured["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer openrouter-key"
    assert request["headers"]["Authorization"] == "Bearer ***"
    assert payload["model"] == model_name
    assert payload["max_tokens"] == 65536
    assert "provider" not in payload
    assert "stream" not in payload


def test_nvidia_stream_response_is_aggregated():
    class FakeStream:
        def __enter__(self):
            return self

        def __exit__(self, _exc_type, _exc, _traceback):
            return False

        def raise_for_status(self):
            return None

        def iter_lines(self):
            return iter(
                [
                    'data: {"choices":[{"delta":{"content":"O","reasoning_content":null}}]}',
                    'data: {"choices":[{"delta":{"content":"K","reasoning_content":null}}]}',
                    "data: [DONE]",
                ]
            )

    class FakeClient:
        def stream(self, _method, _url, headers=None, json=None):
            return FakeStream()

    text, raw = providers._stream_chat_completion(FakeClient(), "https://example.test", {}, {})

    assert text == "OK"
    assert raw["stream"] is True
    assert raw["text"] == "OK"
    assert len(raw["chunks"]) == 2


def test_failed_model_call_keeps_redacted_request_log(monkeypatch):
    def fake_stream_chat_completion(_client, _url, _headers, _payload):
        raise TimeoutError("The read operation timed out")

    monkeypatch.setattr(providers, "_stream_chat_completion", fake_stream_chat_completion)
    config = ModelConfig(
        provider="nvidia",
        model="deepseek-v4-pro",
        api_key="nvidia-key",
        max_output_tokens=16384,
    )

    result = call_model(config, "hello", max_attempts=1)

    request = result.raw_response["request"]
    assert result.ok is False
    assert result.error == "The read operation timed out"
    assert result.raw_response["error"] == "The read operation timed out"
    assert request["url"] == "https://integrate.api.nvidia.com/v1/chat/completions"
    assert request["headers"]["Authorization"] == "Bearer ***"
    assert request["json"]["model"] == "deepseek-ai/deepseek-v4-pro"
    assert request["json"]["chat_template_kwargs"] == {"thinking": False}
    assert request["json"]["stream"] is True


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


def test_start_evaluation_run_deduplicates_active_threads(monkeypatch):
    started_run_ids = []

    class FakeThread:
        def __init__(self, target, args, daemon):
            self.args = args

        def start(self):
            started_run_ids.append(self.args[0])

    monkeypatch.setattr(evaluation_runner, "Thread", FakeThread)
    evaluation_runner._active_run_ids.clear()

    try:
        assert evaluation_runner.start_evaluation_run(7) is True
        assert evaluation_runner.start_evaluation_run(7) is False
        assert started_run_ids == [7]
    finally:
        evaluation_runner._active_run_ids.clear()


def test_resume_interrupted_evaluation_runs_schedules_only_active_runs(monkeypatch):
    scheduled_run_ids = []

    class FakeScalars:
        def all(self):
            return [2, 3]

        def __iter__(self):
            return iter([2, 3])

    class FakeDb:
        def __enter__(self):
            return self

        def __exit__(self, _exc_type, _exc, _traceback):
            return False

        def scalars(self, statement):
            compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
            assert "evaluation_runs.status IN ('pending', 'running')" in compiled
            return FakeScalars()

    class FakeSessionMaker:
        def __call__(self):
            return FakeDb()

    monkeypatch.setattr(evaluation_runner, "get_sessionmaker", lambda: FakeSessionMaker())
    monkeypatch.setattr(evaluation_runner, "start_evaluation_run", lambda run_id: scheduled_run_ids.append(run_id) or True)

    assert evaluation_runner.resume_interrupted_evaluation_runs() == 2
    assert scheduled_run_ids == [2, 3]


def test_run_evaluation_resumes_only_unfinished_results(monkeypatch):
    processed_result_ids = []
    commits = []

    class FakeScalars:
        def __init__(self, values):
            self.values = values

        def all(self):
            return self.values

        def __iter__(self):
            return iter(self.values)

    class FakeDb:
        def __enter__(self):
            return self

        def __exit__(self, _exc_type, _exc, _traceback):
            return False

        def get(self, model, item_id):
            if model is EvaluationRun:
                return EvaluationRun(id=item_id, status="running", total_count=2)
            return EvaluationResult(id=item_id, evaluation_run_id=11, status="pending")

        def commit(self):
            commits.append(True)

        def scalars(self, statement):
            compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
            assert "evaluation_results.status IN ('pending', 'running')" in compiled
            return FakeScalars([101, 102])

        def scalar(self, _statement):
            return 0

    class FakeSessionMaker:
        def __call__(self):
            return FakeDb()

    def fake_run_result_once(_db, result):
        processed_result_ids.append(result.id)
        result.status = "completed"
        return result

    monkeypatch.setattr(evaluation_runner, "get_sessionmaker", lambda: FakeSessionMaker())
    monkeypatch.setattr(evaluation_runner, "run_result_once", fake_run_result_once)

    evaluation_runner.run_evaluation(11)

    assert processed_result_ids == [101, 102]
    assert commits


def test_run_evaluation_thread_marks_crash_and_releases_active_run(monkeypatch):
    crashed = []

    def fake_run_evaluation(_run_id):
        raise RuntimeError("boom")

    def fake_mark_run_crashed(run_id, error_message):
        crashed.append((run_id, error_message))

    monkeypatch.setattr(evaluation_runner, "run_evaluation", fake_run_evaluation)
    monkeypatch.setattr(evaluation_runner, "_mark_run_crashed", fake_mark_run_crashed)
    evaluation_runner._active_run_ids.clear()
    evaluation_runner._active_run_ids.add(23)

    evaluation_runner._run_evaluation_thread(23)

    assert crashed == [(23, "boom")]
    assert 23 not in evaluation_runner._active_run_ids


def test_mark_run_crashed_fails_active_run_and_unfinished_results(monkeypatch):
    commits = []
    executed = []
    run = EvaluationRun(id=31, status="running", total_count=2)

    class FakeDb:
        def __enter__(self):
            return self

        def __exit__(self, _exc_type, _exc, _traceback):
            return False

        def get(self, model, item_id):
            if model is EvaluationRun and item_id == 31:
                return run
            return None

        def execute(self, statement):
            compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
            assert "evaluation_results.status IN ('pending', 'running')" in compiled
            assert "SET status='failed'" in compiled
            executed.append(compiled)

        def scalar(self, _statement):
            return 0

        def commit(self):
            commits.append(True)

    class FakeSessionMaker:
        def __call__(self):
            return FakeDb()

    monkeypatch.setattr(evaluation_runner, "get_sessionmaker", lambda: FakeSessionMaker())

    evaluation_runner._mark_run_crashed(31, "boom")

    assert run.status == "failed"
    assert run.error_message == "Evaluation worker crashed: boom"
    assert run.finished_at is not None
    assert executed
    assert commits == [True]


def test_mark_run_crashed_keeps_stopped_run_unchanged(monkeypatch):
    commits = []
    run = EvaluationRun(id=32, status="stopped", total_count=2)

    class FakeDb:
        def __enter__(self):
            return self

        def __exit__(self, _exc_type, _exc, _traceback):
            return False

        def get(self, model, item_id):
            if model is EvaluationRun and item_id == 32:
                return run
            return None

        def execute(self, _statement):
            raise AssertionError("stopped runs should not be updated")

        def commit(self):
            commits.append(True)

    class FakeSessionMaker:
        def __call__(self):
            return FakeDb()

    monkeypatch.setattr(evaluation_runner, "get_sessionmaker", lambda: FakeSessionMaker())

    evaluation_runner._mark_run_crashed(32, "boom")

    assert run.status == "stopped"
    assert run.error_message is None
    assert commits == []
