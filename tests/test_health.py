def test_liveness(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["service"] == "Auspex"


def test_readiness_checks_postgres_and_opensearch(client):
    resp = client.get("/api/health/ready")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ready"
    assert body["checks"]["postgres"]["ok"] is True
    assert body["checks"]["opensearch"]["ok"] is True


def test_readiness_degrades_to_503_when_a_dependency_is_down():
    """The 503/degraded branch must actually fire — point OpenSearch at a dead port."""
    from fastapi.testclient import TestClient

    from auspex.app import create_app
    from auspex.config import get_settings

    good = get_settings()
    broken = get_settings().model_copy(update={"opensearch_url": "http://127.0.0.1:1"})
    # Keep the real (working) DB DSN so startup/migrations succeed; only OpenSearch is dead.
    assert broken.database_url == good.database_url
    with TestClient(create_app(broken)) as degraded:
        resp = degraded.get("/api/health/ready")
        assert resp.status_code == 503, resp.text
        body = resp.json()
        assert body["status"] == "degraded"
        assert body["checks"]["opensearch"]["ok"] is False
        assert body["checks"]["postgres"]["ok"] is True
