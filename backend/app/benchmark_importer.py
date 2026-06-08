from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterable

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .models import BenchmarkQuestion, BenchmarkSet


ROOT_DIR = Path(__file__).resolve().parents[2]


def custom_benchmark_dir() -> Path:
    configured = os.getenv("BENCHMARK_DATA_DIR")
    if configured:
        return Path(configured) / "custom_medical_eval_sets"
    for candidate in (
        ROOT_DIR / "data" / "benchmarks" / "custom_medical_eval_sets",
        Path("/data/benchmarks/custom_medical_eval_sets"),
    ):
        if candidate.exists():
            return candidate
    return ROOT_DIR / "data" / "benchmarks" / "custom_medical_eval_sets"


def _set_name(path: Path) -> str:
    name = path.stem
    prefix = "dataset_upload_prod_"
    suffix = "_0_59300178"
    if name.startswith(prefix):
        name = name[len(prefix) :]
    if name.endswith(suffix):
        name = name[: -len(suffix)]
    return name


def _question_type(raw: dict) -> str:
    return "choice" if str(raw.get("options") or "").strip() else "qa"


class BenchmarkImportError(ValueError):
    def __init__(self, row_number: int, message: str):
        super().__init__(message)
        self.row_number = row_number


def import_jsonl_lines(
    db: Session,
    lines: Iterable[str],
    name: str,
    source_path: str,
    category: str = "uploaded_jsonl",
) -> BenchmarkSet:
    benchmark_set = db.scalar(select(BenchmarkSet).where(BenchmarkSet.name == name))
    if benchmark_set is None:
        benchmark_set = BenchmarkSet(
            name=name,
            category=category,
            source_path=source_path,
            modality="text",
        )
        db.add(benchmark_set)
        db.flush()
    else:
        benchmark_set.category = category
        benchmark_set.source_path = source_path
        benchmark_set.modality = "text"
        db.execute(delete(BenchmarkQuestion).where(BenchmarkQuestion.benchmark_set_id == benchmark_set.id))
        db.flush()

    count = 0
    for row_number, line in enumerate(lines, start=1):
        line = line.strip()
        if not line:
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise BenchmarkImportError(row_number, exc.msg) from exc
        question = str(raw.get("question") or "").strip()
        answer = str(raw.get("answer") or "").strip()
        if not question or not answer:
            continue
        db.add(
            BenchmarkQuestion(
                benchmark_set_id=benchmark_set.id,
                source_row=row_number,
                question_type=_question_type(raw),
                question=question,
                options=str(raw.get("options") or "").strip() or None,
                answer=answer,
                raw=raw,
            )
        )
        count += 1

    benchmark_set.question_count = count
    db.commit()
    db.refresh(benchmark_set)
    return benchmark_set


def import_custom_medical_eval_sets(db: Session) -> list[BenchmarkSet]:
    CUSTOM_BENCHMARK_DIR = custom_benchmark_dir()
    if not CUSTOM_BENCHMARK_DIR.exists():
        raise FileNotFoundError(f"Benchmark directory not found: {CUSTOM_BENCHMARK_DIR}")

    imported_sets: list[BenchmarkSet] = []
    for path in sorted(CUSTOM_BENCHMARK_DIR.glob("*.jsonl")):
        benchmark_set = db.scalar(select(BenchmarkSet).where(BenchmarkSet.name == _set_name(path)))
        if benchmark_set is None:
            benchmark_set = BenchmarkSet(
                name=_set_name(path),
                category="custom_medical_eval_sets",
                source_path=str(path),
                modality="text",
            )
            db.add(benchmark_set)
            db.flush()
        else:
            benchmark_set.source_path = str(path)
            benchmark_set.category = "custom_medical_eval_sets"
            benchmark_set.modality = "text"
            db.execute(delete(BenchmarkQuestion).where(BenchmarkQuestion.benchmark_set_id == benchmark_set.id))
            db.flush()

        with path.open("r", encoding="utf-8") as file:
            imported = import_jsonl_lines(db, file, _set_name(path), str(path), category="custom_medical_eval_sets")
        benchmark_set.question_count = imported.question_count
        imported_sets.append(benchmark_set)

    for benchmark_set in imported_sets:
        db.refresh(benchmark_set)
    return imported_sets
