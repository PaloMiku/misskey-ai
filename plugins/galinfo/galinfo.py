import os
import aiohttp
from typing import Dict, Any
from src.plugin_base import PluginBase
from src.plugin_manager import PluginCommand, PluginContext



class APIYm:
    def __init__(self):
        self.api = "https://www.ymgal.games"
        self.cid = "ymgal"
        self.c_secret = "luna0327"

    async def get_token(self):
        tapi = f"{self.api}/oauth/token?"
        data = {
            "grant_type": "client_credentials",
            "client_id": self.cid,
            "client_secret": self.c_secret,
            "scope": "public"
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(tapi, data=data) as response:
                token = (await response.json())["access_token"]
                return token

    async def header(self, token):
        return {
            "Accept": "application/json;charset=utf-8",
            "Authorization": f"Bearer {token}",
            "version": "1",
        }

    async def search_game(self, header, keyword: str, similarity: int) -> Dict[str, Any]:
        from urllib.parse import quote
        keyword = quote(keyword)
        url = f"{self.api}/open/archive/search-game?mode=accurate&keyword={keyword}&similarity={similarity}"
        async with aiohttp.ClientSession(headers=header) as session:
            async with session.get(url) as response:
                res = await response.json()
                code = res["code"]
                if code == 0:
                    gamedata = res.get("data", {}).get("game", {})
                    result = {
                        "id": gamedata.get("gid", None),
                        "oaid": gamedata.get("developerId", None),
                        "mainimg": gamedata.get("mainImg", "None"),
                        "name": gamedata.get("name", "None"),
                        "rd": gamedata.get("releaseDate", "None"),
                        "rest": gamedata.get("restricted", "None"),
                        "hc": gamedata.get("haveChinese", False),
                        "cnname": gamedata.get("chineseName", "None"),
                        "intro": gamedata.get("introduction", "None")
                    }
                elif code == 614:
                    raise Exception("参数错误，可能是根据关键词搜索不到游戏档案\n在使用游戏简称、汉化名、外号等关键字无法查询到目标内容时，请使用游戏原名（全名+标点+大小写无误）再次尝试，或者使用模糊查找")
                else:
                    raise Exception(f"返回错误，返回码code:{code}")
        return result

    async def vague_search_game(self, header, keyword: str, pageNum=1, pageSize=10) -> str:
        from urllib.parse import quote
        keyword = quote(keyword)
        url = f"{self.api}/open/archive/search-game?mode=list&keyword={keyword}&pageNum={pageNum}&pageSize={pageSize}"
        async with aiohttp.ClientSession(headers=header) as session:
            async with session.get(url) as response:
                res = await response.json()
                code = res.get("code")
                if code == 0:
                    result = res.get("data", {}).get("result", {})
                    if result:
                        s_keyword = result[0].get("name", None)
                    else:
                        raise Exception("模糊搜索无结果，请尝试更改关键词")
                else:
                    raise Exception(f"返回错误，返回码code:{code}")
        return s_keyword

    def info_list(self, info: dict[str, Any]):
        import re
        parg = (info.get("intro") or "").split("\n")
        if len(parg) < 2:
            parg = (info.get("intro") or "").split("\n\n")
        pargs = []
        for p in parg:
            pattern = r"\s+"
            clean_p = f"{'':<7}{re.sub(pattern, '', p.strip())}"
            pargs.append(clean_p)
        intro = "\n".join(pargs)
        chain = (
            f"游戏名：{info.get('name')}（{info.get('cnname')}）\n"
            f"限制级：{'是' if info.get('rest') else '否'}\n"
            f"是否已有汉化：{'是' if info.get('hc') else '否'}\n"
            f"简介：\n{intro}"
        )
        return chain

class GalinfoPlugin(PluginBase):
    name = "galinfo"
    description = "提供Galgame信息查询，基于月幕Gal的api"
    version = "1.0"

    def __init__(self, context: PluginContext):
        super().__init__(context)
        self.ym = APIYm()
        # 标签从 config.yaml 读取，默认 #galgame
        self.trigger_tag = context.config.get('gal_tag', '#galgame')

    async def on_message(self, message_data: dict) -> dict | None:
        """
        兼容misskey-ai插件基类和manager，参数为message_data字典，返回标准响应。
        """
        text = message_data.get('text', '')
        if self.trigger_tag in text:
            keyword = text.replace(self.trigger_tag, '').strip()
            if not keyword:
                return {
                    "handled": True,
                    "plugin_name": self.name,
                    "response": "请在标签后输入要查询的游戏名"
                }
            try:
                token = await self.ym.get_token()
                header = await self.ym.header(token)
                gal = await self.ym.vague_search_game(header, keyword)
                info = await self.ym.search_game(header, gal, 100)
                chains = self.ym.info_list(info)
                return {
                    "handled": True,
                    "plugin_name": self.name,
                    "response": f"已匹配最符合的一条：{gal}\n{chains}"
                }
            except Exception as e:
                return {
                    "handled": True,
                    "plugin_name": self.name,
                    "response": f"查询失败：{e}"
                }
        return None




