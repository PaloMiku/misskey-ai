__all__ = (
    "MisskeyBotError",
    "ConfigurationError",
    "AuthenticationError",
    "APIConnectionError",
    "APIRateLimitError",
    "WebSocketConnectionError",
    "WebSocketReconnectError",
    "ClientConnectorError",
)


class MisskeyBotError(Exception):
    """Base exception for all Misskey bot errors"""


class ConfigurationError(MisskeyBotError):
    """Configuration related errors"""


class AuthenticationError(MisskeyBotError):
    """Authentication related errors"""


class APIConnectionError(MisskeyBotError):
    """API connection related errors"""


class APIRateLimitError(MisskeyBotError):
    """API rate limit errors"""


class WebSocketConnectionError(MisskeyBotError):
    """WebSocket connection errors"""


class WebSocketReconnectError(WebSocketConnectionError):
    """WebSocket reconnection errors"""


class ClientConnectorError(MisskeyBotError):
    """Client connector errors"""
