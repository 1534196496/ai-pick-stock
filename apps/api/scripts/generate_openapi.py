"""以确定性格式生成供前端与 CI 校验的 OpenAPI 契约。"""

import json
from pathlib import Path

from app.main import create_app

OUTPUT_PATH = Path(__file__).resolve().parents[1] / "openapi.json"


def generate_openapi() -> str:
    """生成排序稳定且以换行结尾的 OpenAPI JSON。"""
    document = create_app().openapi()
    return json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main() -> None:
    """把当前 FastAPI 契约写入版本化文件。"""
    OUTPUT_PATH.write_text(generate_openapi(), encoding="utf-8")


if __name__ == "__main__":
    main()
