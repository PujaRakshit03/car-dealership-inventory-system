import pytest
from fastapi.testclient import TestClient

from backend.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    database_path = tmp_path / "vehicles.sqlite3"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")

    with TestClient(app) as test_client:
        yield test_client


def test_vehicle_can_be_created_and_retrieved(client: TestClient) -> None:
    vehicle = {
        "make": "Toyota",
        "model": "Camry",
        "year": 2024,
        "price": 28500.00,
        "quantity": 3,
    }

    create_response = client.post("/vehicles", json=vehicle)

    assert create_response.status_code == 201
    vehicle_id = create_response.json()["id"]

    retrieve_response = client.get(f"/vehicles/{vehicle_id}")

    assert retrieve_response.status_code == 200
    assert retrieve_response.json() == {"id": vehicle_id, **vehicle}
