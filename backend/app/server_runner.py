"""Windows-kit ASGI runner with a graceful authenticated-update shutdown hook."""

from __future__ import annotations

import asyncio
import os

import uvicorn

from . import server_control
from .main import app


async def run() -> None:
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=int(os.environ.get("DTC_PORT", "8000"))))

    async def watch_shutdown() -> None:
        while not server.should_exit:
            if server_control.stop_requested():
                server.should_exit = True
                return
            await asyncio.sleep(0.1)

    watcher = asyncio.create_task(watch_shutdown())
    try:
        await server.serve()
    finally:
        watcher.cancel()
        try:
            await watcher
        except asyncio.CancelledError:
            pass


if __name__ == "__main__":
    asyncio.run(run())
