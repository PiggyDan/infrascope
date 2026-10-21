"""Incident rules, exercised directly against the service (no scheduler)."""

from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import Incident, IncidentStatus, MonitoringResult, MonitoringTarget, TargetStatus
from app.services.checker import CheckOutcome
from app.services.incidents import record_check
from app.timeutil import utcnow

FAIL = CheckOutcome(success=False, status_code=503, response_time_ms=5.0, error="HTTP 503")
TIMEOUT = CheckOutcome(success=False, error="Timeout after 5s")
OK = CheckOutcome(success=True, status_code=200, response_time_ms=4.2)


@pytest.fixture
def run(session_factory, make_target):
    target = make_target(name="api")
    state = {"t": utcnow()}

    def _run(*outcomes: CheckOutcome):
        processed = []
        for outcome in outcomes:
            state["t"] += timedelta(seconds=30)
            with session_factory() as session, session.begin():
                db_target = session.get(MonitoringTarget, target.id)
                processed.append(record_check(session, db_target, outcome, checked_at=state["t"]))
        with session_factory() as session:
            return session.get(MonitoringTarget, target.id), processed

    def _incidents():
        with session_factory() as session:
            return session.scalars(select(Incident).order_by(Incident.opened_at)).all()

    _run.incidents = _incidents
    _run.target = target
    return _run


def test_single_failure_does_not_open_incident(run):
    target, _ = run(FAIL)
    assert target.status == TargetStatus.UNKNOWN
    assert target.consecutive_failures == 1
    assert run.incidents() == []


def test_two_consecutive_failures_open_incident(run):
    target, processed = run(FAIL, TIMEOUT)
    assert target.status == TargetStatus.DOWN
    [incident] = run.incidents()
    assert processed[1].opened_incident is not None
    assert incident.status == IncidentStatus.OPEN
    assert incident.failure_reason == "Timeout after 5s"
    assert incident.target_name == "api"
    assert incident.opened_at == target.last_checked_at
    assert incident.resolved_at is None


def test_no_duplicate_open_incidents(run):
    target, processed = run(FAIL, FAIL, FAIL, FAIL)
    assert len(run.incidents()) == 1
    assert [p.opened_incident is not None for p in processed] == [False, True, False, False]
    assert target.consecutive_failures == 4


def test_single_success_does_not_resolve(run):
    target, _ = run(FAIL, FAIL, OK)
    assert target.status == TargetStatus.DOWN
    assert run.incidents()[0].status == IncidentStatus.OPEN


def test_two_consecutive_successes_resolve_incident(run):
    target, processed = run(FAIL, FAIL, OK, OK)
    [incident] = run.incidents()
    assert target.status == TargetStatus.UP
    assert incident.status == IncidentStatus.RESOLVED
    assert incident.resolved_at == target.last_checked_at
    assert incident.resolved_at > incident.opened_at
    assert "2 consecutive successful checks" in incident.resolution_reason
    assert processed[3].resolved_incident is not None


def test_interrupted_recovery_needs_two_fresh_successes(run):
    target, _ = run(FAIL, FAIL, OK, FAIL, OK)
    assert target.status == TargetStatus.DOWN
    assert run.incidents()[0].status == IncidentStatus.OPEN
    target, _ = run(OK)
    assert target.status == TargetStatus.UP
    assert run.incidents()[0].status == IncidentStatus.RESOLVED


def test_alternating_results_never_open_incident(run):
    target, _ = run(OK, FAIL, OK, FAIL, OK)
    assert target.status == TargetStatus.UP
    assert run.incidents() == []


def test_success_without_incident_marks_up_immediately(run):
    target, _ = run(OK)
    assert target.status == TargetStatus.UP
    assert target.consecutive_successes == 1


def test_incident_history_is_preserved_across_outages(run):
    run(FAIL, FAIL, OK, OK, FAIL, FAIL)
    incidents = run.incidents()
    assert [i.status for i in incidents] == [IncidentStatus.RESOLVED, IncidentStatus.OPEN]


def test_every_check_is_persisted(run, session_factory):
    run(FAIL, OK, TIMEOUT)
    with session_factory() as session:
        results = session.scalars(
            select(MonitoringResult).order_by(MonitoringResult.checked_at)
        ).all()
    assert [(r.success, r.status_code, r.error) for r in results] == [
        (False, 503, "HTTP 503"),
        (True, 200, None),
        (False, None, "Timeout after 5s"),
    ]


def test_custom_thresholds(session_factory, make_target):
    target = make_target()
    with session_factory() as session, session.begin():
        db_target = session.get(MonitoringTarget, target.id)
        result = record_check(session, db_target, FAIL, checked_at=utcnow(), failure_threshold=1)
    assert result.opened_incident is not None


def test_database_enforces_single_open_incident(session_factory, make_target):
    target = make_target()
    with session_factory() as session:
        for _ in range(2):
            session.add(
                Incident(
                    target_id=target.id,
                    target_name=target.name,
                    status=IncidentStatus.OPEN,
                    opened_at=utcnow(),
                    failure_reason="x",
                )
            )
        with pytest.raises(IntegrityError):
            session.commit()
