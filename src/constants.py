HTTP_OK = 200
HTTP_UNAUTHORIZED = 401
HTTP_FORBIDDEN = 403
HTTP_TOO_MANY_REQUESTS = 429
HTTP_INTERNAL_SERVER_ERROR = 500
HTTP_BAD_GATEWAY = 502
HTTP_SERVICE_UNAVAILABLE = 503
HTTP_GATEWAY_TIMEOUT = 504

RETRYABLE_HTTP_CODES = {
    HTTP_TOO_MANY_REQUESTS,
    HTTP_INTERNAL_SERVER_ERROR,
    HTTP_BAD_GATEWAY,
    HTTP_SERVICE_UNAVAILABLE,
    HTTP_GATEWAY_TIMEOUT,
}

API_TIMEOUT = 60
API_MAX_RETRIES = 3

WS_HEARTBEAT_INTERVAL = 60
WS_RECONNECT_DELAY = 5
WS_MAX_RECONNECT_ATTEMPTS = 5
WS_MAX_RECONNECT_DELAY = 300.0

MAX_PROCESSED_ITEMS_CACHE = 500

ERROR_MESSAGES = {
    "MisskeyBotError": "抱歉，出现未知问题，请联系管理员。",
    "APIRateLimitError": "抱歉，请求过于频繁，请稍后再试。",
    "AuthenticationError": "抱歉，服务配置有误，请联系管理员。",
    "APIConnectionError": "抱歉，AI 服务暂不可用，请稍后再试。",
    "WebSocketConnectionError": "抱歉，WebSocket 连接失败，将使用轮询模式。",
    "ValueError": "抱歉，请求参数无效，请检查输入。",
    "RuntimeError": "抱歉，系统资源不足，请稍后再试。",
}
DEFAULT_ERROR_MESSAGE = "抱歉，处理您的消息时出现了错误。"
