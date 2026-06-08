from __future__ import annotations


def build_prompt(question: str, options: str | None) -> str:
    if options:
        return (
            "请回答下面的医学单选题。只需要先输出一个选项字母 A、B、C、D 或 E，"
            "之后可以用一两句话解释。\n\n"
            f"题目：{question}\n\n选项：\n{options}"
        )
    return f"请回答下面的医学问题，尽量准确、简洁。\n\n问题：{question}"
