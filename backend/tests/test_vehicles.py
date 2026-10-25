import pytest
from fastapi.testclient import TestClient

from backend.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    database_path = tmp_path / "vehicles.sqlite3"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("JWT_SECRET_KEY", "vehicle-test-secret")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "admin-password")

    with TestClient(app) as test_client:
        yield test_client


def register_and_login(client: TestClient, username: str, password: str) -> str:
    registration = client.post(
        "/auth/register",
        json={"username": username, "password": password},
    )
    assert registration.status_code == 201
    login = client.post(
        "/auth/login",
        json={"username": username, "password": password},
    )
    assert login.status_code == 200
    return login.json()["access_token"]


def admin_headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/auth/login",
        json={"username": "admin", "password": "admin-password"},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_vehicle_can_be_created_and_retrieved(client: TestClient) -> None:
    token = register_and_login(client, "dealer", "dealer-password")
    headers = {"Authorization": f"Bearer {token}"}
    vehicle = {
        "make": "Toyota",
        "model": "Camry",
        "year": 2024,
        "price": 28500.00,
        "quantity": 3,
    }

    create_response = client.post("/vehicles", json=vehicle, headers=headers)

    assert create_response.status_code == 201
    vehicle_id = create_response.json()["id"]

    retrieve_response = client.get(f"/vehicles/{vehicle_id}")

    assert retrieve_response.status_code == 200
    assert retrieve_response.json() == {"id": vehicle_id, **vehicle}


def test_vehicle_creation_requires_authentication(client: TestClient) -> None:
    response = client.post(
        "/vehicles",
        json={"make": "Honda", "model": "Civic", "year": 2023, "price": 22000, "quantity": 1},
    )

    assert response.status_code == 401


def test_vehicle_update_requires_authentication(client: TestClient) -> None:
    headers = {"Authorization": f"Bearer {register_and_login(client, 'dealer', 'dealer-password')}"}
    created = client.post(
        "/vehicles",
        json={"make": "Honda", "model": "Civic", "year": 2023, "price": 22000, "quantity": 1},
        headers=headers,
    )

    response = client.put(
        f"/vehicles/{created.json()['id']}",
        json={"make": "Honda", "model": "Accord", "year": 2023, "price": 26000, "quantity": 1},
    )

    assert response.status_code == 401


