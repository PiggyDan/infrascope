from sqlalchemy.exc import OperationalError


def test_health_reports_ok_with_database(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["monitor"] == "disabled"


def test_health_returns_503_when_database_unavailable(client, app, monkeypatch):
    class BrokenSession:
        def execute(self, *_args, **_kwargs):
            raise OperationalError("SELECT 1", {}, Exception("connection refused"))

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

    monkeypatch.setattr(app.state, "session_factory", BrokenSession)
    response = client.get("/health")
    assert response.status_code == 503
    assert response.json()["database"] == "unavailable"


def test_openapi_docs_available(client):
    assert client.get("/docs").status_code == 200
    paths = client.get("/openapi.json").json()["paths"]
    for path in [
        "/health",
        "/api/v1/targets",
        "/api/v1/targets/{target_id}",
        "/api/v1/targets/{target_id}/results",
        "/api/v1/incidents",
        "/api/v1/summary",
    ]:
        assert path in paths
