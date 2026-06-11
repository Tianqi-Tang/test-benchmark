import zipfile

from scripts import vision_image_report


def test_build_openai_responses_image_payload_uses_input_image():
    payload = vision_image_report.build_openai_responses_image_payload(
        model="gpt-5.5",
        prompt="read image",
        image_data_url="data:image/jpeg;base64,abc",
        max_output_tokens=2000,
    )

    content = payload["input"][0]["content"]
    assert payload["model"] == "gpt-5.5"
    assert payload["store"] is False
    assert content[0] == {"type": "input_text", "text": "read image"}
    assert content[1] == {"type": "input_image", "image_url": "data:image/jpeg;base64,abc"}


def test_build_gemini_image_payload_uses_inline_data():
    payload = vision_image_report.build_gemini_image_payload(
        prompt="read image",
        image_bytes=b"abc",
        mime_type="image/jpeg",
        max_output_tokens=2000,
    )

    parts = payload["contents"][0]["parts"]
    assert parts[0] == {"text": "read image"}
    assert parts[1]["inline_data"]["mime_type"] == "image/jpeg"
    assert parts[1]["inline_data"]["data"] == "YWJj"
    assert payload["generationConfig"]["maxOutputTokens"] == 2000


def test_build_qwen_vision_image_payload_uses_image_url():
    payload = vision_image_report.build_qwen_vision_image_payload(
        model="qwen3.7-plus",
        prompt="read image",
        image_data_url="data:image/jpeg;base64,abc",
        max_output_tokens=2000,
    )

    content = payload["messages"][0]["content"]
    assert payload["model"] == "qwen3.7-plus"
    assert content[0] == {"type": "text", "text": "read image"}
    assert content[1] == {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,abc"}}


def test_default_targets_skip_gemini_by_default():
    targets = vision_image_report.parse_model_targets(None)

    assert [target.model_names[0] for target in targets] == ["gpt-5.5", "qwen3.7-plus"]
    assert targets[1].provider_options == ("qwen_vision", "qwen")


def test_parse_json_object_accepts_markdown_wrapped_json():
    parsed = vision_image_report.parse_json_object(
        """```json
{"image_type":"检验单","items":[{"name":"白细胞","value":"5.0"}]}
```"""
    )

    assert parsed["image_type"] == "检验单"
    assert parsed["items"][0]["name"] == "白细胞"


def test_write_xlsx_creates_valid_workbook(tmp_path):
    output = tmp_path / "report.xlsx"

    vision_image_report.write_xlsx(
        output,
        [
            {
                "file_name": "检查单1.jpg",
                "status": "success",
                "summary": "测试摘要",
            }
        ],
    )

    with zipfile.ZipFile(output) as archive:
        assert "xl/workbook.xml" in archive.namelist()
        worksheet = archive.read("xl/worksheets/sheet1.xml").decode("utf-8")

    assert "检查单1.jpg" in worksheet
    assert "测试摘要" in worksheet
