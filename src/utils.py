#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import asyncio
import platform
from typing import Dict, Any, Optional

import psutil
from loguru import logger
from tenacity import (
    retry,
    stop_after_attempt,
    retry_if_exception_type,
)


def retry_async(max_retries=3, retryable_exceptions=None):
    def _before_retry_log(retry_state):
        logger.info(f"第{retry_state.attempt_number}次重试...")

    kwargs = {
        "stop": stop_after_attempt(max_retries),
        "before": _before_retry_log,
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
    logger.info(
        f"运行环境: Python {system_info['python_version']}, {system_info['platform']}, CPU 核心: {system_info['cpu_count']}, 内存: {system_info['memory_total_gb']} GB"
    )


def get_memory_usage() -> Dict[str, Any]:
    process = psutil.Process(os.getpid())
    memory_info = process.memory_info()
    rss_mb = memory_info.rss / (1024 * 1024)
    vms_mb = memory_info.vms / (1024 * 1024)
    return {
        "rss_mb": round(rss_mb, 2),
        "vms_mb": round(vms_mb, 2),
        "percent": process.memory_percent(),
    }


async def monitor_memory_usage() -> None:
    interval_seconds = 3600
    threshold_mb = 1024
    while True:
        try:
            memory_usage = get_memory_usage()
            logger.debug(
                f"内存使用: {memory_usage['rss_mb']} MB (物理), {memory_usage['vms_mb']} MB (虚拟), {memory_usage['percent']:.2f}%"
            )
            if memory_usage["rss_mb"] > threshold_mb:
                logger.warning(f"内存使用过高: {memory_usage['rss_mb']} MB")
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
    return (
        user_info.get("username", "unknown")
        if isinstance(user_info, dict)
        else "unknown"
    )


def health_check() -> bool:
    try:
        memory_usage = get_memory_usage()
        if memory_usage["percent"] > 90:
            logger.warning(f"内存使用过高: {memory_usage['percent']}%")
            return False
        current_process = psutil.Process(os.getpid())
        if not current_process.is_running():
            return False
        return True
    except (OSError, ValueError, AttributeError) as e:
        logger.error(f"健康检查失败: {e}")
        return False
