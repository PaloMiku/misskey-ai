from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Callable, Awaitable

__all__ = (
    "IConfigProvider",
    "IAPIClient",
    "IStreamingClient",
    "ITextGenerator",
    "IPlugin",
)


class IConfigProvider(ABC):
    @abstractmethod
    def get(self, key: str, default: Any = None) -> Any:
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
    async def connect(self, channels: Optional[list[str]] = None) -> None:
        pass

    @abstractmethod
    async def close(self) -> None:
        pass

    @abstractmethod
    def on_mention(self, handler: Callable[[Dict[str, Any]], Awaitable[None]]) -> None:
        pass

    @abstractmethod
    def on_message(self, handler: Callable[[Dict[str, Any]], Awaitable[None]]) -> None:
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
