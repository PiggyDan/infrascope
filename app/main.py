"""FastAPI application factory.

Run with: uvicorn app.main:create_app --factory
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.api import api_keys, health, incidents, notifications, summary, targets
from app.config import Settings, get_settings
from app.db import create_db_engine, make_session_factory
from app.services.checker import HttpChecker
from app.services.monitor import MonitorEngine
from app.services.notifications import WebhookDispatcher
from app.services.url_policy import UnsafeURLError, validate_target_url

logger = logging.getLogger("infrascope")

DESCRIPTION = """
InfraScope monitors HTTP(S) endpoints, stores every measurement and opens/resolves
incidents automatically.

**Authentication:** send an API key in the `X-API-Key` header (use the *Authorize*
button). `VIEWER` keys can read; `ADMIN` keys can also change targets and manage keys.
Create the first key with `python -m app.cli create-api-key --name admin --role ADMIN`.
`/health` and these docs are public.
"""


def _check_webhook_config(settings: Settings) -> None:
    """Fail fast on a webhook URL the SSRF policy would block; warn on unsigned webhooks."""
    try:
        validate_target_url(
            settings.notify_webhook_url, settings.allowed_hosts, settings.allowed_networks
        )
    except UnsafeURLError as exc:
        raise RuntimeError(
            f"NOTIFY_WEBHOOK_URL is not allowed by the destination policy: {exc}. "
            "Add its host to ALLOWED_TARGET_HOSTS (or its IP to ALLOWED_TARGET_NETWORKS)."
        ) from exc
    if settings.notify_webhook_secret is None:
        logger.warning("NOTIFY_WEBHOOK_SECRET is not set: webhooks will be sent unsigned")


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
        dispatcher: WebhookDispatcher | None = None
        if settings.notifications_enabled:
            _check_webhook_config(settings)
            dispatcher = WebhookDispatcher(session_factory, settings)
        if settings.monitor_enabled:
            checker = HttpChecker(timeout_seconds=settings.http_timeout_seconds)
            monitor = MonitorEngine(session_factory, checker, settings, dispatcher=dispatcher)
            monitor.start()
        app.state.monitor = monitor
        logger.info(
            "InfraScope %s started (allowed hosts: %s; allowed networks: %s; webhooks: %s)",
            __version__,
            ", ".join(sorted(settings.allowed_hosts)) or "<none>",
            ", ".join(str(n) for n in settings.allowed_networks) or "<none>",
            "on" if dispatcher else "off",
        )
        try:
            yield
        finally:
            if monitor is not None:
                await asyncio.to_thread(monitor.stop)
            if checker is not None:
                checker.close()
            if dispatcher is not None:
                dispatcher.close()
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
    app.include_router(api_keys.router)
    app.include_router(notifications.router)
    return app
