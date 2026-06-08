from fastapi.testclient import TestClient

from app.main import app


def test_health_endpoint():
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["service"] == "test-benchmark"


def test_index_page():
    client = TestClient(app)

    response = client.get("/")

    assert response.status_code == 200
    assert "test-benchmark" in response.text
