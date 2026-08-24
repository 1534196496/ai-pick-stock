"""从 FastAPI 应用生成确定性的 OpenAPI 契约文件。"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.main import create_app  # noqa: E402


def main() -> None:
    """按稳定键序写入仓库内的 OpenAPI JSON，供契约评审与前端生成。"""
    output_path = PROJECT_ROOT / "openapi.json"
    content = json.dumps(
        create_app().openapi(),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    output_path.write_text(f"{content}\n", encoding="utf-8")


if __name__ == "__main__":
    main()
