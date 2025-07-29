class MisskeyBotError(Exception):
    def __init__(self, message: str = None):
        self.message = message or "发生了未知错误"
        super().__init__(self.message)


class ConfigurationError(MisskeyBotError):
    def __init__(self, message: str = None, config_path: str = None):
        self.config_path = config_path
        error_msg = (
            f"配置错误 ({config_path}): {message or '配置文件存在问题'}"
            if config_path
            else (message or "配置文件存在问题")
        )
        super().__init__(error_msg)


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
        error_msg = message or "WebSocket 连接失败"
        super().__init__(error_msg)


class APIRateLimitError(MisskeyBotError):
    def __init__(self, service_name: str, retry_after: int = None):
        self.service_name = service_name
        self.retry_after = retry_after
        super().__init__(
            f"{service_name} API 速率限制{f'，请在{retry_after}秒后重试' if retry_after else ''}"
        )
