#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import json
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional

from cachetools import LRUCache
from loguru import logger
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .config import Config
from .deepseek_api import DeepSeekAPI
from .misskey_api import MisskeyAPI
from .streaming import StreamingClient
from .persistence import PersistenceManager
from .plugin_manager import PluginManager
from .interfaces import ITextGenerator, IAPIClient, IStreamingClient
from .exceptions import (
    ConfigurationError,
    APIConnectionError,
    APIRateLimitError,
    AuthenticationError,
    WebSocketConnectionError,
)
from .constants import (
    MAX_CACHE,
    WS_MAX_RETRIES,
    ERROR_MESSAGES,
    DEFAULT_ERROR_MESSAGE,
    ConfigKeys,
)
from .utils import retry_async, extract_user_id, extract_username


class MisskeyBot:
    def __init__(
        self,
        config: Config,
        text_generator: Optional[ITextGenerator] = None,
        api_client: Optional[IAPIClient] = None,
        streaming_client: Optional[IStreamingClient] = None,
    ):
        if not isinstance(config, Config):
            raise ValueError("配置参数必须是 Config 类型")
        self.config = config
        self.startup_time = datetime.now(timezone.utc)
        logger.debug(f"机器人启动时间 (UTC): {self.startup_time.isoformat()}")
        try:
            instance_url = config.get(ConfigKeys.MISSKEY_INSTANCE_URL)
            access_token = config.get(ConfigKeys.MISSKEY_ACCESS_TOKEN)
            self.misskey = api_client or MisskeyAPI(instance_url, access_token)
            self.streaming = streaming_client or StreamingClient(
                instance_url, access_token
            )
            self.deepseek = text_generator or DeepSeekAPI(
                config.get(ConfigKeys.DEEPSEEK_API_KEY),
                config.get(ConfigKeys.DEEPSEEK_MODEL),
                config.get(ConfigKeys.DEEPSEEK_API_BASE),
            )
            self.scheduler = AsyncIOScheduler()
            self._cleanup_needed = True
            logger.debug("API 客户端和调度器初始化完成")
        except (ValueError, TypeError, KeyError) as e:
            logger.error(f"初始化失败: {e}")
            raise ConfigurationError(f"初始化失败: {e}")
        self.persistence = PersistenceManager(config.get(ConfigKeys.DB_PATH))
        self.plugin_manager = PluginManager(config, persistence=self.persistence)
        self.processed_mentions = LRUCache(maxsize=MAX_CACHE)
        self.processed_messages = LRUCache(maxsize=MAX_CACHE)
        now_utc = datetime.now(timezone.utc)
        self.last_auto_post_time = now_utc - timedelta(hours=24)
        self.posts_today = 0
        self.today = now_utc.date()
        self.system_prompt = config.get(ConfigKeys.BOT_SYSTEM_PROMPT, "")
        self.running = False
        self.tasks = []
        self.error_counts = {
            "api_errors": 0,
            "rate_limit_errors": 0,
            "auth_errors": 0,
            "connection_errors": 0,
        }
        logger.info("机器人初始化完成")

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()
        return False

    async def _load_recent_processed_items(self) -> None:
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

    async def _cleanup_old_processed_items(self) -> None:
        try:
            cleanup_days = self.config.get(ConfigKeys.DB_CLEANUP_DAYS)
            deleted_count = await self.persistence.cleanup_old_records(cleanup_days)
            if deleted_count > 0:
                logger.debug(f"已清理 {deleted_count} 条过期记录")
        except (ValueError, OSError) as e:
            logger.error(f"清理旧记录时出错: {e}")

    async def start(self) -> None:
        if self.running:
            logger.warning("机器人已在运行中")
            return
        logger.info("启动服务组件...")
        self.running = True
        await self._initialize_services()
        await self._setup_scheduler()
        await self._setup_streaming()
        logger.info("服务组件就绪，开始监听...")

    async def _initialize_services(self) -> None:
        await self.persistence.initialize()
        try:
            current_user = await self.misskey.get_current_user()
            self.bot_user_id = current_user.get("id")
            logger.info(f"已连接 Misskey 实例，用户 ID: {self.bot_user_id}")
        except (APIConnectionError, AuthenticationError, ValueError) as e:
            logger.error(f"连接 Misskey 实例失败: {e}")
            self.bot_user_id = None
        await self._load_recent_processed_items()
        await self.plugin_manager.load_plugins()
        await self.plugin_manager.on_startup()

    async def _setup_scheduler(self) -> None:
        cron_jobs = [
            (self._reset_daily_post_count, 0),
            (self._cleanup_old_processed_items, 1),
            (self.persistence.vacuum, 2),
        ]
        for func, hour in cron_jobs:
            self.scheduler.add_job(func, "cron", hour=hour, minute=0, second=0)
        if self.config.get(ConfigKeys.BOT_AUTO_POST_ENABLED):
            interval_minutes = self.config.get(ConfigKeys.BOT_AUTO_POST_INTERVAL)
            logger.info(f"自动发帖已启用，间隔: {interval_minutes} 分钟")
            self.scheduler.add_job(
                self._auto_post,
                "interval",
                minutes=interval_minutes,
                next_run_time=datetime.now(timezone.utc) + timedelta(minutes=1),
            )
        self.scheduler.start()

    async def _setup_streaming(self) -> None:
        self.streaming.on_mention(self._handle_mention)
        self.streaming.on_message(self._handle_message)
        try:
            await self._start_websocket()
            if self.streaming.is_connected:
                logger.info("WebSocket 连接成功，使用实时模式")
                task = asyncio.create_task(self._maintain_websocket())
            else:
                logger.warning("WebSocket 重试失败，启用轮询模式")
                task = asyncio.create_task(self._poll_mentions())
            self.tasks.append(task)
        except (WebSocketConnectionError, APIConnectionError, OSError) as e:
            logger.error(f"WebSocket 启动失败: {e}，启用轮询模式")
            task = asyncio.create_task(self._poll_mentions())
            self.tasks.append(task)

    async def stop(self) -> None:
        if not self.running:
            logger.warning("机器人已停止")
            return
        logger.info("停止服务组件...")
        self.running = False
        try:
            await self.plugin_manager.on_shutdown()
            await self.plugin_manager.cleanup_plugins()
            self.scheduler.shutdown(wait=False)
            for task in self.tasks:
                if not task.done():
                    task.cancel()
            if self.tasks:
                await asyncio.gather(*self.tasks, return_exceptions=True)
            self.tasks = []
            await self.streaming.close()
            await self.misskey.close()
            await self.deepseek.close()
            await self.persistence.close()
            self.processed_mentions.clear()
            self.processed_messages.clear()
        except (OSError, ValueError, TypeError) as e:
            logger.error(f"停止机器人时出错: {e}")
        finally:
            self._cleanup_needed = False
            logger.info("服务组件已停止")

    def _reset_daily_post_count(self) -> None:
        self.posts_today = 0
        self.today = datetime.now(timezone.utc).date()
        logger.debug("已重置每日发帖计数")

    async def _start_websocket(self) -> None:
        @retry_async(
            max_retries=WS_MAX_RETRIES,
        )
        async def websocket_connect():
            await self.streaming.connect()

        await websocket_connect()

    async def _maintain_websocket(self) -> None:
        try:
            while self.running and self.streaming.is_connected:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            logger.debug("WebSocket 维护任务被取消")
        except (WebSocketConnectionError, APIConnectionError, OSError) as e:
            logger.error(f"WebSocket 维护任务出错: {e}")
            if self.running:
                await self._cleanup_websocket_resources()
                try:
                    await self._start_websocket()
                    if self.streaming.is_connected:
                        logger.info("WebSocket 重新连接成功")
                        await self._maintain_websocket()
                    else:
                        self._switch_to_polling("WebSocket 重试失败")
                except (
                    WebSocketConnectionError,
                    APIConnectionError,
                    OSError,
                ) as reconnect_error:
                    self._switch_to_polling(f"WebSocket 重试失败: {reconnect_error}")

    def _switch_to_polling(self, reason: str) -> None:
        logger.warning(f"{reason}，切换到轮询模式")
        task = asyncio.create_task(self._poll_mentions())
        self.tasks.append(task)

    async def _cleanup_websocket_resources(self) -> None:
        try:
            await self.streaming.disconnect()
            self.streaming.processed_events.clear()
            logger.debug("WebSocket 资源清理完成")
        except (OSError, ValueError) as e:
            logger.error(f"清理 WebSocket 资源时出错: {e}")

    async def _poll_mentions(self) -> None:
        base_delay = self.config.get(ConfigKeys.BOT_RESPONSE_POLLING_INTERVAL)

        async def poll_once():
            if self.config.get(ConfigKeys.BOT_RESPONSE_MENTION_ENABLED):
                mentions = await self.misskey.get_mentions(limit=100)
                if mentions:
                    logger.debug(f"轮询获取到 {len(mentions)} 个提及")
                await self._process_polled_items(
                    mentions, "mention", self._handle_mention
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
            messages = await self.misskey.get_all_chat_messages(limit=100)
            if messages:
                logger.debug(f"轮询获取到 {len(messages)} 条聊天")
            await self._process_polled_items(messages, "message", self._handle_message)
        except (APIConnectionError, APIRateLimitError, ValueError, OSError) as e:
            logger.error(f"轮询聊天时出错: {e}")
            logger.debug(f"轮询聊天详细错误: {e}", exc_info=True)

    async def _process_polled_items(self, items, item_type: str, handler) -> None:
        cache = (
            self.processed_mentions
            if item_type == "mention"
            else self.processed_messages
        )
        persistence_check = (
            self.persistence.is_mention_processed
            if item_type == "mention"
            else self.persistence.is_message_processed
        )
        for item in items:
            item_id = item.get("id")
            if item_id and item_id not in cache:
                if not await persistence_check(item_id):
                    if self._is_message_after_startup(item):
                        await handler(item)
                    else:
                        user_id = extract_user_id(item)
                        username = extract_username(item)
                        await self._mark_processed(
                            item_id, user_id, username, item_type
                        )
                else:
                    logger.debug(f"{item_type}已在数据库中标记为已处理: {item_id}")
            else:
                logger.debug(f"{item_type}已在缓存中: {item_id}")

    async def _handle_mention(self, note: Dict[str, Any]) -> None:
        if not self.config.get(ConfigKeys.BOT_RESPONSE_MENTION_ENABLED):
            return
        mention_data = self._parse_mention_data(note)
        if not mention_data["mention_id"]:
            return
        try:
            await self._process_mention(mention_data, note)
        except (
            ValueError,
            APIConnectionError,
            APIRateLimitError,
            AuthenticationError,
            OSError,
        ) as e:
            await self._handle_mention_error(e, mention_data)

    def _parse_mention_data(self, note: Dict[str, Any]) -> Dict[str, Any]:
        is_reply_event = note.get("type") == "reply" and "note" in note
        logger.debug(f"提及数据: {json.dumps(note, ensure_ascii=False, indent=2)}")
        mention_id = note.get("id")
        reply_target_id = note.get("note", {}).get("id")
        if is_reply_event:
            note_data = note["note"]
            text = note_data.get("text", "")
            user_id = note_data.get("userId")
            username = note_data.get("user", {}).get("username")
            reply_info = note_data.get("reply", {})
            if reply_info and reply_info.get("text"):
                text = f"{reply_info.get('text')}\n\n{text}"
        else:
            text = note.get("note", {}).get("text", "")
            user_id = extract_user_id(note)
            username = extract_username(note)
        return {
            "mention_id": mention_id,
            "reply_target_id": reply_target_id,
            "text": text,
            "user_id": user_id,
            "username": username,
        }

    async def _process_mention(
        self, mention_data: Dict[str, Any], note: Dict[str, Any]
    ) -> None:
        await self._mark_processed(
            mention_data["mention_id"],
            mention_data["user_id"],
            mention_data["username"],
            "mention",
        )
        logger.info(
            f"收到 @{mention_data['username']} 的提及: {self._format_log_text(mention_data['text'])}"
        )
        if await self._try_plugin_mention_response(mention_data, note):
            return
        await self._generate_ai_mention_response(mention_data)

    async def _try_plugin_mention_response(
        self, mention_data: Dict[str, Any], note: Dict[str, Any]
    ) -> bool:
        plugin_results = await self.plugin_manager.on_mention(note)
        for result in plugin_results:
            if result and result.get("handled"):
                logger.debug(f"提及已被插件处理: {result.get('plugin_name')}")
                response = result.get("response")
                if response:
                    formatted_response = f"@{mention_data['username']}\n{response}"
                    await self.misskey.create_note(
                        formatted_response, reply_id=mention_data["reply_target_id"]
                    )
                    logger.info(
                        f"插件已回复 @{mention_data['username']}: {self._format_log_text(formatted_response)}"
                    )
                return True
        return False

    async def _generate_ai_mention_response(self, mention_data: Dict[str, Any]) -> None:
        try:
            reply = await self.deepseek.generate_reply(
                mention_data["text"], self.system_prompt, **self._ai_config
            )
            logger.debug("生成提及回复成功")
            formatted_reply = f"@{mention_data['username']}\n{reply}"
            await self.misskey.create_note(
                formatted_reply, reply_id=mention_data["reply_target_id"]
            )
            logger.info(
                f"已回复 @{mention_data['username']}: {self._format_log_text(formatted_reply)}"
            )
        except (APIRateLimitError, APIConnectionError, AuthenticationError) as e:
            error_message = self._handle_error(e, "生成或发送回复时")
            await self._send_error_reply(
                mention_data["username"],
                mention_data["reply_target_id"],
                error_message
                if "生成" in str(e)
                else "抱歉，回复发送失败，请稍后再试。",
            )

    async def _handle_mention_error(
        self, e: Exception, mention_data: Dict[str, Any]
    ) -> None:
        if isinstance(e, ValueError):
            logger.error(f"输入验证错误: {e}")
        else:
            logger.error(f"处理提及时出错: {e}")
        self._handle_error(e, "处理提及时")
        try:
            if mention_data["username"] and mention_data["reply_target_id"]:
                await self._send_error_reply(
                    mention_data["username"],
                    mention_data["reply_target_id"],
                    "抱歉，处理您的提及时出现了错误。",
                )
        except (APIConnectionError, APIRateLimitError, OSError) as reply_error:
            logger.error(f"发送错误回复失败: {reply_error}")

    async def _handle_message(self, message: Dict[str, Any]) -> None:
        if not self.config.get(ConfigKeys.BOT_RESPONSE_CHAT_ENABLED):
            return
        message_id = message.get("id")
        if not message_id:
            logger.debug("缺少 ID，跳过处理")
            return
        logger.debug(f"聊天数据: {json.dumps(message, ensure_ascii=False, indent=2)}")
        if (
            message_id in self.processed_messages
            or await self.persistence.is_message_processed(message_id)
        ):
            logger.debug(f"已处理: {message_id}")
            return
        try:
            await self._process_chat_message(message, message_id)
        except (
            APIConnectionError,
            APIRateLimitError,
            AuthenticationError,
            ValueError,
            OSError,
        ) as e:
            logger.error(f"处理聊天时出错: {e}")
            logger.debug(f"处理聊天详细错误: {e}", exc_info=True)

    async def _process_chat_message(
        self, message: Dict[str, Any], message_id: str
    ) -> None:
        text = message.get("text") or message.get("content") or message.get("body", "")
        user_id = extract_user_id(message)
        username = extract_username(message)
        logger.debug(
            f"解析聊天 - ID: {message_id}, 用户 ID: {user_id}, 文本: {self._format_log_text(text)}..."
        )
        if self.bot_user_id and user_id == self.bot_user_id:
            logger.debug(f"跳过自己发送的聊天: {message_id}")
            await self._mark_processed(message_id, user_id, username, "message")
            return
        await self._mark_processed(message_id, user_id, username, "message")
        if not (user_id and text):
            logger.debug(f"聊天缺少必要信息 - 用户 ID: {user_id}, 文本: {bool(text)}")
            return
        logger.info(f"收到 @{username} 的聊天: {self._format_log_text(text)}")
        if await self._try_plugin_message_response(message, user_id, username):
            return
        await self._generate_ai_chat_response(user_id, username, text)

    async def _try_plugin_message_response(
        self, message: Dict[str, Any], user_id: str, username: str
    ) -> bool:
        plugin_results = await self.plugin_manager.on_message(message)
        for result in plugin_results:
            if result and result.get("handled"):
                logger.debug(f"聊天已被插件处理: {result.get('plugin_name')}")
                response = result.get("response")
                if response:
                    await self.misskey.send_message(user_id, response)
                    logger.info(
                        f"插件已回复 @{username}: {self._format_log_text(response)}"
                    )
                return True
        return False

    async def _generate_ai_chat_response(
        self, user_id: str, username: str, text: str
    ) -> None:
        chat_history = await self._get_chat_history(user_id)
        chat_history.append({"role": "user", "content": text})
        if not chat_history or chat_history[0].get("role") != "system":
            chat_history.insert(0, {"role": "system", "content": self.system_prompt})
        reply = await self.deepseek.generate_chat_response(
            chat_history, **self._ai_config
        )
        logger.debug("生成聊天回复成功")
        await self.misskey.send_message(user_id, reply)
        logger.info(f"已回复 @{username}: {self._format_log_text(reply)}")
        chat_history.append({"role": "assistant", "content": reply})

    async def _send_error_reply(
        self, username: str, note_id: str, message: str
    ) -> None:
        try:
            await self.misskey.create_note(
                text=f"@{username}\n{message}", reply_id=note_id
            )
        except (APIConnectionError, APIRateLimitError, OSError) as e:
            logger.error(f"发送错误回复失败: {e}")

    async def _get_chat_history(
        self, user_id: str, limit: int = None
    ) -> List[Dict[str, str]]:
        try:
            if limit is None:
                limit = self.config.get(ConfigKeys.BOT_RESPONSE_CHAT_MEMORY)
            messages = await self.misskey.get_messages(user_id, limit=limit)
            chat_history = []
            for msg in reversed(messages):
                if msg.get("userId") == user_id:
                    chat_history.append(
                        {"role": "user", "content": msg.get("text", "")}
                    )
                else:
                    chat_history.append(
                        {"role": "assistant", "content": msg.get("text", "")}
                    )
            return chat_history
        except (APIConnectionError, APIRateLimitError, ValueError, OSError) as e:
            logger.error(f"获取聊天历史时出错: {e}")
            return []

    async def _auto_post(self) -> None:
        if not self.running or not self._check_auto_post_limits():
            return
        try:
            max_posts = self.config.get(ConfigKeys.BOT_AUTO_POST_MAX_PER_DAY)

            def log_post_success(post_content: str) -> None:
                logger.info(f"自动发帖成功: {self._format_log_text(post_content)}")
                logger.info(f"今日发帖计数: {self.posts_today}/{max_posts}")

            plugin_results = await self.plugin_manager.on_auto_post()
            if not await self._try_plugin_auto_post_with_results(
                plugin_results, log_post_success
            ):
                await self._generate_ai_auto_post_with_results(
                    plugin_results, log_post_success
                )
        except (
            APIConnectionError,
            APIRateLimitError,
            AuthenticationError,
            ValueError,
            OSError,
        ) as e:
            logger.error(f"自动发帖时出错: {e}")

    def _check_auto_post_limits(self) -> bool:
        current_date = datetime.now(timezone.utc).date()
        if current_date != self.today:
            self._reset_daily_post_count()
        max_posts = self.config.get(ConfigKeys.BOT_AUTO_POST_MAX_PER_DAY)
        if self.posts_today >= max_posts:
            logger.debug(f"今日发帖数量已达上限 ({max_posts})，跳过自动发帖")
            return False
        return True

    async def _try_plugin_auto_post_with_results(
        self, plugin_results, log_post_success
    ) -> bool:
        for result in plugin_results:
            if result and result.get("content"):
                post_content = result.get("content")
                visibility = result.get(
                    "visibility", self.config.get(ConfigKeys.BOT_AUTO_POST_VISIBILITY)
                )
                await self.misskey.create_note(post_content, visibility=visibility)
                self.posts_today += 1
                self.last_auto_post_time = datetime.now(timezone.utc)
                log_post_success(post_content)
                return True
        return False

    async def _generate_ai_auto_post_with_results(
        self, plugin_results, log_post_success
    ) -> None:
        plugin_prompt = ""
        timestamp_override = None
        for result in plugin_results:
            if result and result.get("modify_prompt"):
                if result.get("plugin_prompt"):
                    plugin_prompt = result.get("plugin_prompt")
                if result.get("timestamp"):
                    timestamp_override = result.get("timestamp")
                logger.info(
                    f"{result.get('plugin_name')} 插件请求修改提示词: {plugin_prompt}"
                )
        post_prompt = self.config.get(
            ConfigKeys.BOT_AUTO_POST_PROMPT, "生成一篇有趣、有见解的社交媒体帖子。"
        )
        try:
            post_content = await self._generate_post_with_plugin(
                self.system_prompt,
                post_prompt,
                plugin_prompt,
                timestamp_override,
                **self._ai_config,
            )
        except ValueError as e:
            logger.warning(f"自动发帖失败: {e}，跳过本次发帖")
            return
        visibility = self.config.get(ConfigKeys.BOT_AUTO_POST_VISIBILITY)
        await self.misskey.create_note(post_content, visibility=visibility)
        self.posts_today += 1
        self.last_auto_post_time = datetime.now(timezone.utc)
        log_post_success(post_content)

    async def _generate_post_with_plugin(
        self,
        system_prompt: str,
        prompt: str,
        plugin_prompt: str,
        timestamp_override: Optional[int] = None,
        **ai_config,
    ) -> str:
        if not prompt:
            raise ValueError("缺少提示词")
        timestamp_min = (
            timestamp_override
            if timestamp_override is not None
            else int(time.time() // 60)
        )
        full_prompt = f"[{timestamp_min}] {plugin_prompt}{prompt}"
        return await self.deepseek.generate_text(
            full_prompt, system_prompt, **(ai_config or self._ai_config)
        )

    def _handle_error(self, error: Exception, context: str = "") -> str:
        error_type = type(error).__name__
        self.error_counts[error_type] = self.error_counts.get(error_type, 0) + 1
        logger.error(f"错误类型: {error_type}, 上下文: {context}, 详情: {str(error)}")
        return ERROR_MESSAGES.get(type(error).__name__, DEFAULT_ERROR_MESSAGE)

    def get_error_stats(self) -> Dict[str, int]:
        return self.error_counts.copy()

    def _format_log_text(self, text: str, max_length: int = 50) -> str:
        if not text:
            return "None"
        return f"{text[:max_length]}{'...' if len(text) > max_length else ''}"

    @property
    def _ai_config(self) -> Dict[str, Any]:
        return {
            "max_tokens": self.config.get(ConfigKeys.DEEPSEEK_MAX_TOKENS),
            "temperature": self.config.get(ConfigKeys.DEEPSEEK_TEMPERATURE),
        }

    async def _mark_processed(
        self, item_id: str, user_id: str, username: str, item_type: str
    ) -> None:
        if item_type == "mention":
            await self.persistence.mark_mention_processed(item_id, user_id, username)
            self.processed_mentions[item_id] = True
        elif item_type == "message":
            await self.persistence.mark_message_processed(item_id, user_id, "private")
            self.processed_messages[item_id] = True

    def _is_message_after_startup(self, message: Dict[str, Any]) -> bool:
        try:
            created_at = (
                message.get("createdAt")
                or message.get("created_at")
                or message.get("timestamp")
            )
            if not created_at:
                logger.debug(f"缺少时间戳信息: {message.get('id', 'unknown')}")
                return False
            message_time = self._parse_message_timestamp(created_at)
            if message_time is None:
                return False
            return self._compare_message_time(message_time)
        except (ValueError, TypeError, AttributeError) as e:
            logger.debug(f"检查时间时出错: {e}")
            return False

    def _parse_message_timestamp(self, created_at) -> Optional[datetime]:
        if isinstance(created_at, str):
            try:
                message_time = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                return (
                    message_time
                    if message_time.tzinfo
                    else message_time.replace(tzinfo=timezone.utc)
                )
            except ValueError:
                logger.debug(f"无法解析时间戳格式: {created_at}")
                return None
        elif isinstance(created_at, (int, float)):
            return datetime.fromtimestamp(
                created_at / 1000 if created_at > 1e10 else created_at, tz=timezone.utc
            )
        else:
            logger.debug(f"未知的时间戳类型: {type(created_at)}")
            return None

    def _compare_message_time(self, message_time: datetime) -> bool:
        startup_time = self.startup_time
        if startup_time.tzinfo is None:
            startup_time = startup_time.replace(tzinfo=timezone.utc)
        is_after = message_time > startup_time
        logger.debug(
            f"时间检查 - 消息时间: {message_time.isoformat()}, 启动时间: {self.startup_time.isoformat()}, 结果: {is_after}"
        )
        return is_after
