import json
import zipfile
from argparse import Namespace
from types import SimpleNamespace

from scripts import medbench_consistency_runner


def test_classify_answers_exact_match_ignores_whitespace():
    result = medbench_consistency_runner.classify_answers(("建议复查。", "建议 复查。", "建议\n复查。"))

    assert result.status == "exact_match"
    assert result.reason == "normalized answers are identical"


def test_classify_answers_flags_empty_answer_as_invalid():
    result = medbench_consistency_runner.classify_answers(("建议复查。", "", "建议随访。"))

    assert result.status == "invalid"
    assert "round_2 empty answer" in result.reason


def test_classify_answers_flags_length_outlier_before_similarity():
    result = medbench_consistency_runner.classify_answers(
        (
            "患者应立即停药并复查血常规。" * 12,
            "患者应立即停药并复查血常规。" * 12,
            "停药。",
        )
    )

    assert result.status == "length_outlier"
    assert "answer length outlier" in result.reason


def test_classify_answers_marks_low_similarity_as_needs_review():
    result = medbench_consistency_runner.classify_answers(
        (
            "需要考虑细菌感染并根据药敏选择抗菌药物。",
            "应优先评估免疫系统疾病并完善自身抗体检查。",
            "建议进行影像学复查并暂不使用抗生素。",
        )
    )

    assert result.status == "needs_review"
    assert result.min_similarity is not None


def test_write_xlsx_creates_summary_and_details_sheets(tmp_path):
    output = tmp_path / "consistency.xlsx"

    medbench_consistency_runner.write_xlsx(
        output,
        [
            {
                "model": "gpt-5.5",
                "file": "MedMC.jsonl",
                "total": "1",
                "stable": "1",
                "stable_rate": "1.000",
                "exact_match": "1",
                "text_similar": "0",
                "length_outlier": "0",
                "invalid": "0",
                "needs_review": "0",
                "issue_count": "0",
            }
        ],
        [
            {
                "model": "gpt-5.5",
                "file": "MedMC.jsonl",
                "line": "1",
                "question": "测试问题",
                "status": "exact_match",
                "reason": "normalized answers are identical",
                "min_similarity": "1.000",
                "similarity_12": "1.000",
                "similarity_13": "1.000",
                "similarity_23": "1.000",
                "chars_round_1": "4",
                "chars_round_2": "4",
                "chars_round_3": "4",
                "answer_round_1": "测试答案",
                "answer_round_2": "测试答案",
                "answer_round_3": "测试答案",
                "other": json.dumps({"id": 1}, ensure_ascii=False),
            }
        ],
    )

    with zipfile.ZipFile(output) as archive:
        assert "xl/worksheets/sheet1.xml" in archive.namelist()
        assert "xl/worksheets/sheet2.xml" in archive.namelist()
        workbook = archive.read("xl/workbook.xml").decode("utf-8")
        details = archive.read("xl/worksheets/sheet2.xml").decode("utf-8")

    assert "Summary" in workbook
    assert "Details" in workbook
    assert "测试问题" in details


def test_run_one_round_runs_only_the_requested_round(monkeypatch, tmp_path):
    events = []

    selected_models = [
        SimpleNamespace(target=SimpleNamespace(display_name="model-a"), config=SimpleNamespace(id=1, provider="p", model="m")),
        SimpleNamespace(target=SimpleNamespace(display_name="model-b"), config=SimpleNamespace(id=2, provider="p", model="m")),
    ]
    source_paths = (tmp_path / "MedMC.jsonl",)
    source_paths[0].write_text(json.dumps({"question": "q", "answer": None}, ensure_ascii=False) + "\n", encoding="utf-8")
    args = Namespace(
        parallel_models=2,
        parallel_files=1,
        round=2,
        raw_root=tmp_path / "raw",
    )

    def fake_run_round_file(selected_model, source_path, round_number, args):
        events.append((round_number, selected_model.target.display_name))
        return medbench_consistency_runner.RoundRunSummary(
            model_name=selected_model.target.display_name,
            round_number=round_number,
            answer_path=tmp_path / f"{round_number}.jsonl",
            total=1,
            attempted_this_run=0,
            answered_this_run=0,
            failures=0,
            remaining=0,
        )

    monkeypatch.setattr(medbench_consistency_runner, "run_round_file", fake_run_round_file)
    monkeypatch.setattr(medbench_consistency_runner, "log", lambda _message: None)

    summaries = medbench_consistency_runner.run_one_round(args, selected_models, source_paths)

    assert [summary.round_number for summary in summaries] == [2, 2]
    assert events == [(2, "model-a"), (2, "model-b")]


def test_run_one_round_reports_remaining_without_advancing(monkeypatch, tmp_path):
    events = []
    selected_models = [
        SimpleNamespace(target=SimpleNamespace(display_name="model-a"), config=SimpleNamespace(id=1, provider="p", model="m")),
    ]
    source_paths = (tmp_path / "MedMC.jsonl",)
    source_paths[0].write_text(json.dumps({"question": "q", "answer": None}, ensure_ascii=False) + "\n", encoding="utf-8")
    args = Namespace(
        parallel_models=1,
        parallel_files=1,
        round=1,
        raw_root=tmp_path / "raw",
    )

    def fake_run_round_file(selected_model, source_path, round_number, args):
        events.append(round_number)
        return medbench_consistency_runner.RoundRunSummary(
            model_name=selected_model.target.display_name,
            round_number=round_number,
            answer_path=tmp_path / f"{round_number}.jsonl",
            total=1,
            attempted_this_run=0,
            answered_this_run=0,
            failures=0,
            remaining=1,
        )

    monkeypatch.setattr(medbench_consistency_runner, "run_round_file", fake_run_round_file)
    monkeypatch.setattr(medbench_consistency_runner, "log", lambda _message: None)

    summaries = medbench_consistency_runner.run_one_round(args, selected_models, source_paths)

    assert [summary.round_number for summary in summaries] == [1]
    assert events == [1]
