import sys
import aiohttp
from typing import Optional, Any
from loguru import logger
from .constants import API_TIMEOUT, WS_TIMEOUT
from .exceptions import ClientConnectorError

__all__ = ("HTTPClient", "HTTPSession")


class HTTPClient:
    def __init__(self) -> None:
        self.__session: Optional[aiohttp.ClientSession] = None
        self.__connector: Optional[aiohttp.TCPConnector] = None
        self.token: Optional[str] = None
        user_agent = "MisskeyBot/1.0 Python/{0[0]}.{0[1]} aiohttp/{1}"
        self.user_agent = user_agent.format(sys.version_info, aiohttp.__version__)
        self._default_headers = {
            "Content-Type": "application/json",
            "User-Agent": self.user_agent,
        }

    @property
    def _connector(self) -> aiohttp.TCPConnector:
        if self.__connector is None or self.__connector.closed:
            self.__connector = aiohttp.TCPConnector(
                limit=100,
                limit_per_host=30,
                ttl_dns_cache=300,
                use_dns_cache=True,
                keepalive_timeout=30,
                enable_cleanup_closed=True,
            )
        return self.__connector

    @property
    def session(self) -> aiohttp.ClientSession:
        if self.__session is None or self.__session.closed:
            self.__session = aiohttp.ClientSession(
                headers=self._default_headers,
                timeout=aiohttp.ClientTimeout(total=API_TIMEOUT, connect=10),
                connector=self._connector,
                connector_owner=False,
            )
        return self.__session

    async def close_session(self):
        if self.__session and not self.__session.closed:
            await self.__session.close()
            self.__session = None
        if self.__connector and not self.__connector.closed:
            await self.__connector.close()
            self.__connector = None
        logger.debug("HTTP 会话已关闭")

    async def ws_connect(self, url: str, *, compress: int = 0) -> Any:
        kwargs = {
            "autoclose": False,
            "max_msg_size": 0,
            "timeout": WS_TIMEOUT,
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
