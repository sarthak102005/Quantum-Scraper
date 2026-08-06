"""
run.py — Windows-compatible server launcher.

Root cause: uvicorn's asyncio_loop_factory(use_subprocess=False) explicitly
returns SelectorEventLoop on Windows. SelectorEventLoop cannot spawn
subprocesses, which breaks Playwright (it spawns a Chromium browser process).

Fix: Pass a custom loop_factory callable directly to uvicorn.run() that
always creates a ProactorEventLoop on Windows. uvicorn accepts any callable
that returns an AbstractEventLoop as the `loop` parameter.
"""

import sys
import asyncio
import uvicorn


def _make_event_loop() -> asyncio.AbstractEventLoop:
    """Always returns ProactorEventLoop on Windows, SelectorEventLoop elsewhere."""
    if sys.platform == "win32":
        return asyncio.ProactorEventLoop()
    return asyncio.SelectorEventLoop()


if __name__ == "__main__":
    uvicorn.run(
        "web.server:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        loop=_make_event_loop,  # type: ignore[arg-type]
    )

