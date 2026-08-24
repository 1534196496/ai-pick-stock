"""OpenAPI 生成物、命名和财务字段类型契约测试。"""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from app.main import create_app

OPENAPI_PATH = Path(__file__).resolve().parents[2] / "openapi.json"
FINANCIAL_FIELD_PARTS = ("amount", "shares", "price", "cost", "marketValue", "profit")


def test_committed_openapi_matches_application() -> None:
    """后端契约变化时强制同步评审仓库内 OpenAPI 生成物。"""
    committed = json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))
    assert committed == create_app().openapi()


def test_public_schema_properties_use_camel_case() -> None:
    """公开模型字段不得把 Python snake_case 泄漏到前端契约。"""
    schema = json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))
    properties = list(_iter_properties(schema))

    assert properties
    assert all("_" not in name for name, _ in properties)
    assert any(name == "requestId" for name, _ in properties)
    assert "HTTPValidationError" not in schema["components"]["schemas"]


def test_financial_properties_are_serialized_as_strings() -> None:
    """当前及后续金额、份额、价格和成本字段必须以十进制字符串公开。"""
    schema = json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))
    financial_properties = [
        (name, definition)
        for name, definition in _iter_properties(schema)
        if any(part in name for part in FINANCIAL_FIELD_PARTS)
    ]

    assert all(definition.get("type") == "string" for _, definition in financial_properties)


def _iter_properties(value: Any) -> Iterator[tuple[str, dict[str, Any]]]:
    """递归遍历契约内所有对象属性，供跨模块命名与类型门禁复用。"""
    if isinstance(value, dict):
        properties = value.get("properties")
        if isinstance(properties, dict):
            for name, definition in properties.items():
                if isinstance(name, str) and isinstance(definition, dict):
                    yield name, definition
        for child in value.values():
            yield from _iter_properties(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_properties(child)
