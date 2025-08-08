#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
from functools import reduce
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from loguru import logger

from .constants import ConfigKeys
from .exceptions import ConfigurationError

__all__ = ("Config",)


class Config:
    def __init__(self, config_path: Optional[str] = None):
        self.config_path = config_path or os.environ.get("CONFIG_PATH", "config.yaml")
        self.config: Dict[str, Any] = {}

    async def load(self) -> None:
        config_path = Path(self.config_path)
        if not config_path.exists():
            raise ConfigurationError()
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                self.config = yaml.safe_load(f)
            logger.debug(f"已加载配置文件: {config_path}")
            self._override_from_env()
            self._validate_config()
        except yaml.YAMLError as e:
            logger.error(f"YAML 配置文件解析错误: {e}")
            raise ConfigurationError() from e
        except OSError as e:
            logger.error(f"配置文件读取错误: {e}")
            raise ConfigurationError() from e
        except (ValueError, TypeError, AttributeError) as e:
            logger.error(f"配置处理错误: {e}")
            raise ConfigurationError() from e

    def _override_from_env(self) -> None:
        env_mappings = {
            "MISSKEY_INSTANCE_URL": (ConfigKeys.MISSKEY_INSTANCE_URL, str),
            "MISSKEY_ACCESS_TOKEN": (ConfigKeys.MISSKEY_ACCESS_TOKEN, str),
            "OPENAI_API_KEY": (ConfigKeys.OPENAI_API_KEY, str),
            "OPENAI_MODEL": (ConfigKeys.OPENAI_MODEL, str),
            "OPENAI_API_BASE": (ConfigKeys.OPENAI_API_BASE, str),
            "OPENAI_MAX_TOKENS": (ConfigKeys.OPENAI_MAX_TOKENS, int),
            "OPENAI_TEMPERATURE": (ConfigKeys.OPENAI_TEMPERATURE, float),
            "BOT_SYSTEM_PROMPT": (ConfigKeys.BOT_SYSTEM_PROMPT, str),
            "BOT_AUTO_POST_ENABLED": (ConfigKeys.BOT_AUTO_POST_ENABLED, bool),
            "BOT_AUTO_POST_INTERVAL": (ConfigKeys.BOT_AUTO_POST_INTERVAL, int),
            "BOT_AUTO_POST_MAX_PER_DAY": (ConfigKeys.BOT_AUTO_POST_MAX_PER_DAY, int),
            "BOT_AUTO_POST_VISIBILITY": (ConfigKeys.BOT_AUTO_POST_VISIBILITY, str),
            "BOT_AUTO_POST_PROMPT": (ConfigKeys.BOT_AUTO_POST_PROMPT, str),
            "BOT_RESPONSE_MENTION_ENABLED": (
                ConfigKeys.BOT_RESPONSE_MENTION_ENABLED,
                bool,
            ),
            "BOT_RESPONSE_CHAT_ENABLED": (ConfigKeys.BOT_RESPONSE_CHAT_ENABLED, bool),
            "BOT_RESPONSE_CHAT_MEMORY": (ConfigKeys.BOT_RESPONSE_CHAT_MEMORY, int),
            "DB_PATH": (ConfigKeys.DB_PATH, str),
            # "DB_CLEANUP_DAYS": (ConfigKeys.DB_CLEANUP_DAYS, int),
            "LOG_PATH": (ConfigKeys.LOG_PATH, str),
            "LOG_LEVEL": (ConfigKeys.LOG_LEVEL, str),
        }
        for env_key, (config_path, value_type) in env_mappings.items():
            if env_value := os.environ.get(env_key):
                self._set_config_value(config_path, env_value, value_type)

    def _set_config_value(self, path: str, value: str, value_type: type) -> None:
        keys = path.split(".")
        config = self.config
        for key in keys[:-1]:
            config = config.setdefault(key, {})
        converters = {
            bool: lambda v: v.lower() in ("true", "yes"),
            int: int,
            float: float,
        }
        config[keys[-1]] = converters.get(
            value_type, lambda v: self._process_string_value(v, path)
        )(value)

    def _process_string_value(self, value: Any, config_path: str) -> str:
        if not isinstance(value, str):
            return value
        if value.startswith("file://"):
            return self._load_from_file(value[7:])
        if self._is_prompt_config(config_path) and self._looks_like_file_path(value):
            return self._load_from_file(value)
        return value

    def _load_from_file(self, file_path: str) -> str:
        try:
            path = Path(file_path)
            if not path.is_absolute():
                path = Path(self.config_path).parent / path
            with open(path, "r", encoding="utf-8") as f:
                content = f.read().strip()
                logger.debug(f"从文件加载配置: {file_path}")
                return content
        except (OSError, UnicodeDecodeError) as e:
            logger.debug(f"无法从文件加载配置 {file_path}，使用原始值: {e}")
            return file_path

    def _looks_like_file_path(self, value: str) -> bool:
        return len(value) <= 200 and (value.endswith(".txt") or "prompts" in value)

    def _is_prompt_config(self, config_path: str) -> bool:
        prompt_configs = [ConfigKeys.BOT_SYSTEM_PROMPT, ConfigKeys.BOT_AUTO_POST_PROMPT]
        return config_path in prompt_configs

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return reduce(lambda d, k: d[k], key.split("."), self.config)
        except (KeyError, TypeError) as e:
            builtin_default = self._get_builtin_default(key)
            if default is not None:
                return default
            if builtin_default is not None:
                return builtin_default
            logger.error(f"配置文件格式错误: {e}")
            return None

    def _get_builtin_default(self, key: str) -> Any:
        builtin_defaults = {
            ConfigKeys.MISSKEY_INSTANCE_URL: None,
            ConfigKeys.MISSKEY_ACCESS_TOKEN: None,
            ConfigKeys.OPENAI_API_KEY: None,
            ConfigKeys.OPENAI_MODEL: "deepseek-chat",
            ConfigKeys.OPENAI_API_BASE: "https://api.deepseek.com/v1",
            ConfigKeys.OPENAI_MAX_TOKENS: 1000,
            ConfigKeys.OPENAI_TEMPERATURE: 0.8,
            ConfigKeys.BOT_SYSTEM_PROMPT: None,
            ConfigKeys.BOT_AUTO_POST_ENABLED: True,
            ConfigKeys.BOT_AUTO_POST_INTERVAL: 180,
            ConfigKeys.BOT_AUTO_POST_MAX_PER_DAY: 8,
            ConfigKeys.BOT_AUTO_POST_VISIBILITY: "public",
            ConfigKeys.BOT_AUTO_POST_PROMPT: None,
            ConfigKeys.BOT_RESPONSE_MENTION_ENABLED: True,
            ConfigKeys.BOT_RESPONSE_CHAT_ENABLED: True,
            ConfigKeys.BOT_RESPONSE_CHAT_MEMORY: 10,
            ConfigKeys.DB_PATH: "data/misskey_ai.db",
            # ConfigKeys.DB_CLEANUP_DAYS: 30,
            ConfigKeys.LOG_PATH: "logs/misskey_ai.log",
            ConfigKeys.LOG_LEVEL: "INFO",
        }
        return builtin_defaults.get(key)

    def _validate_config(self) -> None:
        self._validate_required_configs()
        self._validate_file_paths()
        logger.debug("配置验证完成")

    def _validate_required_configs(self) -> None:
        required_configs = [
            (ConfigKeys.MISSKEY_INSTANCE_URL, "Misskey 实例 URL"),
            (ConfigKeys.MISSKEY_ACCESS_TOKEN, "Misskey 访问令牌"),
            (ConfigKeys.OPENAI_API_KEY, "OpenAI API 密钥"),
            (ConfigKeys.OPENAI_MODEL, "OpenAI 模型名称"),
            (ConfigKeys.OPENAI_API_BASE, "OpenAI API 端点"),
        ]
        for config_key, desc in required_configs:
            value = self.get(config_key)
            if not value or (isinstance(value, str) and not value.strip()):
                raise ConfigurationError(f"缺少必要配置项: {desc}")

    def _validate_file_paths(self) -> None:
        paths = [
            (self.get(ConfigKeys.DB_PATH), "数据库目录"),
            (self.get(ConfigKeys.LOG_PATH), "日志目录"),
        ]
        for path, desc in paths:
            if path:
                try:
                    Path(path).parent.mkdir(parents=True, exist_ok=True)
                except OSError as e:
                    logger.error(f"创建{desc}失败 {path}: {e}")
                    raise ConfigurationError(f"无法创建{desc}: {path}") from e
