from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from .llm import call_model
from .models import BenchmarkQuestion, ModelConfig


@dataclass(frozen=True)
class JudgeScore:
    score_ratio: float
    reason: str
    raw_json: dict[str, Any]
    raw_response: dict[str, Any] | None


def judge_qa_answer(
    judge_model: ModelConfig,
    question: BenchmarkQuestion,
    model_answer: str,
) -> JudgeScore:
    llm_result = call_model(judge_model, build_judge_prompt(question, model_answer), max_output_tokens=1024)
    if not llm_result.ok or not llm_result.text:
        raise ValueError(llm_result.error or "Judge model did not return a response.")

    payload = _parse_judge_payload(llm_result.text)
    score_ratio = payload.get("score_ratio")
    if not isinstance(score_ratio, (int, float)):
        raise ValueError("Judge response missing numeric score_ratio.")
    score_ratio = max(0.0, min(1.0, float(score_ratio)))
    reason = payload.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        reason = "Judge did not provide a reason."
    return JudgeScore(
        score_ratio=score_ratio,
        reason=reason.strip(),
        raw_json=payload,
        raw_response=llm_result.raw_response,
    )


def build_judge_prompt(question: BenchmarkQuestion, model_answer: str) -> str:
    return f"""你是医疗模型评测裁判。请只比较标准答案和评测模型答案这两段文本内容。

评分要求：
- score_ratio 必须是 0.0 到 1.0 的数字。
- 重点评估评测模型答案与标准答案之间的差异。
- 如果评测模型答案与标准答案描述一致或医学含义等价，给 1.0。
- 如果评测模型答案部分覆盖标准答案，按关键医学要点覆盖程度给 0.1 到 0.9。
- 如果差异很大、无法建立等价或部分等价关系、存在严重医学事实错误或危险建议，给 0.0。
- 不要因为表达方式不同扣分。
- 不要基于外部知识重新回答问题，只判断两段答案文本是否一致。

请优先输出 JSON：
{{
  "score_ratio": 0.0,
  "reason": "简要说明评分原因"
}}

如果你的模型能力不支持严格 JSON，也必须在回答中包含下面两行：
score_ratio: 0.0
reason: 简要说明评分原因

标准答案：
{question.answer}

评测模型答案：
{model_answer}
"""


def _parse_judge_payload(text: str) -> dict[str, Any]:
    try:
        return _parse_json_object(text)
    except ValueError:
        return _parse_text_payload(text)


def _parse_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
        if not match:
            raise ValueError("Judge response is not valid JSON.") from None
        payload = json.loads(match.group(0))
    if not isinstance(payload, dict):
        raise ValueError("Judge response JSON must be an object.")
    return payload


def _parse_text_payload(text: str) -> dict[str, Any]:
    score_match = re.search(
        r"(?:score_ratio|score|分数|评分)\s*[:：]\s*([01](?:\.\d+)?|100(?:\.0+)?|[1-9]\d(?:\.\d+)?)",
        text,
        flags=re.IGNORECASE,
    )
    if not score_match:
        raise ValueError("Judge response missing score_ratio.") from None
    score_ratio = float(score_match.group(1))
    if score_ratio > 1:
        score_ratio = score_ratio / 100

    reason_match = re.search(r"(?:reason|理由|原因)\s*[:：]\s*(.+)", text, flags=re.IGNORECASE | re.DOTALL)
    reason = reason_match.group(1).strip() if reason_match else text.strip()
    return {
        "score_ratio": score_ratio,
        "reason": reason,
        "raw_text": text,
    }
