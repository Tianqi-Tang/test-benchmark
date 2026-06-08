from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

APP_ROOT = Path(__file__).resolve().parent
STATIC_DIR = APP_ROOT / "static"

app = FastAPI(title="test-benchmark", version="0.1.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "test-benchmark",
        "time": datetime.now(timezone.utc).isoformat(),
    }
