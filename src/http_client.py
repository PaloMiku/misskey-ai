import sys
import aiohttp
from typing import Optional, Any
from loguru import logger
from .constants import API_TIMEOUT
from .exceptions import ClientConnectorError

__all__ = ("HTTPClient", "HTTPSession")


class HTTPClient:
    def __init__(self) -> None:
        self.__session: Optional[aiohttp.ClientSession] = None
        self.token: Optional[str] = None
        user_agent = "MisskeyBot/1.0 Python/{0[0]}.{0[1]} aiohttp/{1}"
        self.user_agent = user_agent.format(sys.version_info, aiohttp.__version__)
        self._default_headers = {
            "Content-Type": "application/json",
            "User-Agent": self.user_agent,
        }

    @property
    def session(self) -> aiohttp.ClientSession:
        if self.__session is None or self.__session.closed:
            self.__session = aiohttp.ClientSession(
                headers=self._default_headers,
                timeout=aiohttp.ClientTimeout(total=API_TIMEOUT),
            )
        return self.__session

    async def close_session(self):
        if self.__session and not self.__session.closed:
            await self.__session.close()
            self.__session = None
            logger.debug("HTTP 会话已关闭")

    async def ws_connect(self, url: str, *, compress: int = 0) -> Any:
        kwargs = {
            "autoclose": False,
            "max_msg_size": 0,
            "timeout": 30.0,
            "headers": {"User-Agent": self.user_agent},
            "compress": compress,
        }
        try:
            ws = await self.session.ws_connect(url, **kwargs)
        except aiohttp.client_exceptions.ClientConnectorError as e:
            logger.error(f"HTTP 客户端连接失败: {e}")
            raise ClientConnectorError()
        return ws

    def set_token(self, token: str):
        self.token = token


HTTPSession: HTTPClient = HTTPClient()
