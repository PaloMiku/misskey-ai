import asyncio
import json
import uuid
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, List, Optional

import aiohttp
from cachetools import LRUCache
from loguru import logger

from .constants import MAX_CACHE, RECEIVE_TIMEOUT
from .exceptions import WebSocketConnectionError, WebSocketReconnectError
from .http_client import HTTPSession
from .interfaces import IStreamingClient

__all__ = ("ChannelType", "StreamingClient")


class ChannelType(Enum):
    MAIN = "main"


class StreamingClient(IStreamingClient):
    def __init__(self, instance_url: str, access_token: str):
        self.instance_url = instance_url.rstrip("/")
        self.access_token = access_token
        self.ws_connection: Optional[aiohttp.ClientWebSocketResponse] = None
        self.http_client = HTTPSession
        self.channels: Dict[str, Dict[str, Any]] = {}
        self.event_handlers: Dict[str, List[Callable]] = {}
        self.processed_events = LRUCache(maxsize=MAX_CACHE)
        self.running = False
        self.should_reconnect = True
        self._first_connection = True

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
        return False

    async def close(self) -> None:
        await self.disconnect()
        await self._close_websocket()
        self.processed_events.clear()
        logger.debug("Streaming 客户端已关闭")

    def on_mention(self, handler: Callable[[Dict[str, Any]], Awaitable[None]]) -> None:
        self._add_event_handler("mention", handler)

    def on_message(self, handler: Callable[[Dict[str, Any]], Awaitable[None]]) -> None:
        self._add_event_handler("message", handler)

    def _add_event_handler(self, event_type: str, handler: Callable) -> None:
        self.event_handlers.setdefault(event_type, []).append(handler)

    async def connect(
        self, channels: Optional[list[str]] = None, *, reconnect: bool = True
    ) -> None:
        self.should_reconnect = reconnect
        while True:
            try:
                await self.connect_once(channels)
                await self.listen_messages()
            except WebSocketReconnectError:
                if not self.should_reconnect:
                    break
                logger.debug("WebSocket 连接异常，重新连接...")
                await asyncio.sleep(3)

    async def disconnect(self) -> None:
        self.should_reconnect = False
        self.running = False
        await self._disconnect_all_channels()
        await self._close_websocket()
        self.processed_events.clear()

    @property
    def _ws_available(self) -> bool:
        return self.ws_connection and not self.ws_connection.closed

    async def connect_channel(
        self, channel_type: ChannelType, params: Optional[Dict[str, Any]] = None
    ) -> str:
        existing_channels = [
            ch_id
            for ch_id, ch_info in self.channels.items()
            if ch_info["type"] == channel_type
        ]
        if existing_channels:
            logger.warning(
                f"频道类型 {channel_type.value} 已存在连接: {existing_channels}"
            )
            return existing_channels[0]
        channel_id = str(uuid.uuid4())
        message = {
            "type": "connect",
            "body": {
                "channel": channel_type.value,
                "id": channel_id,
                "params": params or {},
            },
        }
        if not self._ws_available:
            logger.error(f"WebSocket 连接不可用，无法连接频道: {channel_type.value}")
            raise WebSocketConnectionError()
        await self.ws_connection.send_json(message)
        self.channels[channel_id] = {"type": channel_type, "params": params or {}}
        if self._first_connection:
            logger.info(f"已连接频道: {channel_type.value} (ID: {channel_id})")
        return channel_id

    # RESERVED
    async def disconnect_channel(self, channel_type: ChannelType) -> None:
        channels_to_remove = [
            ch_id
            for ch_id, ch_info in self.channels.items()
            if ch_info["type"] == channel_type
        ]
        for channel_id in channels_to_remove:
            if self._ws_available:
                message = {"type": "disconnect", "body": {"id": channel_id}}
                await self.ws_connection.send_json(message)
            del self.channels[channel_id]
        logger.debug(f"已断开频道连接: {channel_type.value}")

    async def connect_once(self, channels: List[str] = None) -> None:
        if self.running:
            return
        self.running = True
        await self._connect_websocket()
        if channels:
            for channel in channels:
                if isinstance(channel, str):
                    try:
                        channel_type = ChannelType(channel)
                        await self.connect_channel(channel_type)
                    except ValueError as e:
                        logger.warning(f"未知的频道类型 {channel}: {e}")
                elif isinstance(channel, ChannelType):
                    await self.connect_channel(channel)
        else:
            await self.connect_channel(ChannelType.MAIN)
        if self._first_connection:
            logger.info("Streaming 客户端已启动")
            self._first_connection = False

    async def _connect_websocket(self) -> None:
        base_ws_url = self.instance_url.replace("https://", "wss://").replace(
            "http://", "ws://"
        )
        ws_url = f"{base_ws_url}/streaming?i={self.access_token}"
        safe_url = f"{base_ws_url}/streaming"
        try:
            self.ws_connection = await self.http_client.ws_connect(ws_url)
            if self._first_connection:
                logger.info(f"WebSocket 连接成功: {safe_url}")
        except Exception:
            await self._cleanup_failed_connection()
            logger.error("WebSocket 连接失败")
            logger.debug("WebSocket 连接错误详情", exc_info=True)
            raise WebSocketConnectionError()

    async def listen_messages(self) -> None:
        while self.running:
            if not self._ws_available:
                raise WebSocketReconnectError()
            try:
                msg = await asyncio.wait_for(
                    self.ws_connection.receive(), timeout=RECEIVE_TIMEOUT
                )
                if msg.type in (
                    aiohttp.WSMsgType.CLOSED,
                    aiohttp.WSMsgType.CLOSING,
                    aiohttp.WSMsgType.ERROR,
                ):
                    raise WebSocketReconnectError()
                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    await self._process_message(data)
            except asyncio.TimeoutError:
                continue
            except (
                aiohttp.ClientError,
                json.JSONDecodeError,
                OSError,
            ):
                raise WebSocketReconnectError()
            except (ValueError, TypeError, AttributeError, KeyError) as e:
                logger.error(f"解析消息失败: {e}")
                continue

    async def _close_websocket(self) -> None:
        if self.ws_connection and not self.ws_connection.closed:
            await self.ws_connection.close()
        self.ws_connection = None

    async def _cleanup_failed_connection(self) -> None:
        try:
            await self._close_websocket()
        except (OSError, ValueError) as e:
            logger.error(f"清理失败连接时出错: {e}")

    async def _disconnect_all_channels(self) -> None:
        for channel_id in list(self.channels.keys()):
            if self._ws_available:
                message = {"type": "disconnect", "body": {"id": channel_id}}
                await self.ws_connection.send_json(message)
        self.channels.clear()

    async def _process_message(self, data: Dict[str, Any]) -> None:
        message_type = data.get("type")
        body = data.get("body", {})
        if message_type == "channel":
            await self._handle_channel_message(body)
        else:
            logger.debug(f"收到未知消息类型: {message_type}")

    async def _handle_channel_message(self, body: Dict[str, Any]) -> None:
        channel_id = body.get("id")
        if channel_id not in self.channels:
            logger.debug(f"收到未知频道的消息: {channel_id}")
            return
        channel_info = self.channels[channel_id]
        channel_type = channel_info["type"]
        event_data = body.get("body", {})
        event_type = event_data.get("type")
        event_id = event_data.get("id")
        if not event_type and (
            event_data.get("fromUserId")
            and event_data.get("toUserId")
            and event_data.get("text") is not None
        ):
            event_type = "chat"
            event_data["type"] = event_type
        if self._is_duplicate_event(event_id, event_type):
            return
        self._track_event(event_id)
        if event_type:
            logger.debug(
                f"收到 {channel_type.value} 频道事件: {event_type} (频道 ID: {channel_id}, 事件 ID: {event_id})"
            )
        await self._dispatch_event(channel_type, event_data)

    async def _dispatch_event(
        self, channel_type: ChannelType, event_data: Dict[str, Any]
    ) -> None:
        event_type = event_data.get("type")
        if not event_type:
            await self._handle_no_event_type(channel_type, event_data)
        else:
            await self._handle_typed_event(
                channel_type, event_type, event_data.get("body", {}), event_data
            )

    async def _handle_no_event_type(
        self, channel_type: ChannelType, event_data: Dict[str, Any]
    ) -> None:
        event_id = event_data.get("id", "unknown")
        logger.debug(
            f"收到无事件类型的数据 - 频道: {channel_type.value}, 事件 ID: {event_id}"
        )
        logger.debug(f"数据结构: {list(event_data.keys())}")
        logger.debug(
            f"事件数据: {json.dumps(event_data, ensure_ascii=False, indent=2)}"
        )

    async def _handle_typed_event(
        self,
        channel_type: ChannelType,
        event_type: str,
        event_body: Dict[str, Any],
        event_data: Dict[str, Any],
    ) -> None:
        if channel_type == ChannelType.MAIN:
            await self._handle_main_channel_event(event_type, event_body, event_data)
        else:
            logger.debug(
                f"收到未知频道的事件: {channel_type.value} - {event_type}"
            )  # RESERVED

    async def _handle_main_channel_event(
        self, event_type: str, event_body: Dict[str, Any], event_data: Dict[str, Any]
    ) -> None:
        handler_map = {"mention": "mention", "reply": "mention", "chat": "message"}
        if event_type in handler_map:
            await self._call_handlers(handler_map[event_type], event_data)
        else:
            logger.debug(f"收到未知类型的 main 频道事件: {event_type}, {event_body}")
            logger.debug(f"数据结构: {list(event_data.keys())}")
            logger.debug(
                f"事件数据: {json.dumps(event_data, ensure_ascii=False, indent=2)}"
            )

    async def _call_handlers(self, event_type: str, data: Dict[str, Any]) -> None:
        handlers = self.event_handlers.get(event_type, [])
        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(data)
                else:
                    handler(data)
            except (ValueError, OSError) as e:
                logger.error(f"事件处理器执行失败 ({event_type}): {e}")
                logger.debug(f"{event_type} 处理器错误详情", exc_info=True)

    def _is_duplicate_event(
        self, event_id: Optional[str], event_type: Optional[str]
    ) -> bool:
        if event_id and event_id in self.processed_events:
            logger.debug(
                f"检测到重复事件，跳过处理 - {event_type}, 事件 ID: {event_id}"
            )
            return True
        return False

    def _track_event(self, event_id: Optional[str]) -> None:
        if event_id:
            self.processed_events[event_id] = True
