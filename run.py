import asyncio

from src import BotRunner


async def handle_shutdown(runner: BotRunner, error_msg: str = None) -> None:
    if error_msg:
        print(f"\n{error_msg}")
    try:
        await runner.shutdown()
    except (OSError, ValueError, TypeError) as e:
        print(f"关闭时出错: {e}")


if __name__ == "__main__":
    runner = BotRunner()
    try:
        asyncio.run(runner.run())
    except KeyboardInterrupt:
        asyncio.run(handle_shutdown(runner))
        print("\n机器人已停止")
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        RuntimeError,
        ImportError,
    ) as e:
        asyncio.run(handle_shutdown(runner, f"启动时出错: {e}"))
