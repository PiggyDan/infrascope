from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app import __version__
from app.api.deps import get_session
from app.schemas import HealthRead

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthRead, summary="Liveness and database check")
def health(request: Request, response: Response, session: Session = Depends(get_session)):
    try:
        session.execute(text("SELECT 1"))
        database = "ok"
    except SQLAlchemyError:
        database = "unavailable"

    monitor = request.app.state.monitor
    if not request.app.state.settings.monitor_enabled:
        monitor_state = "disabled"
    else:
        monitor_state = "running" if monitor is not None and monitor.running else "stopped"

    healthy = database == "ok"
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthRead(
        status="ok" if healthy else "degraded",
        database=database,
        monitor=monitor_state,
        version=__version__,
    )
