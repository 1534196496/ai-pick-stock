"""Provider 共享异步 HTTP、超时与保守重试边界。"""

import asyncio
import random
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

import httpx

_RETRYABLE_STATUS = frozenset({429, 502, 503, 504})


class ProviderUnavailableError(Exception):
    """表示外部来源在超时和有限重试后仍不可用。"""


class ProviderPayloadError(Exception):
    """表示外部响应可达但结构或编码不符合契约。"""


@dataclass(frozen=True, slots=True)
class HttpPayload:
    """保存响应正文、编码和来源状态，不暴露请求敏感头。"""

    content: bytes
    encoding: str
    status_code: int

    def text(self) -> str:
        """按 Provider 明确指定或响应声明的编码解码正文。"""
        try:
            return self.content.decode(self.encoding)
        except UnicodeDecodeError as error:
            raise ProviderPayloadError("外部响应编码无效") from error


class ProviderHttpClient:
    """复用连接池并执行有限、可测试的指数退避。"""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        jitter: Callable[[], float] = random.random,
    ) -> None:
        """允许测试替换 HTTP、休眠和抖动实现。"""
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(12, connect=5),
            follow_redirects=True,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            trust_env=False,
        )
        self._sleep = sleep
        self._jitter = jitter

    async def get(
        self,
        url: str,
        *,
        params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
        encoding: str | None = None,
    ) -> HttpPayload:
        """GET 只重试连接错误和明确可恢复状态，最多三次尝试。"""
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = await self._client.get(url, params=params, headers=headers)
                if response.status_code not in _RETRYABLE_STATUS:
                    response.raise_for_status()
                    return HttpPayload(
                        content=response.content,
                        encoding=encoding or response.encoding or "utf-8",
                        status_code=response.status_code,
                    )
                last_error = ProviderUnavailableError(
                    f"来源暂时不可用 status={response.status_code}"
                )
                retry_after = _retry_after_seconds(response.headers.get("Retry-After"))
            except (httpx.TimeoutException, httpx.NetworkError) as error:
                last_error = error
                retry_after = None
            except httpx.HTTPStatusError as error:
                raise ProviderUnavailableError(
                    f"来源拒绝请求 status={error.response.status_code}"
                ) from error
            if attempt < 2:
                delay = retry_after if retry_after is not None else (0.5, 1.5)[attempt]
                await self._sleep(delay + self._jitter() * 0.1)
        raise ProviderUnavailableError("外部来源重试后仍不可用") from last_error

    async def close(self) -> None:
        """只关闭由当前边界创建的连接池。"""
        if self._owns_client:
            await self._client.aclose()


def _retry_after_seconds(value: str | None) -> float | None:
    """只接受 0–60 秒的数字 Retry-After，避免异常长时间阻塞任务。"""
    if value is None or not value.isdigit():
        return None
    return min(60.0, float(value))
