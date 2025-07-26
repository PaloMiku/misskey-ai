#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Callable, Awaitable, Union


class IUtilsProvider(ABC):
    @abstractmethod
    def extract_username(self, user_data: Dict[str, Any]) -> str:
        pass

    @abstractmethod
    def extract_user_id(self, user_data: Dict[str, Any]) -> str:
        pass


class IPersistenceManager(ABC):
    @abstractmethod
    async def initialize(self) -> None:
        pass

    @abstractmethod
    async def close(self) -> None:
        pass

    @abstractmethod
    async def save_mention(self, mention_data: Dict[str, Any]) -> None:
        pass

    @abstractmethod
    async def save_message(self, message_data: Dict[str, Any]) -> None:
        pass


class IConfigProvider(ABC):
    @abstractmethod
    def get(self, key: str, default: Any = None) -> Any:
        pass

    @abstractmethod
    def get_typed(
        self, key: str, default: Any = None, expected_type: type = None
    ) -> Any:
        pass


class IValidator(ABC):
    @abstractmethod
    def validate_string(
        self, value: Any, param_name: str, min_length: int = 0, max_length: int = None
    ) -> str:
        pass

    @abstractmethod
    def validate_numeric(
        self,
        value: Any,
        param_name: str,
        min_value: Union[int, float] = None,
        max_value: Union[int, float] = None,
    ) -> Union[int, float]:
        pass

    @abstractmethod
    def validate_url(self, value: Any, param_name: str) -> str:
        pass

    @abstractmethod
    def validate_api_key(self, value: Any, param_name: str) -> str:
        pass

    @abstractmethod
    def validate_access_token(self, value: Any, param_name: str) -> str:
        pass

    @abstractmethod
    def log_validation_error(self, error: Exception, context: str = "") -> None:
        pass


class IAPIClient(ABC):
    @abstractmethod
    async def close(self) -> None:
        pass

    @abstractmethod
    async def request(
        self, endpoint: str, data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        pass


class IStreamingClient(ABC):
    @abstractmethod
    async def connect(self, channels: Optional[list] = None) -> None:
        pass

    @abstractmethod
    async def close(self) -> None:
        pass

    @abstractmethod
    def on_mention(self, handler: Callable[[Dict[str, Any]], Awaitable[None]]) -> None:
        pass

    @abstractmethod
    def on_message(self, handler: Callable[[Dict[str, Any]], Any]) -> None:
        pass

    @abstractmethod
    def is_connected(self) -> bool:
        pass


class ITextGenerator(ABC):
    @abstractmethod
    async def generate_text(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_tokens: int = 1000,
        temperature: float = 0.8,
    ) -> str:
        pass

    @abstractmethod
    async def close(self) -> None:
        pass


class IPlugin(ABC):
    @abstractmethod
    async def initialize(self) -> bool:
        pass

    @abstractmethod
    async def cleanup(self) -> None:
        pass

    @abstractmethod
    def get_info(self) -> Dict[str, Any]:
        pass
