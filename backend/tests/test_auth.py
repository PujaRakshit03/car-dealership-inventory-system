import bcrypt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.main import app
from backend.models import User


@pytest.fixture
def client(tmp_path, monkeypatch):
    database_path = tmp_path / "auth.sqlite3"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("JWT_SECRET_KEY", "test-only-secret-key")

    with TestClient(app) as test_client:
        yield test_client


def test_user_can_register(client: TestClient) -> None:
    password = "secure-password"
    response = client.post(
        "/auth/register",
        json={"username": "dealer", "password": password},
    )

    assert response.status_code == 201
    assert response.json()["username"] == "dealer"
    assert "password" not in response.json()
    with client.app.state.session_factory() as session:
        user = session.scalar(select(User).where(User.username == "dealer"))
    assert user is not None
    assert user.hashed_password != password
    assert bcrypt.checkpw(password.encode(), user.hashed_password.encode())


def test_user_can_login_and_access_protected_route(client: TestClient) -> None:
    credentials = {"username": "dealer", "password": "secure-password"}
    client.post("/auth/register", json=credentials)

    login_response = client.post("/auth/login", json=credentials)

    assert login_response.status_code == 200
    token_data = login_response.json()
    assert token_data["access_token"]
    assert token_data["token_type"] == "bearer"

    protected_response = client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {token_data['access_token']}"},
    )

    assert protected_response.status_code == 200
    assert protected_response.json()["username"] == credentials["username"]


def test_login_rejects_invalid_credentials(client: TestClient) -> None:
    client.post(
        "/auth/register",
        json={"username": "dealer", "password": "secure-password"},
    )

    response = client.post(
        "/auth/login",
        json={"username": "dealer", "password": "wrong-password"},
    )

    assert response.status_code == 401


@pytest.mark.parametrize("authorization", [None, "Bearer invalid-token"])
def test_protected_route_rejects_missing_or_invalid_token(
    client: TestClient,
    authorization: str | None,
) -> None:
    headers = {} if authorization is None else {"Authorization": authorization}

    response = client.get("/auth/me", headers=headers)

    assert response.status_code == 401
