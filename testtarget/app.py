"""InfraScope local test target.

A tiny HTTP service the monitor can check through the private Compose network:

    GET /healthy    -> 200
    GET /unhealthy  -> 503
    GET /slow       -> 200 after SLOW_DELAY_SECONDS (override with ?delay=<seconds>)
"""

import asyncio
import os

from fastapi import FastAPI, Query
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
