__all__ = (
    "MisskeyBotError",
    "ConfigurationError",
    "AuthenticationError",
    "APIConnectionError",
    "APIRateLimitError",
    "APIBadRequestError",
    "WebSocketConnectionError",
    "WebSocketReconnectError",
    "ClientConnectorError",
)


class MisskeyBotError(Exception):
    """基础错误"""


class ConfigurationError(MisskeyBotError):
    """配置错误"""


class AuthenticationError(MisskeyBotError):
    """身份验证错误"""


class APIConnectionError(MisskeyBotError):
    """API 连接错误"""


class APIRateLimitError(MisskeyBotError):
    """API 速率限制错误"""


class APIBadRequestError(MisskeyBotError):
    """API 请求错误"""


class WebSocketConnectionError(MisskeyBotError):
    """WebSocket 连接错误"""


class WebSocketReconnectError(WebSocketConnectionError):
    """WebSocket 重连错误"""


class ClientConnectorError(MisskeyBotError):
    """TCP 客户端连接器错误"""
