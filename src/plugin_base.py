#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import pluggy
from typing import Dict, Any, Optional, Callable
from loguru import logger

from .interfaces import IPlugin
from .utils import extract_username, extract_user_id

hookimpl = pluggy.HookimplMarker("misskey_ai")


class PluginContext:
    def __init__(
        self,
        name: str,
        config: Dict[str, Any],
        persistence_manager=None,
        validator=None,
        utils_provider=None,
    ):
        self.name = name
        self.config = config
        self.persistence_manager = persistence_manager
        self.validator = validator
        self.utils_provider = utils_provider or {}


class PluginBase(IPlugin):
    def __init__(
        self, config_or_context, utils_provider: Optional[Dict[str, Callable]] = None
    ):
        if isinstance(config_or_context, PluginContext):
            context = config_or_context
            self.config = context.config
            self.name = context.name
            self.persistence_manager = context.persistence_manager
            self.validator = context.validator
            self._utils = context.utils_provider
        else:
            self.config = config_or_context
            self.name = self.__class__.__name__
            self.persistence_manager = None
            self.validator = None
            self._utils = utils_provider or {}
        self.enabled = self.config.get("enabled", False)
        self.priority = self.config.get("priority", 0)

    async def __aenter__(self):
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.cleanup()
        return False

    @hookimpl
    async def initialize(self) -> bool:
        return True

    @hookimpl
    async def cleanup(self) -> None:
        pass

    @hookimpl
    async def on_startup(self) -> None:
        pass

    @hookimpl
    async def on_mention(
        self, _mention_data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        return None

    @hookimpl
    async def on_message(
        self, _message_data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        return None

    @hookimpl
    async def on_auto_post(self) -> Optional[Dict[str, Any]]:
        return None

    @hookimpl
    async def on_shutdown(self) -> None:
        pass

    @hookimpl
    def get_info(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "enabled": self.enabled,
            "priority": self.priority,
            "description": getattr(self, "description", "No description available"),
        }

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        logger.info(f"插件 {self.name} {'启用' if enabled else '禁用'}")

    def _extract_username(self, data: Dict[str, Any]) -> str:
        return extract_username(data)

    def _extract_user_id(self, data: Dict[str, Any]) -> Optional[str]:
        return extract_user_id(data)

    def _log_plugin_action(self, action: str, details: str = "") -> None:
        if details:
            logger.info(f"{self.name} 插件{action}: {details}")
        else:
            logger.info(f"{self.name} 插件{action}")

    def _validate_plugin_response(self, response: Dict[str, Any]) -> bool:
        if not isinstance(response, dict):
            return False
        if "handled" in response and not isinstance(response["handled"], bool):
            return False
        if "plugin_name" in response and not isinstance(response["plugin_name"], str):
            return False
        if "response" in response and not isinstance(response["response"], str):
            return False
        return True
