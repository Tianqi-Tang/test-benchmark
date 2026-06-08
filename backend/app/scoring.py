from __future__ import annotations

import re

from .models import BenchmarkQuestion


CHOICE_PATTERN = re.compile(r"(?<![A-Za-z])([A-E])(?![A-Za-z])", re.IGNORECASE)


def normalize_text(value: str | None) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", "", value).strip().lower()


def normalize_choice(value: str | None) -> str:
    if not value:
        return ""
    match = CHOICE_PATTERN.search(value.strip())
    if match:
        return match.group(1).upper()
    stripped = value.strip().upper()
    return stripped[:1] if stripped[:1] in {"A", "B", "C", "D", "E"} else ""


def extract_answer(question: BenchmarkQuestion, model_answer: str | None) -> str:
    if question.question_type == "choice":
        return normalize_choice(model_answer)
    return (model_answer or "").strip()


def score_answer(question: BenchmarkQuestion, model_answer: str | None) -> tuple[str, bool | None, float | None]:
    extracted = extract_answer(question, model_answer)
    expected = question.answer.strip()

    if question.question_type == "choice":
        correct = normalize_choice(expected) == extracted
        return extracted, correct, 1.0 if correct else 0.0

    normalized_expected = normalize_text(expected)
    normalized_actual = normalize_text(extracted)
    if not normalized_expected or not normalized_actual:
        return extracted, False, 0.0
    if normalized_expected == normalized_actual:
        return extracted, True, 1.0
    if len(normalized_expected) <= 80 and normalized_expected in normalized_actual:
        return extracted, True, 1.0
    return extracted, None, None
