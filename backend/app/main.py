from datetime import datetime, timezone

from fastapi import FastAPI

app = FastAPI(title="test-benchmark API", version="0.1.0")


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
