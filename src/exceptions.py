class MisskeyBotError(Exception):
    pass


class ConfigurationError(MisskeyBotError):
    pass


class AuthenticationError(MisskeyBotError):
    pass


class APIConnectionError(MisskeyBotError):
    pass


class WebSocketConnectionError(MisskeyBotError):
    pass


class WebSocketReconnectError(WebSocketConnectionError):
    pass


class APIRateLimitError(MisskeyBotError):
    pass
