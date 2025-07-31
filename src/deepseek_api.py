#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
from typing import Dict, List, Optional

import openai
from loguru import logger

from .interfaces import ITextGenerator
from .utils import retry_async
from .constants import API_MAX_RETRIES, API_TIMEOUT

from openai import (
    RateLimitError,
    APIError,
    AuthenticationError,
    BadRequestError,
    APITimeoutError,
    Timeout,
    APIConnectionError,
)

__all__ = ("DeepSeekAPI",)


class DeepSeekAPI(ITextGenerator):
    def __init__(
        self,
        api_key: str,
        model: str = "deepseek-chat",
        api_base: Optional[str] = None,
    ):
        self.api_key = api_key
        self.model = model
        self.api_base = api_base or "https://api.deepseek.com/v1"
        try:
            self.client = openai.OpenAI(
                api_key=self.api_key, base_url=self.api_base, timeout=API_TIMEOUT
            )
            self._initialized = False
        except (ValueError, TypeError, OSError) as e:
            logger.error(f"创建 DeepSeek API 客户端失败: {e}")
            raise APIConnectionError() from e

    async def initialize(self) -> None:
        if not self._initialized:
            logger.debug(f"DeepSeek API 客户端初始化完成，base_url={self.api_base}")
            self._initialized = True

    @retry_async(
        max_retries=API_MAX_RETRIES,
        retryable_exceptions=(
            RateLimitError,
            APITimeoutError,
            Timeout,
            APIError,
            APIConnectionError,
            OSError,
        ),
    )
    async def _call_api_common(
        self,
        messages: List[Dict[str, str]],
        max_tokens: int,
        temperature: float,
        call_type: str,
    ) -> str:
        try:
            response = await self._make_api_request(messages, max_tokens, temperature)
            return self._process_api_response(response, call_type)
        except BadRequestError as e:
            logger.error(f"API 请求参数错误: {e}")
            raise ValueError("API 请求参数错误") from e
        except AuthenticationError as e:
            logger.error(f"API 认证失败: {e}")
            raise AuthenticationError() from e
        except (ValueError, TypeError, KeyError) as e:
            logger.error(f"API 响应数据格式错误: {e}")
            raise ValueError("API 响应数据格式错误") from e

    async def _make_api_request(
        self, messages: List[Dict[str, str]], max_tokens: int, temperature: float
    ):
        return await asyncio.wait_for(
            asyncio.to_thread(
                self.client.chat.completions.create,
                model=self.model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            ),
            timeout=API_TIMEOUT,
        )

    def _process_api_response(self, response, call_type: str) -> str:
        generated_text = response.choices[0].message.content
        if not generated_text:
            raise APIConnectionError()
        logger.debug(
            f"DeepSeek API {call_type}调用成功，生成内容长度: {len(generated_text)}"
        )
        return generated_text

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
        return False

    async def close(self):
        if getattr(self, "client", None):
            self.client.close()
            logger.debug("DeepSeek API 客户端连接已关闭")

    def _build_messages(
        self, prompt: str, system_prompt: Optional[str] = None
    ) -> List[Dict[str, str]]:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt.strip()})
        messages.append({"role": "user", "content": prompt.strip()})
        return messages

    async def generate_text(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_tokens: int = 1000,
        temperature: float = 0.8,
    ) -> str:
        messages = self._build_messages(prompt, system_prompt)
        return await self._call_api_common(
            messages, max_tokens, temperature, "单轮文本"
        )

    async def generate_chat_response(
        self,
        messages: List[Dict[str, str]],
        max_tokens: int = 1000,
        temperature: float = 0.8,
    ) -> str:
        result = await self._call_api_common(
            messages, max_tokens, temperature, "多轮对话"
        )
        return result.strip()

    async def generate_post(
        self,
        system_prompt: str,
        prompt: Optional[str] = None,
        max_tokens: int = 1000,
        temperature: float = 0.8,
    ) -> str:
        if not prompt or not prompt.strip():
            raise ValueError("缺少提示词")
        return await self.generate_text(
            prompt, system_prompt, max_tokens=max_tokens, temperature=temperature
        )

    async def generate_reply(
        self,
        original_text: str,
        system_prompt: str,
        max_tokens: int = 1000,
        temperature: float = 0.8,
    ) -> str:
        return await self.generate_text(
            original_text, system_prompt, max_tokens=max_tokens, temperature=temperature
        )
