"""OpenAPI 生成物与公开字段约束测试。"""

from pathlib import Path

from scripts.generate_openapi import OUTPUT_PATH, generate_openapi


def test_openapi_file_has_no_generation_drift() -> None:
    """版本化契约必须与当前路由生成结果逐字一致。"""
    assert OUTPUT_PATH.read_text(encoding="utf-8") == generate_openapi()


def test_openapi_uses_camel_case_and_stable_error_request_id() -> None:
    """前端依赖的时间字段和错误请求标识必须保持 camelCase。"""
    document = generate_openapi()
    assert '"createdAt"' in document
    assert '"requestId"' in document
    assert '"created_at"' not in document


def test_openapi_is_stored_inside_api_project() -> None:
    """防止脚本误把生成物写到临时或用户目录。"""
    assert Path(__file__).resolve().parents[2] / "openapi.json" == OUTPUT_PATH
