#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
from typing import Dict, Any, Optional, Callable

from loguru import logger

from .interfaces import IPlugin
from .utils import extract_username, extract_user_id


class PluginContext:
    def __init__(
        self,
        name: str,
        config: Dict[str, Any],
        persistence_manager=None,
        utils_provider=None,
    ):
        self.name = name
        self.config = config
        self.persistence_manager = persistence_manager
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
            self._utils = context.utils_provider
        else:
            self.config = config_or_context
            self.name = self.__class__.__name__
            self.persistence_manager = None
            self._utils = utils_provider or {}
        self.enabled = self.config.get("enabled", False)
        self.priority = self.config.get("priority", 0)
        self._initialized = False
        self._resources_to_cleanup = []

    async def __aenter__(self):
        result = await self.initialize()
        if result:
            self._initialized = True
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.cleanup()
        if self._resources_to_cleanup:
            logger.warning(
                f"插件 {self.name} 存在未清理的资源: {len(self._resources_to_cleanup)} 项"
            )
        self._initialized = False
        return False

    async def initialize(self) -> bool:
        return True

    async def cleanup(self) -> None:
        await self._cleanup_registered_resources()

    async def on_startup(self) -> None:
        pass

    async def on_mention(
        self, _mention_data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        return None

    async def on_message(
        self, _message_data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        return None

    async def on_auto_post(self) -> Optional[Dict[str, Any]]:
        return None

    async def on_shutdown(self) -> None:
        pass

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
        logger.info(f"{self.name} 插件{action}{': ' + details if details else ''}")

    def _validate_plugin_response(self, response: Any) -> bool:
        if not isinstance(response, dict):
            return False
        required_types = {"handled": bool, "plugin_name": str, "response": str}
        return all(
            isinstance(response.get(k), t)
            for k, t in required_types.items()
            if k in response
        )

    def _register_resource(self, resource: Any, cleanup_method: str = "close") -> None:
        self._resources_to_cleanup.append((resource, cleanup_method))

    async def _cleanup_registered_resources(self) -> None:
        for resource, cleanup_method in self._resources_to_cleanup:
            try:
                if hasattr(resource, cleanup_method):
                    method = getattr(resource, cleanup_method)
                    if asyncio.iscoroutinefunction(method):
                        await method()
                    else:
                        method()
            except (AttributeError, TypeError, RuntimeError, OSError) as e:
                logger.error(f"插件 {self.name} 清理资源失败: {e}")
        self._resources_to_cleanup.clear()
