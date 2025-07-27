#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
from typing import Any, Optional, List, Dict
from pydantic import BaseModel, Field, field_validator, HttpUrl
from pydantic import constr
from loguru import logger
from .interfaces import IValidator


class MisskeyConfig(BaseModel):
    instance_url: HttpUrl
    access_token: constr(min_length=32, max_length=64, pattern=r"^[a-zA-Z0-9]+$")

    @field_validator("access_token")
    @classmethod
    def validate_access_token(cls, v):
        if not v or not isinstance(v, str):
            raise ValueError("访问令牌必须是字符串")
        v = v.strip()
        patterns = [
            r"your.*token.*here",
            r"replace.*with.*token",
            r"access.*token.*placeholder",
            r"example.*token",
            r"test.*token",
        ]
        for pattern in patterns:
            if re.search(pattern, v.lower()):
                raise ValueError("访问令牌不能是占位符")
        return v


class DeepSeekConfig(BaseModel):
    api_key: constr(min_length=32, max_length=64)
    model: constr(min_length=1) = "deepseek-chat"
    api_base: HttpUrl = "https://api.deepseek.com/v1"
    max_tokens: int = Field(default=1000, ge=1, le=4096)
    temperature: float = Field(default=0.8, ge=0, le=2)

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, v):
        if not v or not isinstance(v, str):
            raise ValueError("API密钥必须是字符串")
        v = v.strip()
        patterns = [r"your.*key.*here", r"replace.*with.*key", r"api.*key.*placeholder"]
        for pattern in patterns:
            if re.search(pattern, v.lower()):
                raise ValueError("API密钥不能是占位符")
        return v


class TextGenerationRequest(BaseModel):
    prompt: constr(min_length=1)
    system_prompt: Optional[constr(min_length=1)] = None
    max_tokens: int = Field(default=1000, ge=1, le=4096)
    temperature: float = Field(default=0.8, ge=0, le=2)


class ChatMessage(BaseModel):
    role: str
    content: constr(min_length=1)


class ChatRequest(BaseModel):
    messages: List[ChatMessage] = Field(min_items=1)
    max_tokens: int = Field(default=1000, ge=1)
    temperature: float = Field(default=0.8, ge=0, le=2)


class Validator(IValidator):
    def log_validation_error(self, error: Exception, context: str = "") -> None:
        if context:
            logger.error(f"参数验证失败 ({context}): {error}")
        else:
            logger.error(f"参数验证失败: {error}")

    def validate_config(
        self, misskey_data: Dict[str, Any], deepseek_data: Dict[str, Any]
    ) -> tuple:
        misskey_config = MisskeyConfig(**misskey_data)
        deepseek_config = DeepSeekConfig(**deepseek_data)
        return misskey_config, deepseek_config

    def validate_misskey_config(self, misskey_data: Dict[str, Any]) -> "MisskeyConfig":
        return MisskeyConfig(**misskey_data)

    def validate_deepseek_config(
        self, deepseek_data: Dict[str, Any]
    ) -> "DeepSeekConfig":
        return DeepSeekConfig(**deepseek_data)

    def validate_text_generation(self, **kwargs) -> TextGenerationRequest:
        return TextGenerationRequest(**kwargs)

    def validate_chat_request(self, **kwargs) -> ChatRequest:
        return ChatRequest(**kwargs)
