"""提供轻量、可停止的周期与每日 Worker 调度器。"""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
SHANGHAI = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True, slots=True)
class ScheduledJob:
    """描述任务名称、执行函数和下一次运行间隔计算。"""

    name: str
    run: Callable[[], Awaitable[bool]]
    next_delay: Callable[[datetime], float]

    @classmethod
    def periodic(
        cls,
        name: str,
        run: Callable[[], Awaitable[bool]],
        *,
        interval_seconds: int,
        initial_delay_seconds: int = 5,
    ) -> "ScheduledJob":
        """创建启动后短暂延迟、随后固定间隔执行的任务。"""
        first = True

        def delay(_: datetime) -> float:
            """首次使用启动延迟，其后使用固定间隔。"""
            nonlocal first
            value = initial_delay_seconds if first else interval_seconds
            first = False
            return float(value)

        return cls(name=name, run=run, next_delay=delay)

    @classmethod
    def daily(
        cls,
        name: str,
        run: Callable[[], Awaitable[bool]],
        *,
        hour: int,
        minute: int,
        initial_delay_seconds: int | None = None,
    ) -> "ScheduledJob":
        """创建可在启动后先执行一次、随后按上海时区定时的任务。"""
        first = initial_delay_seconds is not None

        def delay(now: datetime) -> float:
            """计算严格晚于当前时刻的下一次本地运行间隔。"""
            nonlocal first
            if first:
                first = False
                return float(initial_delay_seconds or 1)
            local_now = now.astimezone(SHANGHAI)
            target = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if target <= local_now:
                target += timedelta(days=1)
            return max(1.0, (target - local_now).total_seconds())

        return cls(name=name, run=run, next_delay=delay)


class WorkerScheduler:
    """串行触发到期任务，并允许容器信号立即停止等待。"""

    def __init__(self, jobs: Sequence[ScheduledJob]) -> None:
        """保存不可变任务列表，避免运行期动态扩展调度范围。"""
        self._jobs = tuple(jobs)

    async def run(self, stop: asyncio.Event) -> None:
        """循环等待最近任务，到期执行后重新计算下一次时间。"""
        loop = asyncio.get_running_loop()
        deadlines = {
            job.name: loop.time() + job.next_delay(datetime.now(SHANGHAI))
            for job in self._jobs
        }
        while not stop.is_set():
            now = loop.time()
            due = [job for job in self._jobs if deadlines[job.name] <= now]
            if due:
                for job in due:
                    try:
                        await job.run()
                    except Exception as error:
                        logger.error(
                            "调度任务异常 name=%s error_type=%s",
                            job.name,
                            type(error).__name__,
                        )
                    deadlines[job.name] = loop.time() + job.next_delay(
                        datetime.now(SHANGHAI)
                    )
                continue

            timeout = min(deadlines.values()) - now if deadlines else 3600.0
            try:
                await asyncio.wait_for(stop.wait(), timeout=max(0.1, timeout))
            except TimeoutError:
                continue
