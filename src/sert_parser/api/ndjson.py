from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from contextvars import copy_context
from typing import Any

from sert_parser.logging_setup import set_step_sink, start_steps

STREAM_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "X-Accel-Buffering": "no",
}


def ndjson_line(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False) + "\n"


async def stream_sync_work(work: Callable[[], dict[str, Any]]) -> AsyncIterator[str]:
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()

    def sink(message: str) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, ("step", message))

    start_steps()
    set_step_sink(sink)
    ctx = copy_context()

    def run() -> dict[str, Any]:
        try:
            return work()
        except Exception as exc:
            return {"type": "error", "detail": str(exc)}
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, ("end", None))

    task = asyncio.create_task(asyncio.to_thread(ctx.run, run))
    try:
        while True:
            kind, data = await queue.get()
            if kind == "step":
                yield ndjson_line({"type": "step", "text": data})
            else:
                break
        yield ndjson_line(await task)
    finally:
        set_step_sink(None)


async def stream_async_work(work: Callable[[], Awaitable[dict[str, Any]]]) -> AsyncIterator[str]:
    queue: asyncio.Queue[str] = asyncio.Queue()

    def sink(message: str) -> None:
        queue.put_nowait(message)

    set_step_sink(sink)

    async def run_work() -> dict[str, Any]:
        try:
            return await work()
        except Exception as exc:
            return {"type": "error", "detail": str(exc)}

    task = asyncio.create_task(run_work())
    try:
        while not task.done() or not queue.empty():
            try:
                text = await asyncio.wait_for(queue.get(), timeout=0.05)
            except TimeoutError:
                continue
            yield ndjson_line({"type": "step", "text": text})
        yield ndjson_line(await task)
    finally:
        set_step_sink(None)
