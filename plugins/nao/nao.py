import re
import aiohttp
from typing import Dict, Any, Optional
from loguru import logger
from src.plugin_base import PluginBase

class NaoImageSearch(PluginBase):
    description = "使用 SauceNAO 搜索图片来源，支持识别二次元图片、动漫截图等"

    def __init__(self, context):
        super().__init__(context)
        self.api_key = self.config.get("api_key")
        self.trigger_tag = self.config.get("trigger_tag", "#nao")
        self.session = None
        self.saucenao_api_url = "https://saucenao.com/search.php"

    async def initialize(self) -> bool:
        if not self.api_key:
            logger.warning("NaoImageSearch: 未设置 API 密钥，将使用免费额度")
        self.session = aiohttp.ClientSession()
        self._register_resource(self.session, "close")
        self._log_plugin_action("初始化完成", f"API密钥: {'已设置' if self.api_key else '未设置'}")
        return True

    async def cleanup(self) -> None:
        """清理资源"""
        await super().cleanup()

    def _note(self, data):
        return data.get("note", data)

    def _extract_images(self, data):
        images = []
        for f in self._note(data).get("files", []):
            if not isinstance(f, dict):
                continue
            if not (f.get("type", "") or "").startswith("image/"):
                continue
            url = f.get("url") or f.get("thumbnailUrl")
            if url:
                images.append(url)
        return images

    def _should_trigger(self, data) -> bool:
        text = self._note(data).get("text", "") or ""
        if self.trigger_tag not in text:
            return False
        cleaned = re.sub(r'@\w+(?:@[\w.-]+)?', '', text).replace(self.trigger_tag, "").strip()
        return cleaned == ""  # 只有去掉 mention 和触发标签后为空才触发

    async def on_mention(self, data):
        return await self._handle_image_search_event(data, "处理 @mention")

    async def on_message(self, data):
        return await self._handle_image_search_event(data, "处理消息")

    async def _handle_image_search_event(self, data: Dict[str, Any], action_desc: str) -> Optional[Dict[str, Any]]:
        try:
            images = self._extract_images(data)
            if not images or not self._should_trigger(data):
                return None
            username = self._extract_username(data)
            self._log_plugin_action(action_desc, f"来自 @{username}")
            return self._create_response(await self._search(images[0]) or "没有找到相似的图片哦～")
        except Exception as e:
            logger.error(f"NaoImageSearch 处理图片事件出错: {e}")
            return None

    async def _search(self, url: str) -> Optional[str]:
        try:
            params = {
                "output_type": "2",
                "url": url,
                "numres": "3",
                "db": "999",
                **({"api_key": self.api_key} if self.api_key else {})
            }
            created = False
            session = self.session
            if session is None:
                session = aiohttp.ClientSession()
                created = True
            try:
                async with session.get(self.saucenao_api_url, params=params) as r:
                    if r.status != 200:
                        logger.error(f"SauceNAO API 请求失败: {r.status}")
                        return None
                    return self._format(await r.json())
            finally:
                if created:
                    await session.close()
        except Exception as e:
            logger.error(f"SauceNAO 图片搜索失败: {e}")
            return None

    def _format(self, payload: Dict[str, Any]) -> Optional[str]:
        try:
            results = payload.get("results")
            if not results:
                return None
            first = results[0]
            h = first.get("header", {})
            d = first.get("data", {})
            title = d.get("title") or d.get("jp_name") or d.get("eng_name") or d.get("source") or "未知"
            author = d.get("author") or d.get("member_name") or d.get("creator") or "未知"
            src = (d.get("ext_urls") or [None])[0] or ""
            lines = [
                f"🔍 相似度: {h.get('similarity', 0)}%",
                f"📝 标题: {title}",
                f"👤 作者: {author}",
            ]
            if src:
                lines.append(f"🔗 来源: {src}")
            if index := h.get("index_name"):
                lines.append(f"📚 数据库: {index}")
            return "\n".join(lines)
        except Exception as e:
            logger.error(f"解析 SauceNAO 响应失败: {e}")
            return None

    def _create_response(self, response_text: str, content_key: str = "response") -> Optional[Dict[str, Any]]:
        """创建插件响应"""
        try:
            response = {
                "handled": True,
                "plugin_name": self.name,
                content_key: response_text,
            }
            return response if self._validate_plugin_response(response) else None
        except Exception as e:
            logger.error(f"创建响应时出错: {e}")
            return None