from app import app

def test_health_endpoint():
    client = app.test_client()
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["app"] == "DBAMonitor"

def test_home_page():
    client = app.test_client()
    response = client.get("/")
    assert response.status_code == 200
    assert b"DBAMonitor" in response.data

def test_overview_without_database_is_demo():
    client = app.test_client()
    response = client.get("/api/overview")
    assert response.status_code == 200
    data = response.get_json()
    assert "status" in data
    assert "metrics" in data
