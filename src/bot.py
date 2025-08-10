#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger

from .config import Config
from .constants import (
    DEFAULT_ERROR_MESSAGE,
    ERROR_MESSAGES,
    ConfigKeys,
)
from .exceptions import (
    APIConnectionError,
    APIRateLimitError,
    AuthenticationError,
    ConfigurationError,
)
from .misskey_api import MisskeyAPI
from .openai_api import OpenAIAPI
from .persistence import PersistenceManager
from .plugin_manager import PluginManager
from .runtime import BotRuntime
from .streaming import StreamingClient
from .transport import ClientSession
from .utils import extract_user_id, extract_username, get_memory_usage

__all__ = ("MisskeyBot",)


class MisskeyBot:
    def __init__(self, config: Config):
        self.config = config
        try:
            instance_url = config.get(ConfigKeys.MISSKEY_INSTANCE_URL)
            access_token = config.get(ConfigKeys.MISSKEY_ACCESS_TOKEN)
            self.misskey = MisskeyAPI(instance_url, access_token)
            self.streaming = StreamingClient(instance_url, access_token)
            self.openai = OpenAIAPI(
                config.get(ConfigKeys.OPENAI_API_KEY),
                config.get(ConfigKeys.OPENAI_MODEL),
                config.get(ConfigKeys.OPENAI_API_BASE),
            )
            self.scheduler = AsyncIOScheduler()
        except (ValueError, TypeError, KeyError) as e:
            logger.error(f"初始化失败: {e}")
            raise ConfigurationError() from e
        self.persistence = PersistenceManager(config.get(ConfigKeys.DB_PATH))
        self.plugin_manager = PluginManager(config, persistence=self.persistence)
        self.runtime = BotRuntime(self)
        self.system_prompt = config.get(ConfigKeys.BOT_SYSTEM_PROMPT, "")
        self.bot_user_id = None
        self.bot_username = None
        logger.info("机器人初始化完成")

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()
        return False

    async def start(self) -> None:
        if self.runtime.running:
            logger.warning("机器人已在运行中")
            return
        logger.info("启动服务组件...")
        self.runtime.running = True
        await self._initialize_services()
        await self._setup_scheduler()
        await self._setup_streaming()
        logger.info("服务组件就绪，等待新任务...")
        memory_usage = get_memory_usage()
        logger.debug(f"内存使用: {memory_usage['rss_mb']} MB")

    async def _initialize_services(self) -> None:
        await self.persistence.initialize()
        await self.openai.initialize()
        current_user = await self.misskey.get_current_user()
        self.bot_user_id = current_user.get("id")
        self.bot_username = current_user.get("username")
        logger.info(
            f"已连接 Misskey 实例，机器人 ID: {self.bot_user_id}, @{self.bot_username}"
        )
        await self.plugin_manager.load_plugins()
        await self.plugin_manager.on_startup()

    async def _setup_scheduler(self) -> None:
        cron_jobs = [
            (self.runtime.reset_daily_counters, 0),
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
            self.streaming.on_reaction(self._handle_reaction)
            self.streaming.on_follow(self._handle_follow)
            await self.streaming.connect_once()
            self.runtime.add_task("streaming", self.streaming.connect())
        except (ValueError, OSError) as e:
            logger.error(f"设置 Streaming 连接失败: {e}")
            raise

    async def stop(self) -> None:
        if not self.runtime.running:
            logger.warning("机器人已停止")
            return
        logger.info("停止服务组件...")
        self.runtime.running = False
        try:
            await self.plugin_manager.on_shutdown()
            await self.plugin_manager.cleanup_plugins()
            if (
                hasattr(self.scheduler, "_eventloop")
                and self.scheduler._eventloop is not None
            ):
                self.scheduler.shutdown(wait=False)
            await self.runtime.cleanup_tasks()
            await self.streaming.close()
            await self.misskey.close()
            await self.openai.close()
            await ClientSession.close_session()
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
        ) as e:
            logger.error(f"处理提及时出错: {e}")
            await self._handle_error(e, mention_data=mention_data)

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
            if not self._is_bot_mentioned(text):
                logger.debug(f"用户 @{username} 的回复中未 @机器人，跳过处理")
                mention_id = None
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

    def _is_bot_mentioned(self, text: str) -> bool:
        if not text or not self.bot_username:
            return False
        return f"@{self.bot_username}" in text

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
        reply = await self.openai.generate_text(
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

    async def _handle_reaction(self, reaction: Dict[str, Any]) -> None:
        username = extract_username(reaction)
        note_id = reaction.get("note", {}).get("id", "unknown")
        reaction_type = reaction.get("reaction", "unknown")
        logger.info(f"用户 @{username} 对帖子 {note_id} 做出反应: {reaction_type}")
        logger.debug(f"反应数据: {json.dumps(reaction, ensure_ascii=False, indent=2)}")
        try:
            await self.plugin_manager.on_reaction(reaction)
        except (ValueError, OSError) as e:
            logger.error(f"处理反应事件时出错: {e}")

    async def _handle_follow(self, follow: Dict[str, Any]) -> None:
        username = extract_username(follow)
        logger.info(f"用户 @{username} 关注了 @{self.bot_username}")
        logger.debug(f"关注数据: {json.dumps(follow, ensure_ascii=False, indent=2)}")
        try:
            await self.plugin_manager.on_follow(follow)
        except (ValueError, OSError) as e:
            logger.error(f"处理关注事件时出错: {e}")

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
            await self._handle_error(e, message=message)

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
        reply = await self.openai.generate_chat(chat_history, **self._ai_config)
        logger.debug("生成聊天回复成功")
        await self.misskey.send_message(user_id, reply)
        logger.info(f"已回复 @{username}: {self._format_log_text(reply)}")
        chat_history.append({"role": "assistant", "content": reply})

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
        max_posts = self.config.get(ConfigKeys.BOT_AUTO_POST_MAX_PER_DAY)
        if not self.runtime.running or not self.runtime.check_post_counter(max_posts):
            return
        try:
            max_posts = self.config.get(ConfigKeys.BOT_AUTO_POST_MAX_PER_DAY)

            def log_post_success(post_content: str) -> None:
                logger.info(f"自动发帖成功: {self._format_log_text(post_content)}")
                logger.info(f"今日发帖计数: {self.runtime.posts_today}/{max_posts}")

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
                self.runtime.post_count()
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
        post_prompt = self.config.get(ConfigKeys.BOT_AUTO_POST_PROMPT, "")
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
        self.runtime.post_count()
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
        return await self.openai.generate_text(
            full_prompt, system_prompt, **(ai_config or self._ai_config)
        )

    async def _handle_error(
        self,
        error: Exception,
        mention_data: Dict[str, Any] = None,
        message: Dict[str, Any] = None,
    ) -> None:
        error_type = type(error).__name__
        error_message = ERROR_MESSAGES.get(error_type, DEFAULT_ERROR_MESSAGE)
        try:
            if mention_data:
                await self.misskey.create_note(
                    text=f"@{mention_data['username']}\n{error_message}",
                    reply_id=mention_data["reply_target_id"],
                )
            elif message:
                user_id = extract_user_id(message)
                await self.misskey.send_message(user_id, error_message)
        except (APIConnectionError, APIRateLimitError, OSError) as e:
            logger.error(f"发送错误回复失败: {e}")

    def _format_log_text(self, text: str, max_length: int = 50) -> str:
        return (
            "None"
            if not text
            else f"{text[:max_length]}{'...' if len(text) > max_length else ''}"
        )

    @property
    def _ai_config(self) -> Dict[str, Any]:
        return {
            "max_tokens": self.config.get(ConfigKeys.OPENAI_MAX_TOKENS),
            "temperature": self.config.get(ConfigKeys.OPENAI_TEMPERATURE),
        }
