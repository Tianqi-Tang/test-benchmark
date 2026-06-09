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


def score_answer(question: BenchmarkQuestion, model_answer: str | None) -> tuple[str, bool | None, float | None]:
    return score_text_answer(
        question.question_type,
        question.answer,
        model_answer,
        question.max_score,
    )


def score_text_answer(
    question_type: str,
    expected_answer: str,
    model_answer: str | None,
    max_score: float | None = 1.0,
) -> tuple[str, bool | None, float | None]:
    full_score = 1.0 if max_score is None else float(max_score)
    if question_type == "choice":
        extracted = normalize_choice(model_answer)
        correct = normalize_choice(expected_answer) == extracted
        return extracted, correct, full_score if correct else 0.0

    extracted = (model_answer or "").strip()
    expected = expected_answer.strip()
    normalized_expected = normalize_text(expected)
    normalized_actual = normalize_text(extracted)
    if not normalized_expected or not normalized_actual:
        return extracted, False, 0.0
    if normalized_expected == normalized_actual:
        return extracted, True, full_score
    if len(normalized_expected) <= 80 and normalized_expected in normalized_actual:
        return extracted, True, full_score
    return extracted, None, None
