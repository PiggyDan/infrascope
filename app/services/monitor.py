"""Background monitoring engine.

A single scheduler thread wakes every `monitor_tick_seconds`, selects enabled
targets whose interval has elapsed and runs their checks on a small thread pool.
It runs outside the event loop, so API requests are never blocked.

Day 1 assumes a single API process (one uvicorn worker). Running several
replicas would schedule duplicate checks; see docs/ARCHITECTURE.md.
"""

import logging
import threading
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.models import MonitoringTarget
from app.services.checker import CheckOutcome, HttpChecker
from app.services.incidents import CheckProcessingResult, record_check
from app.services.url_policy import UnsafeURLError, validate_target_url
from app.timeutil import utcnow

logger = logging.getLogger(__name__)


def is_due(target: MonitoringTarget, now: datetime) -> bool:
    if target.last_checked_at is None:
        return True
    return now - target.last_checked_at >= timedelta(seconds=target.interval_seconds)


class MonitorEngine:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        checker: HttpChecker,
        settings: Settings,
        *,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._session_factory = session_factory
        self._checker = checker
        self._settings = settings
        self._clock = clock
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._executor: ThreadPoolExecutor | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        with self._lock:
            if self.running:
                return
            self._stop_event.clear()
            self._executor = ThreadPoolExecutor(
                max_workers=self._settings.monitor_max_workers,
                thread_name_prefix="infrascope-check",
            )
            self._thread = threading.Thread(
                target=self._run_loop, name="infrascope-monitor", daemon=True
            )
            self._thread.start()
        logger.info(
            "Monitoring engine started (tick=%.1fs, workers=%d)",
            self._settings.monitor_tick_seconds,
            self._settings.monitor_max_workers,
        )

    def stop(self, timeout: float | None = None) -> None:
        """Stop scheduling and wait for in-flight checks to finish."""
        with self._lock:
            self._stop_event.set()
            if self._thread is not None:
                self._thread.join(timeout or self._settings.http_timeout_seconds + 5)
            if self._executor is not None:
                self._executor.shutdown(wait=True, cancel_futures=True)
            self._thread = None
            self._executor = None
        logger.info("Monitoring engine stopped")

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.run_once()
            except Exception:
                logger.exception("Monitoring cycle failed")
            self._stop_event.wait(self._settings.monitor_tick_seconds)

    def find_due_targets(self, now: datetime) -> list[tuple[uuid.UUID, str]]:
        with self._session_factory() as session:
            targets = session.scalars(
                select(MonitoringTarget).where(MonitoringTarget.enabled.is_(True))
            ).all()
            return [(t.id, t.url) for t in targets if is_due(t, now)]

    def run_once(self) -> int:
        """Run one scheduling cycle; returns the number of checks performed."""
        due = self.find_due_targets(self._clock())
        if not due:
            return 0
        executor = self._executor
        if executor is None:  # synchronous mode (tests, one-off runs)
            for target_id, url in due:
                self.check_target(target_id, url)
        else:
            futures = [executor.submit(self.check_target, tid, url) for tid, url in due]
            for future in futures:
                future.result()
        return len(due)

    def check_target(self, target_id: uuid.UUID, url: str) -> CheckProcessingResult | None:
        checked_at = self._clock()
        try:
            validate_target_url(url, self._settings.allowed_hosts)
        except UnsafeURLError as exc:
            outcome = CheckOutcome(success=False, error=f"Blocked by URL policy: {exc}")
        else:
            outcome = self._checker.check(url)

        try:
            with self._session_factory() as session, session.begin():
                target = session.get(MonitoringTarget, target_id, with_for_update=True)
                if target is None or not target.enabled or target.url != url:
                    # Deleted, disabled or re-pointed while the check was running.
                    return None
                target_name = target.name
                processing = record_check(
                    session,
                    target,
                    outcome,
                    checked_at=checked_at,
                    failure_threshold=self._settings.failure_threshold,
                    recovery_threshold=self._settings.recovery_threshold,
                )
        except SQLAlchemyError:
            logger.exception("Failed to persist check result for target %s", target_id)
            return None

        if processing.opened_incident is not None:
            logger.warning(
                "Incident opened for target '%s': %s",
                target_name,
                processing.opened_incident.failure_reason,
            )
        if processing.resolved_incident is not None:
            logger.info("Incident resolved for target '%s'", target_name)
        return processing
