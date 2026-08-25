"""请求标识、同源 CSRF 防护和认证限流中间件。"""

import hashlib
from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import Request, status
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from app.core.errors import api_error_response

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_AUTH_RATE_LIMIT_PATHS = frozenset(
    {
        "/api/v1/auth/registrations",
        "/api/v1/auth/sessions",
        "/api/v1/auth/password-reset-requests",
        "/api/v1/auth/password-resets",
    }
)
_CSRF_HEADER = "X-CSRF-Token"


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    """描述认证请求需要等待的秒数。"""

    retry_after_seconds: int


@runtime_checkable
class AuthenticationRateLimiter(Protocol):
    """定义可由内存或共享存储实现的认证限流边界。"""

    async def check(self, *, scope: str, client_key: str) -> RateLimitDecision | None:
        """未超限返回空，超限返回客户端重试时间。"""
        ...


class AllowAllAuthenticationRateLimiter:
    """在强化限流任务完成前提供显式的无状态默认实现。"""

    async def check(self, *, scope: str, client_key: str) -> RateLimitDecision | None:
        """允许请求通过，同时保持调用端与后续实现解耦。"""
        return None


class RequestSecurityMiddleware(BaseHTTPMiddleware):
    """为 API 请求建立追踪上下文并阻止跨站状态变更。"""

    def __init__(
        self,
        app: object,
        *,
        authentication_rate_limiter: AuthenticationRateLimiter,
    ) -> None:
        """注入认证限流契约，避免中间件绑定具体存储。"""
        super().__init__(app)  # type: ignore[arg-type]
        self._authentication_rate_limiter = authentication_rate_limiter

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        """依次应用请求 ID、Origin/CSRF 和认证限流规则。"""
        request_id = _resolve_request_id(request.headers.get("X-Request-ID"))
        request.state.request_id = request_id

        if request.url.path.startswith("/api/") and request.method not in _SAFE_METHODS:
            rejection = _validate_state_changing_request(request, request_id=request_id)
            if rejection is not None:
                return rejection

        if request.method == "POST" and request.url.path in _AUTH_RATE_LIMIT_PATHS:
            decision = await self._authentication_rate_limiter.check(
                scope=request.url.path,
                client_key=_client_key(request),
            )
            if decision is not None:
                retry_after = max(1, decision.retry_after_seconds)
                return api_error_response(
                    request_id=request_id,
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    code="AUTH_RATE_LIMITED",
                    message="请求过于频繁，请稍后重试",
                    details={"retryAfterSeconds": retry_after},
                    headers={"Retry-After": str(retry_after)},
                )

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response


def _resolve_request_id(candidate: str | None) -> str:
    """接受有限 ASCII 标识，否则生成不可预测服务端请求 ID。"""
    if (
        candidate
        and candidate.isascii()
        and 1 <= len(candidate) <= 64
        and all(character.isalnum() or character in "._-" for character in candidate)
    ):
        return candidate
    return f"req_{uuid4().hex}"


def _validate_state_changing_request(
    request: Request,
    *,
    request_id: str,
) -> Response | None:
    """要求同源 Origin 和足够长的自定义 CSRF 请求头。"""
    origin = request.headers.get("Origin")
    if origin is None:
        return api_error_response(
            request_id=request_id,
            status_code=status.HTTP_403_FORBIDDEN,
            code="ORIGIN_REQUIRED",
            message="状态变更请求缺少 Origin",
        )
    if not _is_same_origin(request, origin):
        return api_error_response(
            request_id=request_id,
            status_code=status.HTTP_403_FORBIDDEN,
            code="ORIGIN_NOT_ALLOWED",
            message="请求来源不受信任",
        )

    csrf_token = request.headers.get(_CSRF_HEADER)
    if csrf_token is None or not csrf_token.isascii() or len(csrf_token) < 16:
        return api_error_response(
            request_id=request_id,
            status_code=status.HTTP_403_FORBIDDEN,
            code="CSRF_TOKEN_REQUIRED",
            message="状态变更请求缺少有效的 CSRF 令牌",
        )
    return None


def _is_same_origin(request: Request, origin: str) -> bool:
    """比较规范化 scheme、host 和端口，拒绝带路径或凭据的 Origin。"""
    parsed = urlsplit(origin)
    if parsed.username or parsed.password or parsed.path not in {"", "/"}:
        return False
    if parsed.query or parsed.fragment:
        return False
    if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
        return False
    expected = urlsplit(f"//{request.headers.get('host', '')}")
    return (parsed.hostname, parsed.port) == (expected.hostname, expected.port)


def _client_key(request: Request) -> str:
    """对连接地址做不可逆摘要，避免限流存储保留原始 IP。"""
    host = request.client.host if request.client is not None else "unknown"
    return hashlib.sha256(host.encode("utf-8")).hexdigest()
