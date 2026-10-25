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
    monkeypatch.delenv("ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)

    with TestClient(app) as test_client:
        yield test_client


def test_user_can_register(client: TestClient) -> None:
    password = "secure-password"
    response = client.post(
        "/auth/register",
        json={"username": "dealer", "password": password, "role": "admin"},
    )

    assert response.status_code == 201
    assert response.json()["username"] == "dealer"
    assert "password" not in response.json()
    with client.app.state.session_factory() as session:
        user = session.scalar(select(User).where(User.username == "dealer"))
    assert user is not None
    assert user.role == "user"
    assert user.hashed_password != password
    assert bcrypt.checkpw(password.encode(), user.hashed_password.encode())


def test_startup_bootstraps_admin_from_environment(tmp_path, monkeypatch) -> None:
    database_path = tmp_path / "bootstrap.sqlite3"
    password = "bootstrap-password"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("JWT_SECRET_KEY", "test-only-secret-key")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", password)

    with TestClient(app) as client:
        with client.app.state.session_factory() as session:
            user = session.scalar(select(User).where(User.username == "admin"))

    assert user is not None
    assert user.role == "admin"
    assert user.hashed_password != password
    assert bcrypt.checkpw(password.encode(), user.hashed_password.encode())


def test_startup_does_not_overwrite_existing_admin_username(tmp_path, monkeypatch) -> None:
    database_path = tmp_path / "existing-admin.sqlite3"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("JWT_SECRET_KEY", "test-only-secret-key")
    monkeypatch.delenv("ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)

    with TestClient(app) as client:
        response = client.post(
            "/auth/register",
            json={"username": "admin", "password": "original-password"},
        )
        assert response.status_code == 201
        with client.app.state.session_factory() as session:
            before = session.scalar(select(User).where(User.username == "admin"))
            original_hash = before.hashed_password

    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "replacement-password")
    with TestClient(app) as client:
        with client.app.state.session_factory() as session:
            existing = session.scalar(select(User).where(User.username == "admin"))

    assert existing is not None
    assert existing.role == "user"
    assert existing.hashed_password == original_hash


def test_admin_access_uses_current_database_role(tmp_path, monkeypatch) -> None:
    database_path = tmp_path / "role-change.sqlite3"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("JWT_SECRET_KEY", "test-only-secret-key")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "admin-password")
    with TestClient(app) as admin_client:
        login = admin_client.post(
            "/auth/login",
            json={"username": "admin", "password": "admin-password"},
        )
        token = login.json()["access_token"]
        with admin_client.app.state.session_factory() as session:
            admin = session.scalar(select(User).where(User.username == "admin"))
            admin.role = "user"
            session.commit()

        response = admin_client.delete(
            "/vehicles/1",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 403


def test_startup_warns_when_bootstrap_credentials_are_incomplete(
    tmp_path,
    monkeypatch,
    caplog,
) -> None:
    database_path = tmp_path / "no-admin.sqlite3"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.delenv("ADMIN_USERNAME", raising=False)
    monkeypatch.setenv("ADMIN_PASSWORD", "must-not-appear-in-logs")

    with TestClient(app) as client:
        with client.app.state.session_factory() as session:
            admin = session.scalar(select(User).where(User.role == "admin"))

    assert admin is None
    assert "ADMIN_USERNAME and ADMIN_PASSWORD" in caplog.text
    assert "must-not-appear-in-logs" not in caplog.text


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
