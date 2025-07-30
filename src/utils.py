#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import asyncio
import platform
from typing import Dict, Any, Optional

import psutil
from loguru import logger
from tenacity import retry, stop_after_attempt, retry_if_exception_type


def retry_async(max_retries=3, retryable_exceptions=None):
    def _retry_log(retry_state):
        logger.info(f"第 {retry_state.attempt_number} 次重试...")

    kwargs = {
        "stop": stop_after_attempt(max_retries),
        "before_sleep": _retry_log,
    }
    if retryable_exceptions:
        kwargs["retry"] = retry_if_exception_type(retryable_exceptions)
    return retry(**kwargs)


def get_system_info() -> Dict[str, Any]:
    return {
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "cpu_count": psutil.cpu_count(),
        "memory_total_gb": round(psutil.virtual_memory().total / (1024**3), 2),
        "process_id": os.getpid(),
    }


async def log_system_info() -> None:
    system_info = get_system_info()
    logger.debug(
        f"运行环境: Python {system_info['python_version']}, {system_info['platform']}, CPU 核心: {system_info['cpu_count']}, 内存: {system_info['memory_total_gb']} GB, 进程ID: {system_info['process_id']}"
    )


def get_memory_usage() -> Dict[str, Any]:
    process = psutil.Process()
    memory_info = process.memory_info()
    mb_factor = 1024 * 1024
    return {
        "rss_mb": round(memory_info.rss / mb_factor, 2),
        "vms_mb": round(memory_info.vms / mb_factor, 2),
        "percent": process.memory_percent(),
    }


async def monitor_memory_usage() -> None:
    interval_seconds = 3600
    threshold_mb = 256
    while True:
        try:
            memory_usage = get_memory_usage()
            if memory_usage["rss_mb"] > threshold_mb:
                logger.warning(f"内存使用较高: {memory_usage['rss_mb']} MB")
            await asyncio.sleep(interval_seconds)
        except asyncio.CancelledError:
            break
        except (OSError, ValueError, AttributeError) as e:
            logger.error(f"内存监控出现错误: {e}")
            await asyncio.sleep(interval_seconds)


def extract_user_id(message: Dict[str, Any]) -> Optional[str]:
    user_info = message.get("fromUser") or message.get("user")
    if isinstance(user_info, dict):
        return user_info.get("id")
    return message.get("userId") or message.get("fromUserId")


def extract_username(message: Dict[str, Any]) -> str:
    user_info = message.get("fromUser") or message.get("user", {})
    if isinstance(user_info, dict):
        return user_info.get("username", "unknown")
    return "unknown"


def health_check() -> bool:
    try:
        return psutil.Process().is_running()
    except (OSError, ValueError, AttributeError) as e:
        logger.error(f"健康检查失败: {e}")
        return False
