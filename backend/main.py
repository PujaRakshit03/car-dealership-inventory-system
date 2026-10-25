import os
import secrets
from collections.abc import AsyncIterator, Generator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from .models import Base, User, Vehicle
from .security import ALGORITHM, create_access_token, hash_password, verify_password


class VehicleCreate(BaseModel):
    make: str
    model: str
    year: int
    price: float
    quantity: int


class VehicleRead(VehicleCreate):
    id: int

    model_config = ConfigDict(from_attributes=True)


class UserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8)

    @field_validator("password")
    @classmethod
    def validate_password_length(cls, password: str) -> str:
        if len(password.encode("utf-8")) > 72:
            raise ValueError("Password must be at most 72 bytes when encoded as UTF-8")
        return password


class UserRead(BaseModel):
    id: int
    username: str

    model_config = ConfigDict(from_attributes=True)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str


class UserIdentity(BaseModel):
    id: int
    username: str

    model_config = ConfigDict(from_attributes=True)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    database_url = os.getenv("DATABASE_URL", "sqlite:///./vehicles.db")
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, connect_args=connect_args)
    Base.metadata.create_all(bind=engine)
    app.state.session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    app.state.jwt_secret_key = os.getenv("JWT_SECRET_KEY") or secrets.token_urlsafe(32)

    try:
        yield
    finally:
        engine.dispose()


def get_session(request: Request) -> Generator[Session, None, None]:
    with request.app.state.session_factory() as session:
        yield session


app = FastAPI(lifespan=lifespan)
bearer_scheme = HTTPBearer(auto_error=False)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/auth/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def register_user(user: UserCreate, session: Session = Depends(get_session)) -> User:
    db_user = User(username=user.username, hashed_password=hash_password(user.password))
    session.add(db_user)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already registered")
    session.refresh(db_user)
    return db_user


@app.post("/auth/login", response_model=TokenResponse)
def login(user: UserCreate, request: Request, session: Session = Depends(get_session)) -> TokenResponse:
    db_user = session.scalar(select(User).where(User.username == user.username))
    if db_user is None or not verify_password(user.password, db_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)
    access_token = create_access_token(
        str(db_user.id),
        request.app.state.jwt_secret_key,
        int(expires_at.timestamp()),
    )
    return TokenResponse(access_token=access_token, token_type="bearer")


def get_current_user(
    request: Request,
    session: Session = Depends(get_session),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> User:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing bearer token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise unauthorized

    try:
        payload = jwt.decode(
            credentials.credentials,
            request.app.state.jwt_secret_key,
            algorithms=[ALGORITHM],
        )
        subject = payload.get("sub")
        if not isinstance(subject, str):
            raise unauthorized
        user_id = int(subject)
    except (JWTError, ValueError):
        raise unauthorized

    user = session.get(User, user_id)
    if user is None:
        raise unauthorized
    return user


@app.get("/auth/me", response_model=UserIdentity)
def read_current_user(current_user: User = Depends(get_current_user)) -> User:
    return current_user


@app.post("/vehicles", response_model=VehicleRead, status_code=status.HTTP_201_CREATED)
def create_vehicle(vehicle: VehicleCreate, session: Session = Depends(get_session)) -> Vehicle:
    db_vehicle = Vehicle(**vehicle.model_dump())
    session.add(db_vehicle)
    session.commit()
    session.refresh(db_vehicle)
    return db_vehicle


@app.get("/vehicles/{vehicle_id}", response_model=VehicleRead)
def read_vehicle(vehicle_id: int, session: Session = Depends(get_session)) -> Vehicle:
    vehicle = session.get(Vehicle, vehicle_id)
    if vehicle is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle not found")
    return vehicle
