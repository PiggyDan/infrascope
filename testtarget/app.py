"""InfraScope local test target.

A tiny HTTP service the monitor can check through the private Compose network:

    GET /healthy    -> 200
    GET /unhealthy  -> 503
    GET /slow       -> 200 after SLOW_DELAY_SECONDS (override with ?delay=<seconds>)

It also acts as a webhook receiver for testing InfraScope notifications:

    POST   /webhook            -> 200, records the request (last 50 kept in memory)
    POST   /webhook/fail       -> 500, records the request (to exercise retries)
    GET    /webhook/received   -> the recorded requests
    DELETE /webhook/received   -> clear them
"""

import asyncio
import os
from collections import deque

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse

MAX_DELAY_SECONDS = 30.0
DEFAULT_DELAY_SECONDS = min(float(os.getenv("SLOW_DELAY_SECONDS", "3")), MAX_DELAY_SECONDS)

app = FastAPI(title="InfraScope Test Target", docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/healthy")
async def healthy() -> dict[str, str]:
    return {"status": "healthy"}


@app.get("/unhealthy")
async def unhealthy() -> JSONResponse:
    return JSONResponse({"status": "unhealthy"}, status_code=503)


@app.get("/slow")
async def slow(
    delay: float | None = Query(None, ge=0, le=MAX_DELAY_SECONDS),
) -> dict[str, float | str]:
    seconds = DEFAULT_DELAY_SECONDS if delay is None else delay
    await asyncio.sleep(seconds)
    return {"status": "slow", "delay_seconds": seconds}


MAX_WEBHOOK_BODY = 64 * 1024
received: deque[dict] = deque(maxlen=50)


async def _record(request: Request, accepted: bool) -> None:
    body = (await request.body())[:MAX_WEBHOOK_BODY]
    received.append(
        {
            "path": request.url.path,
            "accepted": accepted,
            "headers": {
                k: v
                for k, v in request.headers.items()
                if k.startswith("x-infrascope-") or k in ("content-type", "user-agent")
            },
            "body": body.decode("utf-8", errors="replace"),
        }
    )


@app.post("/webhook")
async def webhook(request: Request) -> dict[str, bool]:
    await _record(request, accepted=True)
    return {"received": True}


@app.post("/webhook/fail")
async def webhook_fail(request: Request) -> JSONResponse:
    await _record(request, accepted=False)
    return JSONResponse({"received": False}, status_code=500)


@app.get("/webhook/received")
async def webhook_received() -> list[dict]:
    return list(received)


@app.delete("/webhook/received")
async def webhook_clear() -> dict[str, int]:
    count = len(received)
    received.clear()
    return {"cleared": count}
