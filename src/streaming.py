#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import json
import uuid
from enum import Enum
from typing import Any, Dict, Optional, Callable, List, Awaitable

import aiohttp
from cachetools import LRUCache
from loguru import logger

from .exceptions import WebSocketConnectionError
from .constants import WS_HEARTBEAT_INTERVAL, MAX_PROCESSED_ITEMS_CACHE


class ChannelType(Enum):
    MAIN = "main"


class StreamingClient:
    def __init__(self, instance_url: str, access_token: str):
        self.instance_url = instance_url.rstrip("/")
        self.access_token = access_token
        self.ws_connection: Optional[aiohttp.ClientWebSocketResponse] = None
        self.session: Optional[aiohttp.ClientSession] = None
        self.heartbeat_task: Optional[asyncio.Task] = None
        self.message_task: Optional[asyncio.Task] = None
        self.channels: Dict[str, Dict[str, Any]] = {}
        self.event_handlers: Dict[str, List[Callable]] = {}
        self.running = False
        self.processed_events = LRUCache(maxsize=MAX_PROCESSED_ITEMS_CACHE)

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

    def on_message(self, handler: Callable[[Dict[str, Any]], Any]) -> None:
        self._add_event_handler("message", handler)

    def _add_event_handler(self, event_type: str, handler: Callable) -> None:
        if event_type not in self.event_handlers:
            self.event_handlers[event_type] = []
        self.event_handlers[event_type].append(handler)

    async def connect(self, channels: Optional[list] = None) -> None:
        if self.running:
            logger.warning("Streaming 客户端已在运行")
            return
        self.running = True

        async def start_connection():
            await self._connect_websocket()
            if channels:
                for channel in channels:
                    if isinstance(channel, str):
                        try:
                            channel_type = ChannelType(channel)
                            await self.connect_channel(channel_type)
                        except ValueError:
                            logger.warning(f"未知的频道类型: {channel}")
                    elif isinstance(channel, ChannelType):
                        await self.connect_channel(channel)
            else:
                await self.connect_channel(ChannelType.MAIN)

        await start_connection()
        logger.debug("Streaming 客户端已启动")

    async def disconnect(self) -> None:
        if not self.running:
            return
        self.running = False
        await self._disconnect_all_channels()
        self.processed_events.clear()
        logger.debug("Streaming 客户端已断开连接")

    @property
    def is_connected(self) -> bool:
        return (
            self.ws_connection is not None
            and not self.ws_connection.closed
            and self.running
        )

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
        if self.ws_connection and not self.ws_connection.closed:
            await self.ws_connection.send_str(json.dumps(message))
            self.channels[channel_id] = {"type": channel_type, "params": params or {}}
            logger.debug(f"已连接频道: {channel_type.value} (ID: {channel_id})")
        else:
            logger.error(f"WebSocket 连接不可用，无法连接频道: {channel_type.value}")
            raise WebSocketConnectionError("WebSocket 连接不可用")
        return channel_id

    async def disconnect_channel(self, channel_type: ChannelType) -> None:
        channels_to_remove = []
        for channel_id, channel_info in self.channels.items():
            if channel_info["type"] == channel_type:
                message = {"type": "disconnect", "body": {"id": channel_id}}
                if self.ws_connection and not self.ws_connection.closed:
                    await self.ws_connection.send_str(json.dumps(message))
                channels_to_remove.append(channel_id)
        for channel_id in channels_to_remove:
            del self.channels[channel_id]
        logger.debug(f"已断开频道连接: {channel_type.value}")

    async def _connect_websocket(self) -> None:
        ws_url = f"{self.instance_url.replace('https://', 'wss://').replace('http://', 'ws://')}/streaming?i={self.access_token}"
        safe_url = f"{self.instance_url.replace('https://', 'wss://').replace('http://', 'ws://')}/streaming"
        logger.debug(f"连接 WebSocket: {safe_url}")
        if self.session is None:
            self.session = aiohttp.ClientSession()
        try:
            self.ws_connection = await self.session.ws_connect(ws_url)
            logger.debug(f"WebSocket 连接成功: {safe_url}")
            self.heartbeat_task = asyncio.create_task(self._heartbeat())
            self.message_task = asyncio.create_task(self._handle_messages())
            logger.debug("WebSocket 心跳和消息处理任务已启动")
        except Exception as e:
            await self._cleanup_failed_connection()
            logger.error(f"WebSocket 连接失败: {e}")
            logger.debug(f"WebSocket 连接错误详情: {e}", exc_info=True)
            raise WebSocketConnectionError(f"WebSocket 连接失败: {e}")

    async def _close_websocket(self) -> None:
        if self.heartbeat_task and not self.heartbeat_task.done():
            self.heartbeat_task.cancel()
            try:
                await self.heartbeat_task
            except asyncio.CancelledError:
                pass
        if self.message_task and not self.message_task.done():
            self.message_task.cancel()
            try:
                await self.message_task
            except asyncio.CancelledError:
                pass
        if self.ws_connection and not self.ws_connection.closed:
            await self.ws_connection.close()
        if self.session and not self.session.closed:
            await self.session.close()
        self.ws_connection = None
        self.session = None
        self.heartbeat_task = None
        self.message_task = None

    async def _cleanup_failed_connection(self) -> None:
        try:
            if self.ws_connection and not self.ws_connection.closed:
                await self.ws_connection.close()
            if self.session and not self.session.closed:
                await self.session.close()
            self.ws_connection = None
            self.session = None
            self.heartbeat_task = None
            self.message_task = None
        except Exception as e:
            logger.debug(f"清理失败连接时出错: {e}")

    async def _disconnect_all_channels(self) -> None:
        for channel_id in list(self.channels.keys()):
            message = {"type": "disconnect", "body": {"id": channel_id}}
            if self.ws_connection and not self.ws_connection.closed:
                await self.ws_connection.send_str(json.dumps(message))
        self.channels.clear()
        logger.debug("已断开所有频道连接")

    async def _heartbeat(self) -> None:
        while self.running and self.ws_connection and not self.ws_connection.closed:
            try:
                ping_message = {"type": "ping", "body": {}}
                await self.ws_connection.send_str(json.dumps(ping_message))
                await asyncio.sleep(WS_HEARTBEAT_INTERVAL)
            except Exception as e:
                logger.error(f"心跳错误: {e}")
                break

    async def _send_pong(self) -> None:
        if self.ws_connection and not self.ws_connection.closed:
            pong_message = {"type": "pong", "body": {}}
            await self.ws_connection.send_str(json.dumps(pong_message))

    async def _handle_messages(self) -> None:
        while self.running and self.ws_connection and not self.ws_connection.closed:
            try:
                msg = await self.ws_connection.receive()
                if msg is None:
                    logger.debug("收到空消息，跳过处理")
                    continue
                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                        await self._process_message(data)
                    except json.JSONDecodeError as e:
                        logger.error(f"解码 WebSocket 消息失败: {e}")
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logger.error(f"WebSocket 错误: {self.ws_connection.exception()}")
                    break
                elif msg.type == aiohttp.WSMsgType.CLOSE:
                    logger.info("WebSocket 连接已关闭")
                    break
            except Exception as e:
                logger.error(f"处理 WebSocket 消息时出错: {e}")
                break

    async def _process_message(self, data: Dict[str, Any]) -> None:
        message_type = data.get("type")
        body = data.get("body", {})
        if message_type == "channel":
            await self._handle_channel_message(body)
        elif message_type == "pong":
            logger.debug("收到心跳响应")
        elif message_type == "ping":
            await self._send_pong()
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
        event_body = event_data.get("body", {})
        if not event_type:
            await self._handle_no_event_type(channel_type, event_data)
            return
        await self._handle_typed_event(channel_type, event_type, event_body, event_data)

    async def _handle_no_event_type(
        self, channel_type: ChannelType, event_data: Dict[str, Any]
    ) -> None:
        event_id = event_data.get("id", "unknown")
        logger.debug(f"收到无事件类型的数据 - 事件 ID: {event_id}")
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
            logger.debug(f"收到未知频道的事件: {channel_type.value} - {event_type}")

    async def _handle_main_channel_event(
        self, event_type: str, event_body: Dict[str, Any], event_data: Dict[str, Any]
    ) -> None:
        if event_type == "mention":
            await self._call_handlers("mention", event_data)
        elif event_type == "reply":
            await self._call_handlers("mention", event_data)
        elif event_type == "chat":
            await self._call_handlers("message", event_data)
        else:
            logger.debug(f"收到未知类型的 main 频道事件: {event_type}")
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
            except Exception as e:
                logger.error(f"事件处理器执行失败 ({event_type}): {e}")
                logger.debug(f"{event_type} 处理器错误详情: {e}", exc_info=True)

    def _is_duplicate_event(
        self, event_id: Optional[str], event_type: Optional[str]
    ) -> bool:
        if event_id and event_id in self.processed_events:
            logger.debug(
                f"检测到重复事件，跳过处理 - 事件 ID: {event_id}, 类型: {event_type}"
            )
            return True
        return False

    def _track_event(self, event_id: Optional[str]) -> None:
        if event_id:
            self.processed_events[event_id] = True
