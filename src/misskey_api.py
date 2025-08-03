import json
from typing import Any, Dict, List, Optional

import aiohttp
from loguru import logger

from .constants import (
    API_MAX_RETRIES,
    HTTP_FORBIDDEN,
    HTTP_OK,
    HTTP_TOO_MANY_REQUESTS,
    HTTP_UNAUTHORIZED,
    RETRYABLE_HTTP_CODES,
)
from .exceptions import APIConnectionError, APIRateLimitError, AuthenticationError
from .http_client import HTTPSession
from .interfaces import IAPIClient
from .utils import retry_async

__all__ = ("MisskeyAPI",)


class MisskeyAPI(IAPIClient):
    def __init__(self, instance_url: str, access_token: str):
        self.instance_url = instance_url.rstrip("/")
        self.access_token = access_token
        self.http_client = HTTPSession
        self.http_client.set_token(access_token)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
        return False

    async def close(self) -> None:
        logger.debug("Misskey API 客户端连接已关闭")

    @property
    def session(self):
        return self.http_client.session

    def _is_retryable_error(self, status_code: int) -> bool:
        return status_code in RETRYABLE_HTTP_CODES

    def _handle_response_status(self, response, endpoint: str):
        status = response.status
        if status == HTTP_UNAUTHORIZED:
            logger.error(f"API 认证失败: {endpoint}")
            raise AuthenticationError()
        elif status == HTTP_FORBIDDEN:
            logger.error(f"API 权限不足: {endpoint}")
            raise AuthenticationError()
        elif status == HTTP_TOO_MANY_REQUESTS:
            logger.warning(f"API 频率限制: {endpoint}")
            raise APIRateLimitError()
        return self._is_retryable_error(status)

    async def _process_response(self, response, endpoint: str):
        if response.status == HTTP_OK:
            try:
                result = await response.json()
                logger.debug(f"Misskey API 请求成功: {endpoint}")
                return result
            except json.JSONDecodeError as e:
                logger.error(f"响应不是有效的 JSON 格式: {e}")
                raise APIConnectionError()

        is_retryable = self._handle_response_status(response, endpoint)
        error_text = await response.text()
        if not is_retryable:
            logger.error(f"API 请求失败: {response.status} - {error_text}")
        raise APIConnectionError()

    @retry_async(
        max_retries=API_MAX_RETRIES,
        retryable_exceptions=(Exception, APIConnectionError),
    )
    async def _make_request(
        self, endpoint: str, data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        url = f"{self.instance_url}/api/{endpoint}"

        payload = {"i": self.access_token}
        if data:
            payload.update(data)

        try:
            async with self.session.post(url, json=payload) as response:
                return await self._process_response(response, endpoint)
        except (
            aiohttp.ClientError,
            json.JSONDecodeError,
        ) as e:
            logger.error(f"HTTP 请求错误: {e}")
            raise APIConnectionError() from e

    async def request(
        self, endpoint: str, data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        return await self._make_request(endpoint, data)

    def _determine_reply_visibility(
        self, original_visibility: str, visibility: Optional[str]
    ) -> str:
        if visibility is None:
            return original_visibility
        visibility_priority = {
            "specified": 0,
            "followers": 1,
            "home": 2,
            "public": 3,
        }
        original_priority = visibility_priority.get(original_visibility, 3)
        reply_priority = visibility_priority.get(visibility, 3)
        if reply_priority > original_priority:
            logger.debug(
                f"调整回复可见性从 {visibility} 到 {original_visibility} 以匹配原笔记"
            )
            return original_visibility
        return visibility

    async def _get_visibility_for_reply(
        self, reply_id: str, visibility: Optional[str]
    ) -> str:
        try:
            original_note = await self.get_note(reply_id)
            original_visibility = original_note.get("visibility", "public")
            return self._determine_reply_visibility(original_visibility, visibility)
        except (APIConnectionError, APIRateLimitError, ValueError) as e:
            logger.warning(f"获取原笔记可见性失败，使用默认设置: {e}")
            return visibility if visibility is not None else "home"

    def _get_default_visibility(self) -> str:
        return "public"

    async def create_note(
        self,
        text: str,
        visibility: Optional[str] = None,
        reply_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if reply_id:
            visibility = await self._get_visibility_for_reply(reply_id, visibility)
        elif visibility is None:
            visibility = self._get_default_visibility()
        data = {
            "text": text,
            "visibility": visibility,
            **({"replyId": reply_id} if reply_id else {}),
        }
        result = await self._make_request("notes/create", data)
        logger.debug(
            f"Misskey 发帖成功，note_id: {result.get('createdNote', {}).get('id', 'unknown')}"
        )
        return result

    async def get_note(self, note_id: str) -> Dict[str, Any]:
        return await self._make_request("notes/show", {"noteId": note_id})

    async def get_current_user(self) -> Dict[str, Any]:
        return await self._make_request("i", {})

    async def send_message(self, user_id: str, text: str) -> Dict[str, Any]:
        result = await self._make_request(
            "chat/messages/create-to-user", {"toUserId": user_id, "text": text}
        )
        logger.debug(f"Misskey 聊天发送成功，message_id: {result.get('id', 'unknown')}")
        return result

    async def get_messages(
        self, user_id: str, limit: int = 10, since_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        data = {"userId": user_id, "limit": limit}
        if since_id:
            data["sinceId"] = since_id
        return await self._make_request("chat/messages/user-timeline", data)
