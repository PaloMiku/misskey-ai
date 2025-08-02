import sys
import asyncio
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
            if self.__connector and not self.__connector.closed:
                try:
                    self.__connector.close()
                except (OSError, RuntimeError):
                    pass
            self.__connector = aiohttp.TCPConnector(
                enable_cleanup_closed=True,
                force_close=True,
            )
        return self.__connector

    @property
    def session(self) -> aiohttp.ClientSession:
        if self.__session is None or self.__session.closed:
            if self.__session and not self.__session.closed:
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        loop.create_task(self.__session.close())
                    else:
                        loop.run_until_complete(self.__session.close())
                except (OSError, RuntimeError, asyncio.InvalidStateError):
                    pass
            self.__session = aiohttp.ClientSession(
                headers=self._default_headers,
                timeout=aiohttp.ClientTimeout(total=API_TIMEOUT, connect=10),
                connector=self._connector,
                connector_owner=True,
            )
        return self.__session

    async def close_session(self) -> None:
        async def safe_close(resource, name, exceptions=(OSError, RuntimeError)):
            if resource and not resource.closed:
                try:
                    await resource.close()
                except exceptions as e:
                    logger.warning(f"关闭{name}时出错: {e}")

        await safe_close(
            self.__session, "会话", (OSError, RuntimeError, aiohttp.ClientError)
        )
        await safe_close(self.__connector, "连接器")
        self.__session = self.__connector = None
        logger.debug("HTTP 会话已关闭")

    async def ws_connect(self, url: str, *, compress: int = 0) -> Any:
        try:
            return await self.session.ws_connect(
                url,
                autoclose=True,
                max_msg_size=0,
                timeout=WS_TIMEOUT,
                headers={"User-Agent": self.user_agent},
                compress=compress,
            )
        except aiohttp.ClientConnectorError as e:
            logger.error(f"HTTP 客户端连接失败: {e}")
            raise ClientConnectorError()

    def set_token(self, token: str) -> None:
        self.token = token


HTTPSession: HTTPClient = HTTPClient()
