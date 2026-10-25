from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.main import app
from backend.models import Vehicle


@pytest.fixture
def client(tmp_path, monkeypatch):
    database_path = tmp_path / "acid-tests.sqlite3"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("JWT_SECRET_KEY", "acid-test-secret")
    monkeypatch.delenv("ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def user_headers(client: TestClient) -> dict[str, str]:
    credentials = {"username": "acid-buyer", "password": "acid-test-password"}
    registered = client.post("/auth/register", json=credentials)
    assert registered.status_code == 201
    login = client.post("/auth/login", json=credentials)
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def create_vehicle(
    client: TestClient,
    headers: dict[str, str],
    quantity: int,
) -> int:
    response = client.post(
        "/vehicles",
        json={
            "make": "Test",
            "model": "ACID",
            "year": 2025,
            "price": 25000,
            "quantity": quantity,
        },
        headers=headers,
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_failed_purchase_leaves_database_state_unchanged(
    client: TestClient,
    user_headers: dict[str, str],
) -> None:
    vehicle_id = create_vehicle(client, user_headers, quantity=2)

    response = client.post(
        f"/vehicles/{vehicle_id}/purchase",
        json={"quantity": 3},
        headers=user_headers,
    )

    assert response.status_code == 409
    with client.app.state.session_factory() as session:
        persisted_vehicle = session.get(Vehicle, vehicle_id)
        assert persisted_vehicle is not None
        assert (
            persisted_vehicle.make,
            persisted_vehicle.model,
            persisted_vehicle.year,
            persisted_vehicle.price,
            persisted_vehicle.quantity,
        ) == ("Test", "ACID", 2025, 25000, 2)
        assert session.scalar(select(Vehicle).where(Vehicle.id != vehicle_id)) is None


@pytest.mark.parametrize("quantity", [0, -1])
def test_invalid_purchase_quantity_does_not_change_database(
    client: TestClient,
    user_headers: dict[str, str],
    quantity: int,
) -> None:
    vehicle_id = create_vehicle(client, user_headers, quantity=2)

    response = client.post(
        f"/vehicles/{vehicle_id}/purchase",
        json={"quantity": quantity},
        headers=user_headers,
    )

    assert response.status_code == 422
    with client.app.state.session_factory() as session:
        vehicle = session.get(Vehicle, vehicle_id)
        assert vehicle is not None
        assert vehicle.quantity == 2


def test_concurrent_purchases_cannot_oversell_inventory(
    client: TestClient,
    user_headers: dict[str, str],
) -> None:
    available = 5
    request_count = 20
    vehicle_id = create_vehicle(client, user_headers, quantity=available)
    start_together = Barrier(request_count)

    def purchase_one() -> int:
        start_together.wait(timeout=15)
        response = client.post(
            f"/vehicles/{vehicle_id}/purchase",
            json={"quantity": 1},
            headers=user_headers,
        )
        return response.status_code

    with ThreadPoolExecutor(max_workers=request_count) as executor:
        statuses = list(executor.map(lambda _: purchase_one(), range(request_count)))

    successful_purchases = statuses.count(200)
    assert successful_purchases == available
    assert statuses.count(409) == request_count - available
    assert set(statuses) == {200, 409}

    with client.app.state.session_factory() as session:
        persisted_vehicle = session.get(Vehicle, vehicle_id)
        assert persisted_vehicle is not None
        assert persisted_vehicle.quantity == 0


def test_vehicle_is_durable_across_independent_sessions(
    client: TestClient,
) -> None:
    factory = client.app.state.session_factory
    with factory() as creating_session:
        vehicle = Vehicle(
            make="Durable",
            model="Record",
            year=2022,
            price=31999.5,
            quantity=7,
        )
        creating_session.add(vehicle)
        creating_session.commit()
        vehicle_id = vehicle.id

    with factory() as fresh_session:
        persisted_vehicle = fresh_session.scalar(
            select(Vehicle).where(Vehicle.id == vehicle_id)
        )

        assert persisted_vehicle is not None
        assert persisted_vehicle.make == "Durable"
        assert persisted_vehicle.model == "Record"
        assert persisted_vehicle.year == 2022
        assert persisted_vehicle.price == 31999.5
        assert persisted_vehicle.quantity == 7
