"""提供请求追踪、Origin/CSRF 校验和认证限流中间件。"""

import asyncio
import hashlib
import secrets
import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import Request, Response, status
from starlette.datastructures import MutableHeaders
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.core.config import Settings
from app.core.errors import create_error_response

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
AUTH_RATE_LIMIT_PATHS = {
    "/api/v1/auth/registrations": "registration",
    "/api/v1/auth/sessions": "login",
    "/api/v1/auth/password-reset-requests": "password_reset",
}


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    """描述一次限流检查是否允许继续及建议等待秒数。"""

    allowed: bool
    retry_after_seconds: int = 0


class RateLimiter(Protocol):
    """定义可替换为共享存储实现的异步限流接口。"""

    async def check(
        self,
        *,
        keys: tuple[str, ...],
        limit: int,
        window_seconds: int,
    ) -> RateLimitDecision:
        """原子检查多个去敏维度，并在允许时记录本次请求。"""
        ...


class InMemoryRateLimiter:
    """为单进程部署提供固定时间窗限流，并保留共享实现替换边界。"""

    def __init__(self) -> None:
        """初始化每个去敏键的时间戳队列和并发锁。"""
        self._attempts: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def check(
        self,
        *,
        keys: tuple[str, ...],
        limit: int,
        window_seconds: int,
    ) -> RateLimitDecision:
        """在同一临界区检查所有维度，避免并发请求绕过上限。"""
        now = time.monotonic()
        cutoff = now - window_seconds
        async with self._lock:
            for key in keys:
                attempts = self._attempts[key]
                while attempts and attempts[0] <= cutoff:
                    attempts.popleft()
                if len(attempts) >= limit:
                    retry_after = max(1, int(attempts[0] + window_seconds - now) + 1)
                    return RateLimitDecision(False, retry_after)
            for key in keys:
                self._attempts[key].append(now)
        return RateLimitDecision(True)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """为每个请求建立可信请求 ID，并保证响应可关联。"""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """校验客户端请求 ID，无效时生成服务端标识并写入响应头。"""
        request_id = _resolve_request_id(request.headers.get("X-Request-ID"))
        request.state.request_id = request_id
        MutableHeaders(scope=request.scope)["X-Request-ID"] = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class RequestSecurityMiddleware(BaseHTTPMiddleware):
    """保护 API 写请求，并在认证入口执行去敏的双维度限流。"""

    def __init__(self, app: ASGIApp, *, rate_limiter: RateLimiter) -> None:
        """注入可替换限流器，使测试与后续共享存储实现复用同一契约。"""
        super().__init__(app)
        self._rate_limiter = rate_limiter

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """先验证来源和 CSRF，再限流认证请求并发放双提交 Cookie。"""
        if not request.url.path.startswith("/api/v1"):
            return await call_next(request)

        settings: Settings = request.app.state.settings
        csrf_cookie_name = _csrf_cookie_name(settings)
        csrf_token = request.cookies.get(csrf_cookie_name) or secrets.token_urlsafe(32)

        if request.method not in SAFE_METHODS:
            origin = request.headers.get("Origin")
            if not _is_trusted_origin(request, origin, settings):
                response = _security_error(
                    request,
                    code="ORIGIN_NOT_ALLOWED",
                    message="请求来源不受信任",
                )
                _set_csrf_cookie(response, settings, csrf_cookie_name, csrf_token)
                return response

            submitted_token = request.headers.get("X-CSRF-Token")
            if not submitted_token or not secrets.compare_digest(submitted_token, csrf_token):
                response = _security_error(
                    request,
                    code="CSRF_TOKEN_INVALID",
                    message="CSRF 校验失败，请刷新后重试",
                )
                _set_csrf_cookie(response, settings, csrf_cookie_name, csrf_token)
                return response

            limited_response = await self._check_auth_rate_limit(request)
            if limited_response is not None:
                _set_csrf_cookie(limited_response, settings, csrf_cookie_name, csrf_token)
                return limited_response

        response = await call_next(request)
        if csrf_cookie_name not in request.cookies:
            _set_csrf_cookie(response, settings, csrf_cookie_name, csrf_token)
        return response

    async def _check_auth_rate_limit(self, request: Request) -> Response | None:
        """对认证写入口按来源 IP 和邮箱摘要同时应用固定窗口上限。"""
        action = AUTH_RATE_LIMIT_PATHS.get(request.url.path)
        if request.method != "POST" or action is None:
            return None

        client_host = request.client.host if request.client else "unknown"
        keys = [f"auth:{action}:ip:{client_host}"]
        subject_hash = await _read_subject_hash(request)
        if subject_hash is not None:
            keys.append(f"auth:{action}:subject:{subject_hash}")
        decision = await self._rate_limiter.check(
            keys=tuple(keys),
            limit=10,
            window_seconds=60,
        )
        if decision.allowed:
            return None
        return _security_error(
            request,
            code="AUTH_RATE_LIMITED",
            message="请求过于频繁，请稍后重试",
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            headers={"Retry-After": str(decision.retry_after_seconds)},
        )


def _resolve_request_id(candidate: str | None) -> str:
    """仅接受短 ASCII 标识，避免控制字符和超长值进入日志与响应。"""
    if candidate and candidate.isascii() and len(candidate) <= 64 and candidate.isprintable():
        return candidate
    return f"req_{uuid4().hex}"


def _csrf_cookie_name(settings: Settings) -> str:
    """生产环境使用 Host 前缀限制 Cookie 注入范围。"""
    if settings.environment == "production":
        return "__Host-aipickstock_csrf"
    return "aipickstock_csrf"


def _set_csrf_cookie(
    response: Response,
    settings: Settings,
    name: str,
    token: str,
) -> None:
    """写入可由前端读取的双提交 Cookie，不把令牌放入响应正文。"""
    response.set_cookie(
        key=name,
        value=token,
        path="/",
        secure=settings.environment == "production",
        httponly=False,
        samesite="lax",
    )


def _is_trusted_origin(request: Request, origin: str | None, settings: Settings) -> bool:
    """仅接受规范化同源值或配置中显式列出的开发来源。"""
    normalized = _normalize_origin(origin)
    if normalized is None:
        return False
    request_origin = _normalize_origin(f"{request.url.scheme}://{request.headers.get('host', '')}")
    configured = {_normalize_origin(value) for value in settings.trusted_origins}
    return normalized == request_origin or normalized in configured


def _normalize_origin(value: str | None) -> str | None:
    """拒绝带路径、查询、凭据或非 HTTP(S) 协议的 Origin。"""
    if not value:
        return None
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        return None
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


async def _read_subject_hash(request: Request) -> str | None:
    """从认证 JSON 中提取规范化邮箱摘要，绝不保留或返回完整主体。"""
    try:
        payload = await request.json()
    except (ValueError, UnicodeDecodeError):
        return None
    email = payload.get("email") if isinstance(payload, dict) else None
    if not isinstance(email, str):
        return None
    normalized = email.strip().casefold()
    if not normalized:
        return None
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _security_error(
    request: Request,
    *,
    code: str,
    message: str,
    status_code: int = status.HTTP_403_FORBIDDEN,
    headers: dict[str, str] | None = None,
) -> Response:
    """创建带当前请求 ID 的安全中间件错误。"""
    return create_error_response(
        status_code=status_code,
        code=code,
        message=message,
        request_id=request.state.request_id,
        headers=headers,
    )
