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
            if self.__connector is not None:
                try:
                    if not self.__connector.closed:
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
            if self.__session is not None and not self.__session.closed:
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

    async def close_session(self):
        errors = []
        if self.__session:
            try:
                if not self.__session.closed:
                    await self.__session.close()
            except (OSError, RuntimeError, aiohttp.ClientError) as e:
                errors.append(f"关闭会话时出错: {e}")
            finally:
                self.__session = None
        if self.__connector:
            try:
                if not self.__connector.closed:
                    await self.__connector.close()
            except (OSError, RuntimeError) as e:
                errors.append(f"关闭连接器时出错: {e}")
            finally:
                self.__connector = None
        if errors:
            for error in errors:
                logger.warning(error)
        logger.debug("HTTP 会话已关闭")

    async def ws_connect(self, url: str, *, compress: int = 0) -> Any:
        kwargs = {
            "autoclose": True,
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
