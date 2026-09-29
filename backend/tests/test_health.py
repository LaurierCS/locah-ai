from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import get_db
from app.main import app

client = TestClient(app)

# Mock DB session for testing
# Updated to use postgresql+psycopg (v3) to match project dependencies
TEST_DATABASE_URL = "postgresql+psycopg://user:pass@localhost:5432/test_db"
engine = create_engine(TEST_DATABASE_URL)
TestingSessionLocal = sessionmaker(bind=engine)


def override_get_db():
    try:
        db = TestingSessionLocal()
        yield db
        db.close()
    except RuntimeError as e:
        # Simulate DB failure in some tests
        raise RuntimeError(f"DB Connection Failed: {e}")


app.dependency_overrides[get_db] = override_get_db


def test_health_endpoint_structure():
    """Verify the endpoint exists and returns the correct JSON keys."""
    # We mock a failure here just to see if it returns the 'degraded' status
    # as we don't have a real test DB running in this environment.
    response = client.get("/api/v1/health")

    # Since TEST_DATABASE_URL is fake, it should return 503 degraded
    assert response.status_code == 503
    data = response.json()
    assert "status" in data
    assert data["status"] == "degraded"


def test_health_ok_mock(monkeypatch):
    """
    Verify 200 OK when database queries return successfully.
    Using monkeypatch instead of mocker to avoid dependency on pytest-mock.
    """

    class MockDB:
        def execute(self, query):
            class Result:
                def scalar(self):
                    return "2026-09-29T10:00:00Z"

            return Result()

    mock_db = MockDB()

    # Override the dependency to return our mock session
    app.dependency_overrides[get_db] = lambda: mock_db

    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "last_crawl_at" in data
    assert "active_documents" in data


def test_health_degraded_mock(monkeypatch):
    """Verify 503 degraded when DB throws an exception."""

    class MockDB:
        def execute(self, query):
            raise RuntimeError("Connection refused")

    mock_db = MockDB()

    app.dependency_overrides[get_db] = lambda: [mock_db]

    response = client.get("/api/v1/health")
    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "degraded"
