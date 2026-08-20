from __future__ import annotations

import os
from pathlib import Path


def append_ai_review(report: Path, model: str) -> None:
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("未设置 OPENAI_API_KEY")
    from openai import OpenAI

    text = report.read_text(encoding="utf-8")
    prompt = """你是谨慎的股票研究助理。只依据给定量化报告做二次审阅。用中文输出：1) 候选组合共同特征；2) 三项需人工核验的风险；3) 对排名最靠前五只逐一给出支持证据与反对证据。不得添加报告中不存在的事实，不得使用确定性收益表述，结尾注明非投资建议。"""
    response = OpenAI().responses.create(model=model, instructions=prompt, input=text)
    with report.open("a", encoding="utf-8") as handle:
        handle.write("\n## AI 二次审阅\n\n" + response.output_text.strip() + "\n")

