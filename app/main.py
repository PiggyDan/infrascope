"""FastAPI application factory.

Run with: uvicorn app.main:create_app --factory
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.api import health, incidents, summary, targets
from app.config import Settings, get_settings
from app.db import create_db_engine, make_session_factory
from app.services.checker import HttpChecker
from app.services.monitor import MonitorEngine

logger = logging.getLogger("infrascope")

DESCRIPTION = """
InfraScope monitors HTTP(S) endpoints, stores every measurement and opens/resolves
incidents automatically.

**Day 1 security note:** this API has no authentication. It is a development API
intended to be reachable on `127.0.0.1` only. Authentication and authorization are
Day 2 requirements.
"""


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    # httpx logs every request URL at INFO; the monitor logs what matters itself.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    db_engine = create_db_engine(settings.database_url.get_secret_value())
    session_factory = make_session_factory(db_engine)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        monitor: MonitorEngine | None = None
        checker: HttpChecker | None = None
        if settings.monitor_enabled:
            checker = HttpChecker(timeout_seconds=settings.http_timeout_seconds)
            monitor = MonitorEngine(session_factory, checker, settings)
            monitor.start()
        app.state.monitor = monitor
        logger.info(
            "InfraScope %s started (allowed hosts: %s)",
            __version__,
            ", ".join(sorted(settings.allowed_hosts)) or "<none>",
        )
        try:
            yield
        finally:
            if monitor is not None:
                await asyncio.to_thread(monitor.stop)
            if checker is not None:
                checker.close()
            db_engine.dispose()

    app = FastAPI(
        title="InfraScope",
        version=__version__,
        description=DESCRIPTION,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.db_engine = db_engine
    app.state.session_factory = session_factory
    app.state.monitor = None

    app.include_router(health.router)
    app.include_router(targets.router)
    app.include_router(incidents.router)
    app.include_router(summary.router)
    return app
