import importlib.util
import sys
from pathlib import Path
from typing import Any, Optional

import yaml
from loguru import logger

from . import utils
from .config import Config
from .plugin_base import PluginBase

__all__ = ("PluginManager",)


class PluginManager:
    def __init__(
        self,
        config: Config,
        plugins_dir: str = "plugins",
        persistence=None,
    ):
        self.config = config
        self.plugins_dir = Path(plugins_dir)
        self.plugins: dict[str, PluginBase] = {}
        self.persistence = persistence

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.cleanup_plugins()
        return False

    async def load_plugins(self) -> None:
        if not self.plugins_dir.exists():
            logger.info(f"插件目录不存在: {self.plugins_dir}")
            return
        for plugin_dir in self.plugins_dir.iterdir():
            if (
                plugin_dir.is_dir()
                and not plugin_dir.name.startswith(".")
                and plugin_dir.name not in {"__pycache__", "example"}
            ):
                await self._load_plugin(
                    plugin_dir, self._load_plugin_config(plugin_dir)
                )
        await self._initialize_plugins()
        enabled_count = sum(plugin.enabled for plugin in self.plugins.values())
        logger.info(f"已发现 {len(self.plugins)} 个插件，{enabled_count} 个已启用")

    def _load_plugin_config(self, plugin_dir: Path) -> dict[str, Any]:
        config_file = plugin_dir / "config.yaml"
        if not config_file.exists():
            return {"enabled": False}
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except (OSError, yaml.YAMLError, UnicodeDecodeError) as e:
            logger.error(f"加载插件 {plugin_dir.name} 配置文件时出错: {e}")
            return {}

    async def _load_plugin(
        self, plugin_dir: Path, plugin_config: dict[str, Any]
    ) -> None:
        try:
            plugin_file = plugin_dir / f"{plugin_dir.name}.py"
            if not plugin_file.exists():
                logger.warning(
                    f"插件目录 {plugin_dir.name} 中未找到 {plugin_dir.name}.py 文件"
                )
                return
            if not (module := self._load_plugin_module(plugin_dir, plugin_file)):
                return
            if not (plugin_class := self._find_plugin_class(module, plugin_dir.name)):
                return
            plugin_instance = self._create_plugin_instance(
                plugin_class, plugin_dir.name, plugin_config
            )
            self.plugins[plugin_dir.name] = plugin_instance
            status = "启用" if plugin_instance.enabled else "禁用"
            logger.debug(f"已发现插件: {plugin_dir.name} (状态: {status})")
        except (ImportError, AttributeError, OSError) as e:
            logger.error(f"加载插件 {plugin_dir.name} 失败: {e}")

    def _load_plugin_module(self, plugin_dir: Path, plugin_file: Path):
        spec = importlib.util.spec_from_file_location(
            f"plugins.{plugin_dir.name}.plugin", plugin_file
        )
        if spec is None or spec.loader is None:
            logger.warning(f"无法加载插件规范: {plugin_dir.name}")
            return None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module

    def _find_plugin_class(self, module, plugin_name):
        for attr in (getattr(module, name) for name in dir(module)):
            if (
                isinstance(attr, type)
                and issubclass(attr, PluginBase)
                and attr is not PluginBase
            ):
                return attr
        logger.warning(f"插件 {plugin_name.capitalize()} 中未找到有效的插件类")
        return None

    def _create_plugin_instance(self, plugin_class, plugin_name, plugin_config):
        from .plugin_base import PluginContext

        utils_provider = {
            "extract_username": utils.extract_username,
            "extract_user_id": utils.extract_user_id,
        }
        context = PluginContext(
            name=plugin_name.capitalize(),
            config=plugin_config,
            persistence_manager=self.persistence,
            utils_provider=utils_provider,
        )
        return plugin_class(context)

    async def _initialize_plugins(self) -> None:
        for _, plugin in sorted(
            self.plugins.items(), key=lambda x: x[1].priority, reverse=True
        ):
            if not plugin.enabled:
                continue
            try:
                if await plugin.initialize():
                    logger.debug(f"插件 {plugin.name} 初始化完成")
                else:
                    logger.warning(f"插件 {plugin.name} 初始化失败")
                    plugin.set_enabled(False)
            except (ValueError, OSError) as e:
                logger.error(f"初始化插件 {plugin.name} 时出错: {e}")
                plugin.set_enabled(False)

    async def cleanup_plugins(self) -> None:
        for plugin in self.plugins.values():
            if plugin.enabled:
                try:
                    await plugin.cleanup()
                except (ValueError, OSError) as e:
                    logger.error(f"清理插件 {plugin.name} 时出错: {e}")

    async def on_startup(self) -> None:
        await self.call_plugin_hook("on_startup")

    async def on_mention(self, mention_data: dict[str, Any]) -> list[dict[str, Any]]:
        return await self.call_plugin_hook("on_mention", mention_data)

    async def on_message(self, message_data: dict[str, Any]) -> list[dict[str, Any]]:
        return await self.call_plugin_hook("on_message", message_data)

    async def on_reaction(self, reaction_data: dict[str, Any]) -> list[dict[str, Any]]:
        return await self.call_plugin_hook("on_reaction", reaction_data)

    async def on_follow(self, follow_data: dict[str, Any]) -> list[dict[str, Any]]:
        return await self.call_plugin_hook("on_follow", follow_data)

    async def on_auto_post(self) -> list[dict[str, Any]]:
        return await self.call_plugin_hook("on_auto_post")

    async def on_shutdown(self) -> None:
        await self.call_plugin_hook("on_shutdown")

    async def call_plugin_hook(self, hook_name: str, *args, **kwargs) -> list[Any]:
        results = []
        enabled_plugins = sorted(
            [p for p in self.plugins.values() if p.enabled],
            key=lambda x: x.priority,
            reverse=True,
        )
        for plugin in enabled_plugins:
            if not hasattr(plugin, hook_name):
                continue
            try:
                if (
                    result := await getattr(plugin, hook_name)(*args, **kwargs)
                ) is not None:
                    results.append(result)
            except (ValueError, OSError) as e:
                logger.error(f"调用插件 {plugin.name} 的 {hook_name} hook 时出错: {e}")
        return results

    # RESERVED
    def get_plugin_info(self) -> list[dict[str, Any]]:
        return [plugin.get_info() for plugin in self.plugins.values()]

    # RESERVED
    def get_plugin(self, name: str) -> Optional[PluginBase]:
        return self.plugins.get(name)

    # RESERVED
    def enable_plugin(self, name: str) -> bool:
        if plugin := self.plugins.get(name):
            plugin.set_enabled(True)
            return True
        return False

    # RESERVED
    def disable_plugin(self, name: str) -> bool:
        if plugin := self.plugins.get(name):
            plugin.set_enabled(False)
            return True
        return False
