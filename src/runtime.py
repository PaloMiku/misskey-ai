from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Callable, Optional

from loguru import logger

if TYPE_CHECKING:
    from .bot import MisskeyBot

__all__ = ("BotRuntime",)


class BotRuntime:
    def __init__(
        self,
        bot: MisskeyBot,
        loop: Optional[asyncio.AbstractEventLoop] = None,
    ):
        self.bot = bot
        self.loop = loop or asyncio.get_event_loop()
        self.startup_time = datetime.now(timezone.utc)
        self.running = False
        self.tasks: dict[str, asyncio.Task] = {}
        self.posts_today = 0
        self.last_auto_post_time = self.startup_time

    def add_task(self, name: str, coro: Callable) -> asyncio.Task:
        if name in self.tasks and not self.tasks[name].done():
            self.tasks[name].cancel()
        task = self.loop.create_task(coro)
        self.tasks[name] = task
        return task

    def cancel_task(self, name: str) -> bool:
        if name in self.tasks and not self.tasks[name].done():
            self.tasks[name].cancel()
            return True
        return False

    def cancel_all_tasks(self) -> None:
        for task in self.tasks.values():
            if not task.done():
                task.cancel()
        self.tasks.clear()

    async def cleanup_tasks(self) -> None:
        for task in self.tasks.values():
            if not task.done():
                task.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks.values(), return_exceptions=True)
        self.tasks.clear()

    def post_count(self) -> None:
        self.posts_today += 1
        self.last_auto_post_time = datetime.now(timezone.utc)

    def check_post_counter(self, max_posts: int) -> bool:
        if self.posts_today >= max_posts:
            logger.debug(f"今日发帖数量已达上限 ({max_posts})，跳过自动发帖")
            return False
        return True

    def reset_daily_counters(self) -> None:
        self.posts_today = 0
        logger.debug("发帖计数器已重置")
