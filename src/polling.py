#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
from datetime import datetime
from typing import Dict, Any, Optional, Callable

from cachetools import LRUCache
from loguru import logger

from .config import Config
from .persistence import PersistenceManager
from .interfaces import IAPIClient
from .exceptions import (
    APIConnectionError,
    APIRateLimitError,
)
from .constants import MAX_CACHE, ConfigKeys
from .utils import extract_user_id, extract_username


class PollingManager:
    def __init__(
        self,
        config: Config,
        api_client: IAPIClient,
        persistence: PersistenceManager,
        startup_time: datetime,
    ):
        self.config = config
        self.api_client = api_client
        self.persistence = persistence
        self.startup_time = startup_time
        self.processed_mentions = LRUCache(maxsize=MAX_CACHE)
        self.processed_messages = LRUCache(maxsize=MAX_CACHE)
        self.running = False
        self.mention_handler: Optional[Callable] = None
        self.message_handler: Optional[Callable] = None

    def set_handlers(self, mention_handler: Callable, message_handler: Callable):
        self.mention_handler = mention_handler
        self.message_handler = message_handler

    async def load_recent_processed_items(self) -> None:
        try:
            recent_mentions = await self.persistence.get_recent_mentions(MAX_CACHE)
            recent_messages = await self.persistence.get_recent_messages(MAX_CACHE)
            self.processed_mentions.update(
                {m["note_id"]: True for m in recent_mentions}
            )
            self.processed_messages.update(
                {m["message_id"]: True for m in recent_messages}
            )
            logger.debug(
                f"已加载 {len(recent_mentions)} 个提及和 {len(recent_messages)} 个聊天到缓存"
            )
        except (ValueError, TypeError, KeyError, OSError) as e:
            logger.warning(f"加载已处理 ID 到缓存时出错: {e}，将从空状态开始")

    async def cleanup_old_processed_items(self) -> None:
        try:
            cleanup_days = self.config.get(ConfigKeys.DB_CLEANUP_DAYS)
            deleted_count = await self.persistence.cleanup_old_records(cleanup_days)
            if deleted_count > 0:
                logger.debug(f"已清理 {deleted_count} 条过期记录")
        except (ValueError, OSError) as e:
            logger.error(f"清理旧记录时出错: {e}")

    async def start_polling(self) -> None:
        if self.running:
            logger.warning("轮询已在运行中")
            return
        self.running = True
        logger.info("启动轮询模式")
        await self._poll_mentions()

    def stop_polling(self) -> None:
        self.running = False
        logger.info("停止轮询模式")

    def clear_caches(self) -> None:
        self.processed_mentions.clear()
        self.processed_messages.clear()

    async def _poll_mentions(self) -> None:
        base_delay = self.config.get(ConfigKeys.BOT_RESPONSE_POLLING_INTERVAL)

        async def poll_once():
            if self.config.get(ConfigKeys.BOT_RESPONSE_MENTION_ENABLED):
                mentions = await self.api_client.get_mentions(limit=100)
                if mentions:
                    logger.debug(f"轮询获取到 {len(mentions)} 个提及")
                await self._process_polled_items(
                    mentions, "mention", self.mention_handler
                )
            if self.config.get(ConfigKeys.BOT_RESPONSE_CHAT_ENABLED):
                await self._poll_chat_messages()
            await asyncio.sleep(base_delay)

        while self.running:
            try:
                await poll_once()
            except asyncio.CancelledError:
                break
            except (APIConnectionError, APIRateLimitError, ValueError, OSError) as e:
                if not self.running:
                    break
                logger.error(f"轮询错误: {e}")
                await asyncio.sleep(base_delay)

    async def _poll_chat_messages(self) -> None:
        try:
            messages = await self.api_client.get_all_chat_messages(limit=100)
            if messages:
                logger.debug(f"轮询获取到 {len(messages)} 条聊天")
            await self._process_polled_items(messages, "message", self.message_handler)
        except (APIConnectionError, APIRateLimitError, ValueError, OSError) as e:
            logger.error(f"轮询聊天时出错: {e}")
            logger.debug(f"轮询聊天详细错误: {e}", exc_info=True)

    async def _process_polled_items(self, items, item_type: str, handler) -> None:
        if not handler:
            logger.warning(f"未设置 {item_type} 处理器")
            return

        type_config = {
            "mention": (self.processed_mentions, self.persistence.is_mention_processed),
            "message": (self.processed_messages, self.persistence.is_message_processed),
        }
        cache, persistence_check = type_config[item_type]
        for item in items:
            item_id = item.get("id")
            if item_id and item_id not in cache:
                if not await persistence_check(item_id):
                    if self._is_message_after_startup(item):
                        await handler(item)
                    else:
                        user_id = extract_user_id(item)
                        username = extract_username(item)
                        await self.mark_processed(item_id, user_id, username, item_type)
                else:
                    logger.debug(f"{item_type}已在数据库中标记为已处理: {item_id}")
            else:
                logger.debug(f"{item_type}已在缓存中: {item_id}")

    async def mark_processed(
        self, item_id: str, user_id: str, username: str, item_type: str
    ) -> None:
        handlers = {
            "mention": (
                self.persistence.mark_mention_processed,
                self.processed_mentions,
                username,
            ),
            "message": (
                self.persistence.mark_message_processed,
                self.processed_messages,
                "private",
            ),
        }
        mark_func, cache, param = handlers[item_type]
        await mark_func(item_id, user_id, param)
        cache[item_id] = True

    def _is_message_after_startup(self, message: Dict[str, Any]) -> bool:
        try:
            created_at = message.get("createdAt")
            if not created_at or not isinstance(created_at, str):
                logger.warning(f"时间戳无效: {message.get('id', 'unknown')}")
                return False
            message_time = datetime.fromisoformat(created_at)
            is_after = message_time > self.startup_time
            logger.debug(
                f"时间检查 - 消息: {message_time.isoformat()}, 启动: {self.startup_time.isoformat()}, 结果: {is_after}"
            )
            return is_after
        except (ValueError, TypeError, AttributeError) as e:
            logger.warning(f"检查时间时出错: {e}")
            return False

    def is_mention_processed(self, mention_id: str) -> bool:
        return mention_id in self.processed_mentions

    def is_message_processed(self, message_id: str) -> bool:
        return message_id in self.processed_messages
