class MisskeyBotError(Exception):
    def __init__(self, message: str = None):
        super().__init__(message or "发生了未知错误")


class ConfigurationError(MisskeyBotError):
    def __init__(self, message: str = None, config_path: str = None):
        self.config_path = config_path
        msg = message or "配置文件存在问题"
        super().__init__(f"配置错误 ({config_path}): {msg}" if config_path else msg)


class AuthenticationError(MisskeyBotError):
    def __init__(self, service_name: str):
        self.service_name = service_name
        super().__init__(f"{service_name} 认证失败，请检查 API 密钥")


class APIConnectionError(MisskeyBotError):
    def __init__(self, service_name: str, message: str = None):
        self.service_name = service_name
        super().__init__(
            f"{service_name} API 连接失败{': ' + message if message else ''}"
        )


class WebSocketConnectionError(MisskeyBotError):
    def __init__(self, message: str = None, reconnect_attempts: int = None):
        self.reconnect_attempts = reconnect_attempts
        super().__init__(message or "WebSocket 连接失败")


class APIRateLimitError(MisskeyBotError):
    def __init__(self, service_name: str, retry_after: int = None):
        self.service_name = service_name
        self.retry_after = retry_after
        super().__init__(f"{service_name} API 速率限制")
