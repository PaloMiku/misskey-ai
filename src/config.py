#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
from pathlib import Path
from typing import Any, Dict, Optional, TypeVar

import yaml
from loguru import logger

from .exceptions import ConfigurationError
from .interfaces import IConfigProvider
from .constants import ConfigKeys

T = TypeVar("T")


class Config(IConfigProvider):
    def __init__(self, config_path: Optional[str] = None):
        self.config_path = config_path or os.environ.get("CONFIG_PATH", "config.yaml")
        self.config: Dict[str, Any] = {}

    async def load(self) -> None:
        config_path = Path(self.config_path)
        if not config_path.exists():
            logger.error(f"配置文件不存在: {config_path}")
            raise ConfigurationError(f"配置文件不存在: {config_path}")
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                self.config = yaml.safe_load(f)
            logger.debug(f"已加载配置文件: {config_path}")
            self._override_from_env()
            self._validate_config()
        except yaml.YAMLError as e:
            logger.error(f"配置文件格式错误: {e}")
            raise ConfigurationError(f"配置文件格式错误: {e}")
        except FileNotFoundError as e:
            logger.error(f"配置文件不存在: {e}")
            raise ConfigurationError(f"配置文件不存在: {e}")
        except PermissionError as e:
            logger.error(f"配置文件权限不足: {e}")
            raise ConfigurationError(f"配置文件权限不足: {e}")
        except (OSError, IOError) as e:
            logger.error(f"配置文件读取错误: {e}")
            raise ConfigurationError(f"配置文件读取错误: {e}")
        except (ValueError, TypeError, AttributeError) as e:
            logger.error(f"加载配置文件未知错误: {e}")
            raise ConfigurationError(f"加载配置文件未知错误: {e}")

    def _override_from_env(self) -> None:
        env_mappings = {
            "MISSKEY_INSTANCE_URL": (ConfigKeys.MISSKEY_INSTANCE_URL, str),
            "MISSKEY_ACCESS_TOKEN": (ConfigKeys.MISSKEY_ACCESS_TOKEN, str),
            "DEEPSEEK_API_KEY": (ConfigKeys.DEEPSEEK_API_KEY, str),
            "DEEPSEEK_MODEL": (ConfigKeys.DEEPSEEK_MODEL, str),
            "DEEPSEEK_API_BASE": (ConfigKeys.DEEPSEEK_API_BASE, str),
            "DEEPSEEK_MAX_TOKENS": (ConfigKeys.DEEPSEEK_MAX_TOKENS, int),
            "DEEPSEEK_TEMPERATURE": (ConfigKeys.DEEPSEEK_TEMPERATURE, float),
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
            "BOT_RESPONSE_POLLING_INTERVAL": (
                ConfigKeys.BOT_RESPONSE_POLLING_INTERVAL,
                int,
            ),
            "DB_PATH": (ConfigKeys.DB_PATH, str),
            "DB_CLEANUP_DAYS": (ConfigKeys.DB_CLEANUP_DAYS, int),
            "LOG_PATH": (ConfigKeys.LOG_PATH, str),
            "LOG_LEVEL": (ConfigKeys.LOG_LEVEL, str),
        }
        for env_key, (config_path, value_type) in env_mappings.items():
            env_value = os.environ.get(env_key)
            if env_value:
                self._set_config_value(config_path, env_value, value_type)

    def _set_config_value(self, path: str, value: str, value_type: type) -> None:
        keys = path.split(".")
        config = self.config
        for key in keys[:-1]:
            config = config.setdefault(key, {})
        if value_type is bool:
            config[keys[-1]] = value.lower() in ("true", "yes")
        elif value_type is int:
            config[keys[-1]] = int(value)
        elif value_type is float:
            config[keys[-1]] = float(value)
        else:
            config[keys[-1]] = self._process_string_value(value, path)

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
        except (OSError, IOError, ValueError, UnicodeDecodeError) as e:
            logger.debug(f"无法从文件加载配置 {file_path}: {e}，使用原始值")
            return file_path

    def _looks_like_file_path(self, value: str) -> bool:
        if len(value) > 200:
            return False
        file_indicators = [".txt"]
        if any(value.endswith(ext) for ext in file_indicators):
            return True
        path_indicators = ["prompts"]
        return any(indicator in value for indicator in path_indicators)

    def _is_prompt_config(self, config_path: str) -> bool:
        prompt_configs = [ConfigKeys.BOT_SYSTEM_PROMPT, ConfigKeys.BOT_AUTO_POST_PROMPT]
        return config_path in prompt_configs

    def get(self, key: str, default: Any = None) -> Any:
        keys = key.split(".")
        value = self.config
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                if default is None:
                    default = self._get_builtin_default(key)
                return default
        return value

    def _get_builtin_default(self, key: str) -> Any:
        builtin_defaults = {
            ConfigKeys.MISSKEY_INSTANCE_URL: None,
            ConfigKeys.MISSKEY_ACCESS_TOKEN: None,
            ConfigKeys.DEEPSEEK_API_KEY: None,
            ConfigKeys.DEEPSEEK_MODEL: "deepseek-chat",
            ConfigKeys.DEEPSEEK_API_BASE: "https://api.deepseek.com/v1",
            ConfigKeys.DEEPSEEK_MAX_TOKENS: 1000,
            ConfigKeys.DEEPSEEK_TEMPERATURE: 0.8,
            ConfigKeys.BOT_SYSTEM_PROMPT: None,
            ConfigKeys.BOT_AUTO_POST_ENABLED: True,
            ConfigKeys.BOT_AUTO_POST_INTERVAL: 180,
            ConfigKeys.BOT_AUTO_POST_MAX_PER_DAY: 8,
            ConfigKeys.BOT_AUTO_POST_VISIBILITY: "public",
            ConfigKeys.BOT_AUTO_POST_PROMPT: None,
            ConfigKeys.BOT_RESPONSE_MENTION_ENABLED: True,
            ConfigKeys.BOT_RESPONSE_CHAT_ENABLED: True,
            ConfigKeys.BOT_RESPONSE_CHAT_MEMORY: 10,
            ConfigKeys.BOT_RESPONSE_POLLING_INTERVAL: 60,
            ConfigKeys.DB_PATH: "data/misskey_ai.db",
            ConfigKeys.DB_CLEANUP_DAYS: 30,
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
            (ConfigKeys.DEEPSEEK_API_KEY, "DeepSeek API 密钥"),
            (ConfigKeys.DEEPSEEK_MODEL, "DeepSeek 模型名称"),
            (ConfigKeys.DEEPSEEK_API_BASE, "DeepSeek API 基础 URL"),
        ]
        for config_key, display_name in required_configs:
            value = self.get(config_key)
            if not value or (isinstance(value, str) and not value.strip()):
                raise ConfigurationError(
                    f"缺少必需配置项: {display_name} ({config_key})"
                )

    def _validate_file_paths(self) -> None:
        db_path = self.get(ConfigKeys.DB_PATH)
        if db_path:
            db_dir = Path(db_path).parent
            try:
                db_dir.mkdir(parents=True, exist_ok=True)
            except (OSError, PermissionError) as e:
                raise ConfigurationError(f"无法创建数据库目录 {db_dir}: {e}")
        log_path = self.get(ConfigKeys.LOG_PATH)
        if log_path:
            log_dir = Path(log_path).parent
            try:
                log_dir.mkdir(parents=True, exist_ok=True)
            except (OSError, PermissionError) as e:
                raise ConfigurationError(f"无法创建日志目录 {log_dir}: {e}")

    def get_typed(self, key: str, default: T = None, expected_type: type = None) -> T:
        value = self.get(key, default)
        if expected_type and value is not None and not isinstance(value, expected_type):
            raise ValueError(
                f"配置项 {key} 期望类型 {expected_type.__name__}，实际类型 {type(value).__name__}"
            )
        return value
