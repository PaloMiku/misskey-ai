#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import sys

from src.main import main, shutdown


async def handle_shutdown(error_msg: str = None) -> None:
    if error_msg:
        print(f"\n{error_msg}")
    try:
        await shutdown()
    except (OSError, ValueError, TypeError) as e:
        print(f"关闭时出错: {e}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.platform == "win32" and asyncio.run(handle_shutdown())
        print("\n机器人已停止")
    except (
        OSError,
        IOError,
        ValueError,
        TypeError,
        KeyError,
        RuntimeError,
        ImportError,
        ModuleNotFoundError,
    ) as e:
        error_map = {
            (OSError, IOError): "文件或网络错误",
            (ValueError, TypeError, KeyError): "配置或数据错误",
            (RuntimeError, ImportError, ModuleNotFoundError): "运行时错误",
        }
        msg = next((v for k, v in error_map.items() if isinstance(e, k)), "未知错误")
        asyncio.run(handle_shutdown(f"{msg}: {e}"))
