#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
from typing import Any, Union
from urllib.parse import urlparse
from loguru import logger

from .interfaces import IValidator


class Validator(IValidator):
    def validate_string(
        self, value: Any, param_name: str, min_length: int = 0, max_length: int = None
    ) -> str:
        if not isinstance(value, str):
            raise ValueError(f"{param_name} 必须是字符串")
        if len(value) < min_length:
            raise ValueError(f"{param_name} 长度不能少于 {min_length} 个字符")
        if max_length and len(value) > max_length:
            raise ValueError(f"{param_name} 长度不能超过 {max_length} 个字符")
        return value

    def validate_numeric(
        self,
        value: Any,
        param_name: str,
        min_value: Union[int, float] = None,
        max_value: Union[int, float] = None,
    ) -> Union[int, float]:
        if not isinstance(value, (int, float)):
            raise ValueError(f"{param_name} 必须是数字")
        if min_value is not None and value < min_value:
            raise ValueError(f"{param_name} 不能小于 {min_value}")
        if max_value is not None and value > max_value:
            raise ValueError(f"{param_name} 不能大于 {max_value}")
        return value

    def validate_url(self, value: Any, param_name: str) -> str:
        if not isinstance(value, str):
            raise ValueError(f"{param_name} 必须是字符串")
        try:
            result = urlparse(value)
            if not all([result.scheme, result.netloc]) or result.scheme not in [
                "http",
                "https",
            ]:
                raise ValueError(f"{param_name} 必须是有效的 URL")
        except Exception:
            raise ValueError(f"{param_name} 必须是有效的 URL")
        return value

    def validate_api_key(self, value: Any, param_name: str) -> str:
        if not value or not isinstance(value, str):
            raise ValueError(f"{param_name} 必须是字符串")
        value = value.strip()
        if len(value) < 32 or len(value) > 64:
            raise ValueError(f"{param_name} 长度必须在32-64个字符之间")
        placeholder_patterns = [
            r"your.*key.*here",
            r"replace.*with.*key",
            r"api.*key.*placeholder",
            r"sk-[a-zA-Z0-9]{20,}",
        ]
        value_lower = value.lower()
        for pattern in placeholder_patterns[:-1]:
            if re.search(pattern, value_lower):
                raise ValueError(f"{param_name} 不能是占位符")
        return value

    def validate_access_token(self, value: Any, param_name: str) -> str:
        if not value or not isinstance(value, str):
            raise ValueError(f"{param_name} 必须是字符串")
        value = value.strip()
        if len(value) < 32 or len(value) > 64:
            raise ValueError(f"{param_name} 长度必须在32-64个字符之间")
        if not re.match(r"^[a-zA-Z0-9]+$", value):
            raise ValueError(f"{param_name} 只能包含字母和数字")
        placeholder_patterns = [
            r"your.*token.*here",
            r"replace.*with.*token",
            r"access.*token.*placeholder",
            r"example.*token",
            r"test.*token",
        ]
        value_lower = value.lower()
        for pattern in placeholder_patterns:
            if re.search(pattern, value_lower):
                raise ValueError(f"{param_name} 不能是占位符")
        return value

    def log_validation_error(self, error: Exception, context: str = "") -> None:
        if context:
            logger.error(f"参数验证失败 ({context}): {error}")
        else:
            logger.error(f"参数验证失败: {error}")
