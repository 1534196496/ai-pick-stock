"""API 统一错误契约与异常处理。"""

import logging
from collections.abc import Mapping, Sequence
from typing import Any

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class ApiError(Exception):
    """表示可安全暴露给客户端的稳定 API 错误。"""

    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        details: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        """保存状态码、稳定错误码、修正提示和可选响应头。"""
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = dict(details) if details is not None else None
        self.headers = dict(headers) if headers is not None else None


def request_id_from(request: Request) -> str:
    """读取安全中间件生成的请求标识。"""
    request_id = getattr(request.state, "request_id", None)
    return request_id if isinstance(request_id, str) else "req_unavailable"


def api_error_response(
    *,
    request_id: str,
    status_code: int,
    code: str,
    message: str,
    details: Mapping[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    """构造不泄露内部对象且字段名固定为 camelCase 的错误响应。"""
    error: dict[str, Any] = {
        "code": code,
        "message": message,
    }
    if details is not None:
        error["details"] = dict(details)
    error["requestId"] = request_id
    response_headers = dict(headers) if headers is not None else {}
    response_headers["X-Request-ID"] = request_id
    response_headers["Cache-Control"] = "no-store"
    return JSONResponse(
        status_code=status_code,
        content={"error": error},
        headers=response_headers,
    )


def install_error_handlers(application: FastAPI) -> None:
    """注册领域错误、框架错误、参数错误和未知异常处理器。"""

    @application.exception_handler(ApiError)
    async def handle_api_error(request: Request, error: ApiError) -> JSONResponse:
        """将已分类领域错误转换为统一响应。"""
        return api_error_response(
            request_id=request_id_from(request),
            status_code=error.status_code,
            code=error.code,
            message=error.message,
            details=error.details,
            headers=error.headers,
        )

    @application.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request,
        error: RequestValidationError,
    ) -> JSONResponse:
        """只返回字段路径，不回显密码等非法原始输入。"""
        fields = _validation_fields(error.errors())
        return api_error_response(
            request_id=request_id_from(request),
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code="REQUEST_VALIDATION_FAILED",
            message="请求参数不符合要求",
            details={"fields": fields},
        )

    @application.exception_handler(HTTPException)
    async def handle_http_exception(request: Request, error: HTTPException) -> JSONResponse:
        """兼容框架 HTTP 异常，同时避免把任意内部 detail 直接暴露。"""
        code = "HTTP_ERROR"
        message = "请求无法完成"
        details: Mapping[str, Any] | None = None
        if isinstance(error.detail, Mapping):
            raw_code = error.detail.get("code")
            raw_message = error.detail.get("message")
            raw_details = error.detail.get("details")
            if isinstance(raw_code, str):
                code = raw_code
            if isinstance(raw_message, str):
                message = raw_message
            if isinstance(raw_details, Mapping):
                details = raw_details
        elif error.status_code == status.HTTP_404_NOT_FOUND:
            code = "RESOURCE_NOT_FOUND"
            message = "请求的资源不存在"
        return api_error_response(
            request_id=request_id_from(request),
            status_code=error.status_code,
            code=code,
            message=message,
            details=details,
            headers=error.headers,
        )

    @application.exception_handler(Exception)
    async def handle_unexpected_exception(request: Request, error: Exception) -> JSONResponse:
        """记录请求标识和异常类型，对客户端隐藏堆栈与内部消息。"""
        logger.exception(
            "未处理的 API 异常 request_id=%s exception_type=%s",
            request_id_from(request),
            type(error).__name__,
        )
        return api_error_response(
            request_id=request_id_from(request),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="INTERNAL_SERVER_ERROR",
            message="服务器暂时无法处理请求",
        )


def _validation_fields(errors: Sequence[Mapping[str, Any]]) -> list[str]:
    """把 Pydantic 错误位置转换为去重且顺序稳定的字段路径。"""
    fields: list[str] = []
    for error in errors:
        location = error.get("loc", ())
        if not isinstance(location, (tuple, list)):
            continue
        field = ".".join(str(part) for part in location)
        if field and field not in fields:
            fields.append(field)
    return fields
