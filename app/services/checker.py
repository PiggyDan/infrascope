"""Real HTTP checks. No simulated measurements."""

import time
from dataclasses import dataclass

import httpx

from app import __version__

USER_AGENT = f"InfraScope-Monitor/{__version__}"
MAX_ERROR_LENGTH = 500


@dataclass(frozen=True)
class CheckOutcome:
    success: bool
    status_code: int | None = None
    response_time_ms: float | None = None
    error: str | None = None

    @property
    def failure_reason(self) -> str:
        if self.error:
            return self.error
        if self.status_code is not None:
            return f"HTTP {self.status_code}"
        return "Unknown failure"


def _trim(message: str) -> str:
    return message[:MAX_ERROR_LENGTH]


class HttpChecker:
    """Performs a single GET and measures time until response headers arrive.

    Redirects are never followed (SSRF protection), proxy environment variables
    are ignored, and connections are not reused so every measurement includes
    connection setup.
    """

    def __init__(
        self, timeout_seconds: float = 5.0, *, transport: httpx.BaseTransport | None = None
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._client = httpx.Client(
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=False,
            trust_env=False,
            transport=transport,
            headers={"User-Agent": USER_AGENT},
            limits=httpx.Limits(max_connections=32, max_keepalive_connections=0),
        )

    def check(self, url: str) -> CheckOutcome:
        start = time.perf_counter()
        try:
            # Stream so we only wait for headers and never download large bodies.
            with self._client.stream("GET", url) as response:
                elapsed_ms = (time.perf_counter() - start) * 1000
                status_code = response.status_code
        except httpx.TimeoutException:
            return CheckOutcome(success=False, error=f"Timeout after {self._timeout_seconds:g}s")
        except httpx.ConnectError as exc:
            return CheckOutcome(
                success=False, error=_trim(f"Connection failed: {exc or type(exc).__name__}")
            )
        except httpx.HTTPError as exc:
            return CheckOutcome(success=False, error=_trim(f"{type(exc).__name__}: {exc}"))

        success = 200 <= status_code < 400
        return CheckOutcome(
            success=success,
            status_code=status_code,
            response_time_ms=round(elapsed_ms, 2),
            error=None if success else f"HTTP {status_code}",
        )

    def close(self) -> None:
        self._client.close()
