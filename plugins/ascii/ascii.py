#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
import io
import aiohttp
from typing import Dict, Any, Optional
from PIL import Image, ImageEnhance, ImageFilter

from loguru import logger

from src.plugin_base import PluginBase


class AsciiArtPlugin(PluginBase):
    description = "将图片转换为ASCII艺术，当回复包含指定标签时自动处理图片"

    def __init__(self, context):
        super().__init__(context)
        self.session = None
        
        # 从配置中获取参数
        self.width = self.config.get("width", 60)
        self.height = self.config.get("height", 30)
        self.chars = self.config.get("chars", " ░▒▓█")
        self.tag = self.config.get("tag", "#ascii")
        
        # 新增自动比例相关配置
        self.auto_scale = self.config.get("auto_scale", True)
        self.max_width = self.config.get("max_width", 80)
        self.max_height = self.config.get("max_height", 40)
        self.preserve_aspect = self.config.get("preserve_aspect", True)
        
        # 确保字符集按亮度排序
        if len(self.chars) < 2:
            self.chars = " ░▒▓█"

    async def initialize(self) -> bool:
        """初始化插件"""
        try:
            # 创建 HTTP 会话
            self.session = aiohttp.ClientSession()
            self._register_resource(self.session, "close")
            
            scale_mode = "自动" if self.auto_scale else "固定"
            self._log_plugin_action("初始化完成", 
                f"缩放模式: {scale_mode}, 最大尺寸: {self.max_width}x{self.max_height}, 触发标签: {self.tag}")
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
            
            # 增强图片质量
            # 1. 锐化处理
            image = image.filter(ImageFilter.SHARPEN)
            
            # 2. 自适应对比度增强
            enhancer = ImageEnhance.Contrast(image)
            image = enhancer.enhance(1.8)
            
            # 3. 亮度调整
            brightness_enhancer = ImageEnhance.Brightness(image)
            image = brightness_enhancer.enhance(1.1)
            
            # 计算最优尺寸
            original_width, original_height = image.size
            new_width, new_height = self._calculate_optimal_size(original_width, original_height)
            
            # 使用高质量重采样
            image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
            
            # 转换为ASCII
            ascii_art = self._image_to_ascii_enhanced(image)
            
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

    def _calculate_optimal_size(self, original_width: int, original_height: int) -> tuple:
        """计算最优的ASCII艺术尺寸"""
        try:
            if not self.auto_scale:
                # 使用固定尺寸模式
                if self.preserve_aspect:
                    aspect_ratio = original_height / original_width
                    new_width = self.width
                    new_height = int(aspect_ratio * new_width * 0.5)  # 字符高宽比补偿
                    
                    if new_height > self.height:
                        new_height = self.height
                        new_width = int(new_height / aspect_ratio / 0.5)
                    
                    return new_width, new_height
                else:
                    return self.width, self.height
            
            # 自动缩放模式
            aspect_ratio = original_height / original_width
            
            # 字符高宽比补偿因子
            char_aspect_compensation = 0.5  # Unicode块字符接近正方形
            
            # 根据图片比例特点选择最优尺寸策略
            if aspect_ratio > 1.5:  # 高图片（竖图）
                # 以高度为主要限制
                target_height = min(self.max_height, int(self.max_width * aspect_ratio * char_aspect_compensation))
                target_width = int(target_height / aspect_ratio / char_aspect_compensation)
                
                # 确保不超过最大宽度
                if target_width > self.max_width:
                    target_width = self.max_width
                    target_height = int(target_width * aspect_ratio * char_aspect_compensation)
                    
            elif aspect_ratio < 0.6:  # 宽图片（横图）
                # 以宽度为主要限制
                target_width = self.max_width
                target_height = int(target_width * aspect_ratio * char_aspect_compensation)
                
                # 确保不超过最大高度
                if target_height > self.max_height:
                    target_height = self.max_height
                    target_width = int(target_height / aspect_ratio / char_aspect_compensation)
                    
            else:  # 方形或接近方形的图片
                # 平衡宽度和高度
                target_width = min(self.max_width, int(self.max_height / aspect_ratio / char_aspect_compensation))
                target_height = int(target_width * aspect_ratio * char_aspect_compensation)
                
                # 双向检查限制
                if target_height > self.max_height:
                    target_height = self.max_height
                    target_width = int(target_height / aspect_ratio / char_aspect_compensation)
                elif target_width > self.max_width:
                    target_width = self.max_width
                    target_height = int(target_width * aspect_ratio * char_aspect_compensation)
            
            # 确保最小尺寸
            target_width = max(target_width, 10)
            target_height = max(target_height, 5)
            
            # 确保最大尺寸
            target_width = min(target_width, self.max_width)
            target_height = min(target_height, self.max_height)
            
            logger.debug(f"原始尺寸: {original_width}x{original_height}, "
                        f"目标尺寸: {target_width}x{target_height}, "
                        f"宽高比: {aspect_ratio:.2f}")
            
            return target_width, target_height
            
        except Exception as e:
            logger.error(f"计算最优尺寸时出错: {e}")
            # 回退到默认尺寸
            return self.width, self.height

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

    def _image_to_ascii_enhanced(self, image: Image.Image) -> str:
        """将PIL图片对象转换为ASCII字符串（增强版）"""
        try:
            pixels = list(image.getdata())
            width, height = image.size
            
            # 计算直方图均衡化
            hist = [0] * 256
            for pixel in pixels:
                hist[pixel] += 1
            
            # 计算累积分布函数
            cdf = [0] * 256
            cdf[0] = hist[0]
            for i in range(1, 256):
                cdf[i] = cdf[i-1] + hist[i]
            
            # 归一化CDF
            total_pixels = len(pixels)
            normalized_cdf = [int(255 * cdf[i] / total_pixels) for i in range(256)]
            
            # 应用直方图均衡化
            equalized_pixels = [normalized_cdf[pixel] for pixel in pixels]
            
            ascii_lines = []
            char_count = len(self.chars)
            
            for y in range(height):
                line = ""
                for x in range(width):
                    pixel_index = y * width + x
                    if pixel_index < len(equalized_pixels):
                        # 获取均衡化后的亮度值
                        brightness = equalized_pixels[pixel_index]
                        
                        # 反转亮度映射（暗像素对应复杂字符）
                        reversed_brightness = 255 - brightness
                        char_index = min(int(reversed_brightness * char_count / 256), char_count - 1)
                        
                        line += self.chars[char_index]
                    else:
                        line += self.chars[0]
                
                ascii_lines.append(line)
            
            return '\n'.join(ascii_lines)
            
        except Exception as e:
            logger.error(f"增强ASCII转换时出错: {e}")
            # 回退到基础方法
            return self._image_to_ascii(image)

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