def test_authenticated_user_can_update_vehicle(client: TestClient) -> None:
    headers = {"Authorization": f"Bearer {register_and_login(client, 'dealer', 'dealer-password')}"}
    created = client.post(
        "/vehicles",
        json={"make": "Honda", "model": "Civic", "year": 2023, "price": 22000, "quantity": 1},
        headers=headers,
    )

    response = client.put(
        f"/vehicles/{created.json()['id']}",
        json={"make": "Honda", "model": "Accord", "year": 2024, "price": 27000, "quantity": 2},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["model"] == "Accord"
    assert response.json()["quantity"] == 2


def test_vehicle_listing_filters_by_make_model_and_price(client: TestClient) -> None:
    headers = {"Authorization": f"Bearer {register_and_login(client, 'dealer', 'dealer-password')}"}
    vehicles = [
        {"make": "Toyota", "model": "Camry", "year": 2024, "price": 28000, "quantity": 2},
        {"make": "Toyota", "model": "Corolla", "year": 2023, "price": 22000, "quantity": 4},
        {"make": "Honda", "model": "Civic", "year": 2024, "price": 24000, "quantity": 1},
    ]
    for vehicle in vehicles:
        response = client.post("/vehicles", json=vehicle, headers=headers)
        assert response.status_code == 201

    response = client.get(
        "/vehicles",
        params={"make": "Toyota", "model": "Cam", "min_price": 25000, "max_price": 30000},
    )

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["model"] == "Camry"


def test_admin_can_delete_vehicle_but_regular_user_cannot(client: TestClient) -> None:
    user_headers = {
        "Authorization": f"Bearer {register_and_login(client, 'dealer', 'dealer-password')}"
    }
    vehicle_response = client.post(
        "/vehicles",
        json={"make": "Honda", "model": "Civic", "year": 2023, "price": 22000, "quantity": 1},
        headers=user_headers,
    )
    vehicle_id = vehicle_response.json()["id"]

    forbidden = client.delete(f"/vehicles/{vehicle_id}", headers=user_headers)
    assert forbidden.status_code == 403

    deleted = client.delete(f"/vehicles/{vehicle_id}", headers=admin_headers(client))

    assert deleted.status_code == 204
    assert client.get(f"/vehicles/{vehicle_id}").status_code == 404


def test_admin_can_restock_but_regular_user_cannot(client: TestClient) -> None:
    user_headers = {
        "Authorization": f"Bearer {register_and_login(client, 'dealer', 'dealer-password')}"
    }
    vehicle_response = client.post(
        "/vehicles",
        json={"make": "Honda", "model": "Civic", "year": 2023, "price": 22000, "quantity": 1},
        headers=user_headers,
    )
    vehicle_id = vehicle_response.json()["id"]

    forbidden = client.post(
        f"/vehicles/{vehicle_id}/restock",
        json={"quantity": 5},
        headers=user_headers,
    )
    assert forbidden.status_code == 403

    restocked = client.post(
        f"/vehicles/{vehicle_id}/restock",
        json={"quantity": 5},
        headers=admin_headers(client),
    )

    assert restocked.status_code == 200
    assert restocked.json()["quantity"] == 6


def test_deletion_and_restock_require_authentication(client: TestClient) -> None:
    user_headers = {
        "Authorization": f"Bearer {register_and_login(client, 'dealer', 'dealer-password')}"
    }
    vehicle_response = client.post(
        "/vehicles",
        json={"make": "Honda", "model": "Civic", "year": 2023, "price": 22000, "quantity": 1},
        headers=user_headers,
    )
    vehicle_id = vehicle_response.json()["id"]

    assert client.delete(f"/vehicles/{vehicle_id}").status_code == 401
    assert client.post(
        f"/vehicles/{vehicle_id}/restock",
        json={"quantity": 1},
    ).status_code == 401


def test_authenticated_user_can_purchase_vehicle_and_inventory_decreases(
    client: TestClient,
) -> None:
    headers = {"Authorization": f"Bearer {register_and_login(client, 'buyer', 'buyer-password')}"}
    created = client.post(
        "/vehicles",
        json={"make": "Toyota", "model": "Camry", "year": 2024, "price": 28000, "quantity": 5},
        headers=headers,
    )

    response = client.post(
        f"/vehicles/{created.json()['id']}/purchase",
        json={"quantity": 2},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["quantity"] == 3
    assert client.get(f"/vehicles/{created.json()['id']}").json()["quantity"] == 3


def test_purchase_rejects_insufficient_stock_without_changing_inventory(
    client: TestClient,
) -> None:
    headers = {"Authorization": f"Bearer {register_and_login(client, 'buyer', 'buyer-password')}"}
    created = client.post(
        "/vehicles",
        json={"make": "Toyota", "model": "Camry", "year": 2024, "price": 28000, "quantity": 2},
        headers=headers,
    )
    vehicle_id = created.json()["id"]

    response = client.post(
        f"/vehicles/{vehicle_id}/purchase",
        json={"quantity": 3},
        headers=headers,
    )

    assert response.status_code == 409
    assert client.get(f"/vehicles/{vehicle_id}").json()["quantity"] == 2


@pytest.mark.parametrize("quantity", [0, -1])
def test_purchase_rejects_zero_or_negative_quantity(
    client: TestClient,
    quantity: int,
) -> None:
    headers = {"Authorization": f"Bearer {register_and_login(client, 'buyer', 'buyer-password')}"}

    response = client.post(
        "/vehicles/1/purchase",
        json={"quantity": quantity},
        headers=headers,
    )

    assert response.status_code == 422


def test_purchase_returns_not_found_for_missing_vehicle(client: TestClient) -> None:
    headers = {"Authorization": f"Bearer {register_and_login(client, 'buyer', 'buyer-password')}"}

    response = client.post(
        "/vehicles/999/purchase",
        json={"quantity": 1},
        headers=headers,
    )

    assert response.status_code == 404


def test_purchase_requires_authentication(client: TestClient) -> None:
    response = client.post(
        "/vehicles/1/purchase",
        json={"quantity": 1},
    )

    assert response.status_code == 401
