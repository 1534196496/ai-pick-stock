"""定义跨模块一致的 API 错误契约与异常处理。"""

import logging
from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class ErrorDetail(BaseModel):
    """描述客户端可稳定匹配且带请求追踪标识的 API 错误。"""

    model_config = ConfigDict(populate_by_name=True)

    code: str
    message: str
    details: dict[str, Any] | None = None
    request_id: str = Field(alias="requestId")


class ErrorResponse(BaseModel):
    """统一包装所有 API 错误。"""

    error: ErrorDetail


class ApiError(Exception):
    """表示可安全公开给客户端的预期 API 错误。"""

    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        """保存状态码和稳定错误字段，不接收内部异常文本。"""
        super().__init__(code)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details
        self.headers = headers


def get_request_id(request: Request) -> str:
    """读取请求上下文中由中间件生成或校验后的请求标识。"""
    request_id = getattr(request.state, "request_id", None)
    if isinstance(request_id, str):
        return request_id
    return "req_unavailable"


def create_error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    request_id: str,
    details: dict[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    """创建不包含内部实现细节的统一 JSON 错误响应。"""
    response_headers = {"X-Request-ID": request_id}
    if headers:
        response_headers.update(headers)
    content = ErrorResponse(
        error=ErrorDetail(
            code=code,
            message=message,
            details=details,
            request_id=request_id,
        )
    ).model_dump(mode="json", by_alias=True, exclude_none=True)
    return JSONResponse(
        status_code=status_code,
        content=content,
        headers=response_headers,
    )


def register_error_handlers(application: FastAPI) -> None:
    """为应用注册业务、框架、校验和未知异常的统一处理器。"""

    @application.exception_handler(ApiError)
    async def handle_api_error(request: Request, error: ApiError) -> JSONResponse:
        """把预期业务异常转换为稳定错误结构。"""
        return create_error_response(
            status_code=error.status_code,
            code=error.code,
            message=error.message,
            details=error.details,
            request_id=get_request_id(request),
            headers=error.headers,
        )

    @application.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request,
        error: RequestValidationError,
    ) -> JSONResponse:
        """仅公开字段位置和校验类型，不回显原始输入或异常上下文。"""
        fields = [
            {
                "field": ".".join(str(part) for part in item["loc"] if part != "body"),
                "type": item["type"],
            }
            for item in error.errors()
        ]
        return create_error_response(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code="VALIDATION_ERROR",
            message="请求字段校验失败",
            details={"fields": fields},
            request_id=get_request_id(request),
        )

    @application.exception_handler(StarletteHTTPException)
    async def handle_http_error(
        request: Request,
        error: StarletteHTTPException,
    ) -> JSONResponse:
        """统一框架路由错误和仍使用 HTTPException 的模块错误。"""
        code, message, details = _http_error_fields(error)
        return create_error_response(
            status_code=error.status_code,
            code=code,
            message=message,
            details=details,
            request_id=get_request_id(request),
            headers=error.headers,
        )

    @application.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, error: Exception) -> JSONResponse:
        """隐藏未知异常内容，并仅记录异常类型和请求标识。"""
        request_id = get_request_id(request)
        logger.error(
            "未处理 API 异常 type=%s request_id=%s",
            type(error).__name__,
            request_id,
        )
        return create_error_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="INTERNAL_SERVER_ERROR",
            message="服务器暂时无法处理请求",
            request_id=request_id,
        )


def _http_error_fields(
    error: StarletteHTTPException,
) -> tuple[str, str, dict[str, Any] | None]:
    """从安全字典读取模块错误，其他框架错误使用固定公开文案。"""
    detail: object = error.detail
    if isinstance(detail, dict):
        code = detail.get("code")
        message = detail.get("message")
        details = detail.get("details")
        if isinstance(code, str) and isinstance(message, str):
            return code, message, details if isinstance(details, dict) else None

    defaults = {
        status.HTTP_400_BAD_REQUEST: ("BAD_REQUEST", "请求无法处理"),
        status.HTTP_401_UNAUTHORIZED: ("AUTHENTICATION_REQUIRED", "请先登录"),
        status.HTTP_403_FORBIDDEN: ("FORBIDDEN", "无权执行此操作"),
        status.HTTP_404_NOT_FOUND: ("NOT_FOUND", "请求的资源不存在"),
        status.HTTP_405_METHOD_NOT_ALLOWED: ("METHOD_NOT_ALLOWED", "请求方法不允许"),
    }
    code, message = defaults.get(
        error.status_code,
        ("HTTP_ERROR", "请求无法处理"),
    )
    return code, message, None
