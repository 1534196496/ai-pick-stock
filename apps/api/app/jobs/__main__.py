"""后台任务进程入口。"""

from collections.abc import Callable
from threading import Event

from app.core.config import Settings

_SHUTDOWN_EVENT = Event()


def wait_forever() -> None:
    """阻塞当前进程，直到容器运行时终止该进程。"""
    _SHUTDOWN_EVENT.wait()


def run_worker(*, wait: Callable[[], None] = wait_forever) -> None:
    """校验运行配置并等待后续任务调度器接管执行。"""
    Settings()
    wait()


def main() -> None:
    """启动后台任务进程。"""
    run_worker()


if __name__ == "__main__":
    main()
