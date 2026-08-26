"""提供轻量、可停止的周期与每日 Worker 调度器。"""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
SHANGHAI = ZoneInfo("Asia/Shanghai")
IntervalValue = int | Callable[[], int]
TimeValue = time | Callable[[], time]


@dataclass(frozen=True, slots=True)
class ScheduledJob:
    """描述任务名称、执行函数和下一次运行间隔计算。"""

    name: str
    run: Callable[[], Awaitable[bool]]
    next_delay: Callable[[datetime], float]
    reschedule_on_revision: bool = False

    @classmethod
    def periodic(
        cls,
        name: str,
        run: Callable[[], Awaitable[bool]],
        *,
        interval_seconds: IntervalValue,
        initial_delay_seconds: int = 5,
        reschedule_on_revision: bool = False,
    ) -> "ScheduledJob":
        """创建启动后短暂延迟、随后固定间隔执行的任务。"""
        first = True

        def delay(_: datetime) -> float:
            """首次使用启动延迟，其后使用固定间隔。"""
            nonlocal first
            value = initial_delay_seconds if first else _interval_value(interval_seconds)
            first = False
            return float(value)

        return cls(
            name=name,
            run=run,
            next_delay=delay,
            reschedule_on_revision=reschedule_on_revision,
        )

    @classmethod
    def daily(
        cls,
        name: str,
        run: Callable[[], Awaitable[bool]],
        *,
        hour: int | Callable[[], int],
        minute: int | Callable[[], int],
        initial_delay_seconds: int | None = None,
        reschedule_on_revision: bool = False,
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
            target = local_now.replace(
                hour=_integer_value(hour),
                minute=_integer_value(minute),
                second=0,
                microsecond=0,
            )
            if target <= local_now:
                target += timedelta(days=1)
            return max(1.0, (target - local_now).total_seconds())

        return cls(
            name=name,
            run=run,
            next_delay=delay,
            reschedule_on_revision=reschedule_on_revision,
        )

    @classmethod
    def windowed_periodic(
        cls,
        name: str,
        run: Callable[[], Awaitable[bool]],
        *,
        interval_seconds: IntervalValue,
        window_start: TimeValue,
        window_end: TimeValue,
        initial_delay_seconds: int = 5,
        reschedule_on_revision: bool = False,
    ) -> "ScheduledJob":
        """创建只在每天指定上海时区窗口内运行的周期任务。"""
        first = True

        def delay(now: datetime) -> float:
            """窗口内按间隔运行，窗口外等待到下一次开始时间。"""
            nonlocal first
            is_first = first
            first = False
            local_now = now.astimezone(SHANGHAI)
            start = _time_value(window_start)
            end = _time_value(window_end)
            if is_time_in_window(local_now.time(), start=start, end=end):
                value = initial_delay_seconds if is_first else _interval_value(interval_seconds)
                return float(value)
            target = local_now.replace(
                hour=start.hour,
                minute=start.minute,
                second=start.second,
                microsecond=0,
            )
            if target <= local_now:
                target += timedelta(days=1)
            return max(1.0, (target - local_now).total_seconds())

        return cls(
            name=name,
            run=run,
            next_delay=delay,
            reschedule_on_revision=reschedule_on_revision,
        )


class WorkerScheduler:
    """串行触发到期任务，并允许容器信号立即停止等待。"""

    def __init__(
        self,
        jobs: Sequence[ScheduledJob],
        *,
        schedule_revision: Callable[[], int] | None = None,
    ) -> None:
        """保存不可变任务列表，避免运行期动态扩展调度范围。"""
        self._jobs = tuple(jobs)
        self._schedule_revision = schedule_revision

    async def run(self, stop: asyncio.Event) -> None:
        """循环等待最近任务，到期执行后重新计算下一次时间。"""
        loop = asyncio.get_running_loop()
        deadlines = {
            job.name: loop.time() + job.next_delay(datetime.now(SHANGHAI)) for job in self._jobs
        }
        revision = self._schedule_revision() if self._schedule_revision is not None else None
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
                    deadlines[job.name] = loop.time() + job.next_delay(datetime.now(SHANGHAI))
                if self._schedule_revision is not None:
                    current_revision = self._schedule_revision()
                    if current_revision != revision:
                        revision = current_revision
                        now = loop.time()
                        for job in self._jobs:
                            if job.reschedule_on_revision:
                                deadlines[job.name] = now + job.next_delay(datetime.now(SHANGHAI))
                continue

            timeout = min(deadlines.values()) - now if deadlines else 3600.0
            try:
                await asyncio.wait_for(stop.wait(), timeout=max(0.1, timeout))
            except TimeoutError:
                continue


def _integer_value(value: int | Callable[[], int]) -> int:
    """解析静态整数或运行期整数提供者。"""
    return value() if callable(value) else value


def _interval_value(value: IntervalValue) -> int:
    """解析并保护运行期周期秒数，防止错误配置形成忙循环。"""
    return max(1, _integer_value(value))


def _time_value(value: TimeValue) -> time:
    """解析静态时间或运行期时间提供者。"""
    return value() if callable(value) else value


def is_time_in_window(current: time, *, start: time, end: time) -> bool:
    """判断当前时间是否落在普通或跨午夜窗口内。"""
    if start < end:
        return start <= current < end
    return current >= start or current < end
