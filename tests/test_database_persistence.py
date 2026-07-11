from fastapi.testclient import TestClient

from backend.main import app


def test_database_status_endpoint_reports_persistence():
    with TestClient(app) as client:
        response = client.get("/api/v1/system/db-status")

    assert response.status_code == 200
    body = response.json()
    assert "database_path" in body
    assert "exists" in body
    assert "case_count" in body
