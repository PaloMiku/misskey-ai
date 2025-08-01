#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional

from loguru import logger
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .config import Config
from .deepseek_api import DeepSeekAPI
from .misskey_api import MisskeyAPI
from .streaming import StreamingClient
from .persistence import PersistenceManager
from .plugin_manager import PluginManager
from .state import BotState
from .interfaces import ITextGenerator, IAPIClient, IStreamingClient
from .http_client import HTTPSession
from .exceptions import (
    ConfigurationError,
    APIConnectionError,
    APIRateLimitError,
    AuthenticationError,
)
from .constants import (
    ERROR_MESSAGES,
    DEFAULT_ERROR_MESSAGE,
    ConfigKeys,
)
from .utils import extract_user_id, extract_username, get_memory_usage

__all__ = ("MisskeyBot",)


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
        except (ValueError, TypeError, KeyError) as e:
            logger.error(f"初始化失败: {e}")
            raise ConfigurationError() from e
        self.persistence = PersistenceManager(config.get(ConfigKeys.DB_PATH))
        self.plugin_manager = PluginManager(config, persistence=self.persistence)
        self.state = BotState(self)
        self.system_prompt = config.get(ConfigKeys.BOT_SYSTEM_PROMPT, "")
        logger.info("机器人初始化完成")

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()
        return False

    async def start(self) -> None:
        if self.state.running:
            logger.warning("机器人已在运行中")
            return
        logger.info("启动服务组件...")
        self.state.running = True
        await self._initialize_services()
        await self._setup_scheduler()
        await self._setup_streaming()
        logger.info("服务组件就绪，等待新任务...")
        memory_usage = get_memory_usage()
        logger.debug(f"内存使用: {memory_usage['rss_mb']} MB")

    async def _initialize_services(self) -> None:
        await self.persistence.initialize()
        await self.deepseek.initialize()
        try:
            current_user = await self.misskey.get_current_user()
            self.bot_user_id = current_user.get("id")
            logger.info(f"已连接 Misskey 实例，用户 ID: {self.bot_user_id}")
        except (APIConnectionError, AuthenticationError, ValueError) as e:
            logger.error(f"连接 Misskey 实例失败: {e}")
            self.bot_user_id = None
        await self.plugin_manager.load_plugins()
        await self.plugin_manager.on_startup()

    async def _setup_scheduler(self) -> None:
        cron_jobs = [
            (self.state.reset_daily_counters, 0),
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
        try:
            instance_url = self.config.get(ConfigKeys.MISSKEY_INSTANCE_URL)
            access_token = self.config.get(ConfigKeys.MISSKEY_ACCESS_TOKEN)
            self.streaming = StreamingClient(instance_url, access_token)
            self.streaming.on_mention(self._handle_mention)
            self.streaming.on_message(self._handle_message)
            self.state.add_task("streaming", self.streaming.connect())
            await self.streaming.wait_for_connection()
        except (ValueError, OSError) as e:
            logger.error(f"设置 Streaming 连接失败: {e}")
            raise

    async def stop(self) -> None:
        if not self.state.running:
            logger.warning("机器人已停止")
            return
        logger.info("停止服务组件...")
        self.state.running = False
        try:
            await self.plugin_manager.on_shutdown()
            await self.plugin_manager.cleanup_plugins()
            self.scheduler.shutdown(wait=False)
            await self.state.cleanup_tasks()
            await self.streaming.close()
            await self.misskey.close()
            await self.deepseek.close()
            await HTTPSession.close_session()
            await self.persistence.close()
        except (OSError, ValueError) as e:
            logger.error(f"停止机器人时出错: {e}")
        finally:
            logger.info("服务组件已停止")

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
        ):
            await self._handle_mention_error(mention_data)

    def _parse_mention_data(self, note: Dict[str, Any]) -> Dict[str, Any]:
        try:
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
        except ValueError as e:
            logger.error(f"解析消息数据失败: {e}")
            return {
                "mention_id": None,
                "reply_target_id": None,
                "text": "",
                "user_id": None,
                "username": None,
            }

    async def _process_mention(
        self, mention_data: Dict[str, Any], note: Dict[str, Any]
    ) -> None:
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
            logger.error(f"生成或发送回复时出错: {e}")
            error_message = self._handle_error(e, "生成提及回复")
            await self._send_error_reply(
                mention_data["username"],
                mention_data["reply_target_id"],
                error_message,
            )

    async def _handle_mention_error(self, mention_data: Dict[str, Any]) -> None:
        logger.error("处理提及时出错")
        try:
            if mention_data["username"] and mention_data["reply_target_id"]:
                await self._send_error_reply(
                    mention_data["username"],
                    mention_data["reply_target_id"],
                    DEFAULT_ERROR_MESSAGE,
                )
        except (APIConnectionError, APIRateLimitError, OSError) as e:
            logger.error(f"发送错误回复失败: {e}")

    async def _handle_message(self, message: Dict[str, Any]) -> None:
        if not self.config.get(ConfigKeys.BOT_RESPONSE_CHAT_ENABLED):
            return
        message_id = message.get("id")
        if not message_id:
            logger.debug("缺少 ID，跳过处理")
            return
        logger.debug(f"聊天数据: {json.dumps(message, ensure_ascii=False, indent=2)}")
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

    async def _process_chat_message(
        self, message: Dict[str, Any], message_id: str
    ) -> None:
        text = message.get("text") or message.get("content") or message.get("body", "")
        user_id = extract_user_id(message)
        username = extract_username(message)
        logger.debug(
            f"解析聊天 - ID: {message_id}, 用户 ID: {user_id}, 文本: {self._format_log_text(text)}..."
        )
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
            limit = limit or self.config.get(ConfigKeys.BOT_RESPONSE_CHAT_MEMORY)
            messages = await self.misskey.get_messages(user_id, limit=limit)
            return [
                {
                    "role": "user" if msg.get("userId") == user_id else "assistant",
                    "content": msg.get("text", ""),
                }
                for msg in reversed(messages)
            ]
        except (APIConnectionError, APIRateLimitError, ValueError, OSError) as e:
            logger.error(f"获取聊天历史时出错: {e}")
            return []

    async def _auto_post(self) -> None:
        if not self.state.running or not self._check_auto_post_limits():
            return
        try:
            max_posts = self.config.get(ConfigKeys.BOT_AUTO_POST_MAX_PER_DAY)

            def log_post_success(post_content: str) -> None:
                logger.info(f"自动发帖成功: {self._format_log_text(post_content)}")
                logger.info(f"今日发帖计数: {self.state.posts_today}/{max_posts}")

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
        max_posts = self.config.get(ConfigKeys.BOT_AUTO_POST_MAX_PER_DAY)
        if self.state.posts_today >= max_posts:
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
                self.state.posts_today += 1
                self.state.last_auto_post_time = datetime.now(timezone.utc)
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
            logger.warning(f"自动发帖失败，跳过本次发帖: {e}")
            return
        visibility = self.config.get(ConfigKeys.BOT_AUTO_POST_VISIBILITY)
        await self.misskey.create_note(post_content, visibility=visibility)
        self.state.posts_today += 1
        self.state.last_auto_post_time = datetime.now(timezone.utc)
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
        timestamp_min = timestamp_override or int(
            datetime.now(timezone.utc).timestamp() // 60
        )
        full_prompt = f"[{timestamp_min}] {plugin_prompt}{prompt}"
        return await self.deepseek.generate_text(
            full_prompt, system_prompt, **(ai_config or self._ai_config)
        )

    def _handle_error(self, error: Exception, context: str = "") -> str:
        error_type = type(error).__name__
        logger.error(f"错误类型: {error_type}, 上下文: {context}, 详情: {str(error)}")
        return ERROR_MESSAGES.get(error_type, DEFAULT_ERROR_MESSAGE)

    def _format_log_text(self, text: str, max_length: int = 50) -> str:
        return (
            "None"
            if not text
            else f"{text[:max_length]}{'...' if len(text) > max_length else ''}"
        )

    @property
    def _ai_config(self) -> Dict[str, Any]:
        return {
            "max_tokens": self.config.get(ConfigKeys.DEEPSEEK_MAX_TOKENS),
            "temperature": self.config.get(ConfigKeys.DEEPSEEK_TEMPERATURE),
        }
