#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
import io
import aiohttp
from typing import Dict, Any, Optional
from PIL import Image, ImageEnhance

from loguru import logger

from src.plugin_base import PluginBase


class AsciiArtPlugin(PluginBase):
    description = "将图片转换为ASCII艺术，当回复包含指定标签时自动处理图片"

    def __init__(self, context):
        super().__init__(context)
        self.session = None
        
        # 从配置中获取参数
        self.width = self.config.get("width", 80)
        self.height = self.config.get("height", 40)
        self.chars = self.config.get("chars", " .:-=+*#%@")
        self.tag = self.config.get("tag", "#ascii")
        
        # 确保字符集按亮度排序
        if len(self.chars) < 2:
            self.chars = " .:-=+*#%@"

    async def initialize(self) -> bool:
        """初始化插件"""
        try:
            # 创建 HTTP 会话
            self.session = aiohttp.ClientSession()
            self._register_resource(self.session, "close")
            
            self._log_plugin_action("初始化完成", f"ASCII宽度: {self.width}, 高度: {self.height}, 触发标签: {self.tag}")
            return True
        except Exception as e:
            logger.error(f"AsciiArtPlugin 初始化失败: {e}")
            return False

    async def cleanup(self) -> None:
        """清理资源"""
        await super().cleanup()

    async def on_mention(self, mention_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """处理 @mention 事件"""
        return await self._process_message(mention_data)

    async def on_message(self, message_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """处理聊天消息事件"""
        return await self._process_message(message_data)

    async def _process_message(self, message_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """处理消息的核心逻辑"""
        try:
            # 检查是否包含指定的标签
            if not self._has_trigger_tag(message_data):
                return None

            # 检查是否包含图片附件
            images = self._extract_images_from_note(message_data)
            if not images:
                return None

            # 只处理第一张图片
            image_url = images[0]
            
            username = self._extract_username(message_data)
            self._log_plugin_action("处理ASCII转换请求", f"来自 @{username}")
            
            # 转换图片为ASCII艺术
            ascii_art = await self._convert_image_to_ascii(image_url)
            
            if ascii_art:
                return self._create_response(f"🎨 ASCII艺术转换完成：\n\n```\n{ascii_art}\n```")
            else:
                return self._create_response("❌ 图片转换失败，请检查图片是否可访问")
                
        except Exception as e:
            logger.error(f"AsciiArtPlugin 处理消息时出错: {e}")
            return None

    def _has_trigger_tag(self, message_data: Dict[str, Any]) -> bool:
        """检查消息是否包含触发标签"""
        try:
            note = message_data.get("note", message_data)
            text = note.get("text", "") or ""
            
            # 转义特殊字符以用于正则表达式
            escaped_tag = re.escape(self.tag)
            # 使用正则表达式检查是否包含指定标签（不区分大小写）
            return bool(re.search(escaped_tag + r'\b', text, re.IGNORECASE))
            
        except Exception as e:
            logger.error(f"检查触发标签时出错: {e}")
            return False

    def _extract_images_from_note(self, note_data: Dict[str, Any]) -> list:
        """从 note 数据中提取图片 URL"""
        images = []
        
        # 尝试多种可能的数据结构
        note = note_data.get("note", note_data)
        
        # 检查 files 字段（Misskey 的附件通常存储在这里）
        files = note.get("files", [])
        for file_info in files:
            if isinstance(file_info, dict):
                # 检查是否是图片类型
                file_type = file_info.get("type", "")
                if file_type.startswith("image/"):
                    # 获取图片 URL，优先使用原图
                    url = file_info.get("url") or file_info.get("thumbnailUrl")
                    if url:
                        images.append(url)
        
        # 也检查 attachments 字段（备用）
        attachments = note.get("attachments", [])
        for attachment in attachments:
            if isinstance(attachment, dict):
                file_type = attachment.get("type", "")
                if file_type.startswith("image/"):
                    url = attachment.get("url") or attachment.get("thumbnailUrl")
                    if url:
                        images.append(url)
        
        return images

    async def _convert_image_to_ascii(self, image_url: str) -> Optional[str]:
        """将图片转换为ASCII艺术"""
        try:
            # 下载图片
            image_data = await self._download_image(image_url)
            if not image_data:
                return None
            
            # 打开图片
            image = Image.open(io.BytesIO(image_data))
            
            # 转换为灰度图
            if image.mode != 'L':
                image = image.convert('L')
            
            # 增强对比度
            enhancer = ImageEnhance.Contrast(image)
            image = enhancer.enhance(1.5)
            
            # 计算合适的尺寸，保持宽高比
            original_width, original_height = image.size
            aspect_ratio = original_height / original_width
            
            # 调整宽度和高度
            new_width = self.width
            new_height = int(aspect_ratio * new_width * 0.55)  # 0.55 是字符高宽比的补偿
            
            # 限制最大高度
            if new_height > self.height:
                new_height = self.height
                new_width = int(new_height / aspect_ratio / 0.55)
            
            # 调整图片大小
            image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
            
            # 转换为ASCII
            ascii_art = self._image_to_ascii(image)
            
            return ascii_art
            
        except Exception as e:
            logger.error(f"转换图片为ASCII时出错: {e}")
            return None

    async def _download_image(self, image_url: str) -> Optional[bytes]:
        """下载图片数据"""
        try:
            async with self.session.get(image_url) as response:
                if response.status == 200:
                    # 检查内容类型
                    content_type = response.headers.get('content-type', '')
                    if not content_type.startswith('image/'):
                        logger.warning(f"URL 不是图片类型: {content_type}")
                        return None
                    
                    # 检查文件大小（限制为10MB）
                    content_length = response.headers.get('content-length')
                    if content_length and int(content_length) > 10 * 1024 * 1024:
                        logger.warning(f"图片文件过大: {content_length} bytes")
                        return None
                    
                    return await response.read()
                else:
                    logger.error(f"下载图片失败: HTTP {response.status}")
                    return None
                    
        except Exception as e:
            logger.error(f"下载图片时出错: {e}")
            return None

    def _image_to_ascii(self, image: Image.Image) -> str:
        """将PIL图片对象转换为ASCII字符串"""
        try:
            pixels = list(image.getdata())
            width, height = image.size
            
            ascii_lines = []
            char_count = len(self.chars)
            
            for y in range(height):
                line = ""
                for x in range(width):
                    pixel_index = y * width + x
                    if pixel_index < len(pixels):
                        # 获取像素亮度值 (0-255)
                        brightness = pixels[pixel_index]
                        # 映射到字符集索引
                        char_index = int(brightness * (char_count - 1) / 255)
                        line += self.chars[char_index]
                    else:
                        line += self.chars[0]  # 默认使用最暗的字符
                ascii_lines.append(line)
            
            return '\n'.join(ascii_lines)
            
        except Exception as e:
            logger.error(f"图片转ASCII时出错: {e}")
            return ""

    def _create_response(self, response_text: str, content_key: str = "response") -> Dict[str, Any]:
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
