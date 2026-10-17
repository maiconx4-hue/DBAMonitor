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


def test_db_check_endpoint_returns_connection_state():
    client = app.test_client()
    response = client.get("/api/db-check")
    assert response.status_code == 200
    data = response.get_json()
    assert "connected" in data
    assert "mode" in data
    assert "message" in data


def test_overview_contains_dashboard_sections():
    client = app.test_client()
    response = client.get("/api/overview")
    assert response.status_code == 200
    data = response.get_json()
    assert {"status", "metrics", "tables", "mode"}.issubset(data)
    assert {"database_size", "active_connections", "table_count", "index_count", "cache_hit_ratio"}.issubset(data["metrics"])


def test_persistent_history_endpoint():
    response = app.test_client().get("/api/history?limit=10")
    assert response.status_code == 200
    data = response.get_json()
    assert data["persistent"] is True
    assert isinstance(data["samples"], list)


def test_diagnostics_endpoint_is_safe_without_database():
    response = app.test_client().get("/api/diagnostics")
    assert response.status_code == 200
    data = response.get_json()
    assert "slow_queries" in data
    assert "blocking" in data
    assert "alerts" in data


def test_backups_endpoint_explains_manual_validation():
    response = app.test_client().get("/api/backups")
    assert response.status_code == 200
    data = response.get_json()
    assert "checks" in data
    assert "recommendations" in data
    assert "restaurações" in data["warning"]
