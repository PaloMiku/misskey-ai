#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import signal
import sys
from pathlib import Path
from typing import Optional, List

from loguru import logger
from dotenv import load_dotenv

from .config import Config
from .bot import MisskeyBot
from .exceptions import ConfigurationError, APIConnectionError, AuthenticationError
from .constants import ConfigKeys

bot: Optional[MisskeyBot] = None
tasks: List[asyncio.Task] = []
shutdown_event: Optional[asyncio.Event] = None


async def main() -> None:
    global bot, tasks, shutdown_event
    shutdown_event = asyncio.Event()
    load_dotenv()
    config = Config()
    await config.load()
    log_path = Path(config.get(ConfigKeys.LOG_PATH))
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger.add(log_path, level=config.get(ConfigKeys.LOG_LEVEL))
    logger.info("启动机器人...")
    try:
        bot = MisskeyBot(config)
        await bot.start()
        await _setup_monitoring_and_signals()
        await shutdown_event.wait()
    except asyncio.CancelledError:
        pass
    except (
        ConfigurationError,
        APIConnectionError,
        AuthenticationError,
        OSError,
        ValueError,
    ) as e:
        logger.error(f"启动过程中发生错误: {e}")
        raise
    finally:
        await shutdown()
        logger.info("再见~")


async def _setup_monitoring_and_signals() -> None:
    global tasks
    signals = (
        (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
        if sys.platform != "win32"
        else (signal.SIGINT, signal.SIGTERM)
    )

    def signal_handler(sig, _):
        global shutdown_event
        logger.info(f"收到信号 {signal.Signals(sig).name}，准备关闭...")
        if shutdown_event and not shutdown_event.is_set():
            shutdown_event.set()

    for sig in signals:
        try:
            signal.signal(sig, signal_handler)
        except (OSError, ValueError, NotImplementedError):
            logger.warning(f"无法注册信号处理器: {sig}")


async def shutdown() -> None:
    global bot, tasks
    if hasattr(shutdown, "_called"):
        return
    shutdown._called = True
    logger.info("关闭机器人...")
    for task in tasks:
        if not task.done():
            task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    tasks.clear()
    if bot:
        await bot.stop()
    logger.info("机器人已关闭")


if __name__ == "__main__":
    asyncio.run(main())
