from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Callable, Dict, Optional
from datetime import datetime, timezone

from loguru import logger

if TYPE_CHECKING:
    from .bot import MisskeyBot

__all__ = ("BotState",)


class BotState:
    def __init__(
        self,
        bot: MisskeyBot,
        loop: Optional[asyncio.AbstractEventLoop] = None,
    ):
        self.bot = bot
        self.loop = loop or asyncio.get_event_loop()
        self.startup_time = datetime.now(timezone.utc)
        self.running = False
        self.tasks: Dict[str, asyncio.Task] = {}
        self.posts_today = 0
        self.last_auto_post_time = self.startup_time

    def add_task(self, name: str, coro: Callable) -> asyncio.Task:
        if name in self.tasks and not self.tasks[name].done():
            self.tasks[name].cancel()
        task = self.loop.create_task(coro)
        self.tasks[name] = task
        return task

    # RESERVED
    def cancel_task(self, name: str) -> bool:
        if name in self.tasks and not self.tasks[name].done():
            self.tasks[name].cancel()
            return True
        return False

    # RESERVED
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

    def reset_daily_counters(self) -> None:
        self.posts_today = 0
        logger.debug("发帖计数器已重置")
