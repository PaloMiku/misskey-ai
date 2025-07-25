#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import asyncio
from typing import Any, Dict, List, Optional

import aiohttp
from loguru import logger

from .exceptions import APIConnectionError, APIRateLimitError, AuthenticationError
from .constants import (
    RETRYABLE_HTTP_CODES,
    HTTP_OK,
    HTTP_UNAUTHORIZED,
    HTTP_FORBIDDEN,
    HTTP_TOO_MANY_REQUESTS,
    API_MAX_RETRIES,
    API_TIMEOUT,
)
from .utils import retry_async


class MisskeyAPI:
    def __init__(self, config, instance_url: str, access_token: str):
        self.config = config
        try:
            self.instance_url = config._validate_url_param(
                instance_url, "实例 URL"
            ).rstrip("/")
            self.access_token = config._validate_access_token_param(
                access_token, "访问令牌"
            )
        except ValueError as e:
            config._log_validation_error(e, "Misskey API 初始化")
            raise
        self.headers = {
            "Content-Type": "application/json",
            "User-Agent": "MisskeyBot/1.0",
        }
        self.session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
        return False

    async def close(self) -> None:
        if self.session is not None and not self.session.closed:
            connector = self.session.connector
            await self.session.close()
            if connector is not None and not connector.closed:
                await connector.close()
            await asyncio.sleep(0.1)
            self.session = None
        logger.debug("Misskey API 客户端连接已关闭")

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=API_TIMEOUT)
            self.session = aiohttp.ClientSession(timeout=timeout)
        return self.session

    def _is_retryable_error(self, status_code: int) -> bool:
        return status_code in RETRYABLE_HTTP_CODES

    @retry_async(
        max_retries=API_MAX_RETRIES,
        retryable_exceptions=(aiohttp.ClientError, APIConnectionError),
    )
    async def _make_request(
        self, endpoint: str, data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        self.config._validate_string_param(endpoint, "API 端点", min_length=1)
        if data is not None and not isinstance(data, dict):
            raise ValueError("请求数据必须是字典格式")
        session = await self._ensure_session()
        url = f"{self.instance_url}/api/{endpoint}"
        request_data = {"i": self.access_token}
        if data:
            request_data.update(data)
        try:
            logger.debug(f"请求 Misskey API: {endpoint}")
            async with session.post(
                url, json=request_data, headers=self.headers
            ) as response:
                if response.status == HTTP_OK:
                    try:
                        result = await response.json()
                        logger.debug(f"Misskey API 请求成功: {endpoint}")
                        return result
                    except json.JSONDecodeError as e:
                        raise APIConnectionError("Misskey", f"API 返回无效 JSON: {e}")

                elif response.status == HTTP_UNAUTHORIZED:
                    logger.error("API 认证失败")
                    raise AuthenticationError("Misskey API 认证失败，请检查访问令牌")
                elif response.status == HTTP_FORBIDDEN:
                    logger.error("API 权限不足")
                    raise AuthenticationError("Misskey API 权限不足，请求被拒绝")
                elif response.status == HTTP_TOO_MANY_REQUESTS:
                    raise APIRateLimitError("Misskey API 速率限制")
                elif self._is_retryable_error(response.status):
                    error_text = await response.text()
                    raise APIConnectionError(
                        "Misskey", f"HTTP {response.status}: {error_text}"
                    )
                else:
                    error_text = await response.text()
                    logger.error(f"API 请求失败: {response.status} - {error_text}")
                    raise APIConnectionError(
                        "Misskey", f"HTTP {response.status}: {error_text}"
                    )

        except aiohttp.ClientError as e:
            logger.warning(f"网络错误: {e}")
            raise APIConnectionError("Misskey", f"网络连接失败: {e}")
        except (AuthenticationError, ValueError):
            raise
        except (ConnectionError, OSError, TimeoutError) as e:
            logger.error(f"网络连接错误: {e}")
            raise APIConnectionError("Misskey", f"网络连接错误: {e}")
        except (TypeError, KeyError) as e:
            logger.error(f"Misskey API 数据处理错误: {e}")
            raise ValueError(f"API 响应数据格式错误: {e}")
        except Exception as e:
            logger.error(f"未知错误: {e}")
            raise APIConnectionError("Misskey", f"未知错误: {e}")

    async def request(
        self, endpoint: str, data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        return await self._make_request(endpoint, data)

    async def create_note(
        self,
        text: str,
        visibility: Optional[str] = None,
        reply_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if reply_id:
            try:
                original_note = await self.get_note(reply_id)
                original_visibility = original_note.get("visibility", "public")
                if visibility is None:
                    visibility = original_visibility
                else:
                    visibility_priority = {
                        "specified": 0,
                        "followers": 1,
                        "home": 2,
                        "public": 3,
                    }
                    original_priority = visibility_priority.get(original_visibility, 3)
                    reply_priority = visibility_priority.get(visibility, 3)
                    if reply_priority > original_priority:
                        visibility = original_visibility
                        logger.debug(
                            f"调整回复可见性从 {visibility} 到 {original_visibility} 以匹配原笔记"
                        )
            except Exception as e:
                logger.warning(f"获取原笔记可见性失败，使用默认设置: {e}")
                if visibility is None:
                    visibility = "home"
        else:
            if visibility is None:
                if self.config:
                    visibility = self.config.get("bot.auto_post.visibility", "public")
                else:
                    visibility = "public"
        data = {
            "text": text,
            "visibility": visibility,
        }
        if reply_id:
            data["replyId"] = reply_id
        result = await self._make_request("notes/create", data)
        logger.debug(
            f"Misskey 发帖成功，note_id: {result.get('createdNote', {}).get('id', 'unknown')}"
        )
        return result

    async def get_note(self, note_id: str) -> Dict[str, Any]:
        data = {
            "noteId": note_id,
        }
        return await self._make_request("notes/show", data)

    async def get_mentions(
        self, limit: int = 10, since_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        data = {
            "limit": limit,
        }
        if since_id:
            data["sinceId"] = since_id
        return await self._make_request("notes/mentions", data)

    async def get_user(
        self, user_id: Optional[str] = None, username: Optional[str] = None
    ) -> Dict[str, Any]:
        if not (user_id or username):
            raise ValueError("必须提供 user_id 或 username")
        data = {}
        if user_id:
            data["userId"] = user_id
        elif username:
            data["username"] = username
        return await self._make_request("users/show", data)

    async def get_current_user(self) -> Dict[str, Any]:
        return await self._make_request("i", {})

    async def send_message(self, user_id: str, text: str) -> Dict[str, Any]:
        data = {
            "toUserId": user_id,
            "text": text,
        }
        result = await self._make_request("chat/messages/create-to-user", data)
        logger.debug(f"Misskey 聊天发送成功，message_id: {result.get('id', 'unknown')}")
        return result

    async def get_messages(
        self, user_id: str, limit: int = 10, since_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        data = {
            "userId": user_id,
            "limit": limit,
        }
        if since_id:
            data["sinceId"] = since_id
        return await self._make_request("chat/messages/user-timeline", data)

    async def get_all_chat_messages(
        self, limit: int = 10, room: bool = False
    ) -> List[Dict[str, Any]]:
        data = {
            "limit": limit,
            "room": room,
        }
        try:
            chat_messages = await self._make_request("chat/history", data)
            logger.debug(f"通过 chat/history API 获取到 {len(chat_messages)} 条聊天")
            return chat_messages
        except Exception as e:
            logger.debug(f"获取聊天失败: {e}")
            return []
