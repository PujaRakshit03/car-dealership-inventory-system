import os
import logging
import secrets
from collections.abc import AsyncIterator, Generator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import create_engine, inspect, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from .models import Base, User, Vehicle
from .security import ALGORITHM, create_access_token, hash_password, verify_password

logger = logging.getLogger(__name__)


class VehicleCreate(BaseModel):
    make: str
    model: str
    year: int
    price: float
    quantity: int


class VehicleRead(VehicleCreate):
    id: int

    model_config = ConfigDict(from_attributes=True)


class RestockRequest(BaseModel):
    quantity: int = Field(gt=0)


class PurchaseRequest(BaseModel):
    quantity: int = Field(gt=0)


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
    if "role" not in {column["name"] for column in inspect(engine).get_columns("users")}:
        with engine.begin() as connection:
            connection.execute(
                text("ALTER TABLE users ADD COLUMN role VARCHAR(16) NOT NULL DEFAULT 'user'")
            )
    app.state.session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    app.state.jwt_secret_key = os.getenv("JWT_SECRET_KEY") or secrets.token_urlsafe(32)
    admin_username = os.getenv("ADMIN_USERNAME")
    admin_password = os.getenv("ADMIN_PASSWORD")
    if admin_username and admin_password:
        if len(admin_password.encode("utf-8")) > 72:
            raise ValueError("ADMIN_PASSWORD must be at most 72 bytes when encoded as UTF-8")
        with app.state.session_factory() as session:
            existing_admin = session.scalar(
                select(User).where(User.username == admin_username)
            )
            if existing_admin is None:
                session.add(
                    User(
                        username=admin_username,
                        hashed_password=hash_password(admin_password),
                        role="admin",
                    )
                )
                session.commit()
    else:
        logger.warning(
            "Administrator bootstrap skipped: both ADMIN_USERNAME and ADMIN_PASSWORD must be configured."
        )

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
    db_user = User(
        username=user.username,
        hashed_password=hash_password(user.password),
        role="user",
    )
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


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator privileges required",
        )
    return current_user


@app.get("/auth/me", response_model=UserIdentity)
def read_current_user(current_user: User = Depends(get_current_user)) -> User:
    return current_user


@app.get("/vehicles", response_model=list[VehicleRead])
def list_vehicles(
    make: str | None = None,
    model: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    session: Session = Depends(get_session),
) -> list[Vehicle]:
    query = select(Vehicle)
    if make:
        query = query.where(Vehicle.make.ilike(f"%{make}%"))
    if model:
        query = query.where(Vehicle.model.ilike(f"%{model}%"))
    if min_price is not None:
        query = query.where(Vehicle.price >= min_price)
    if max_price is not None:
        query = query.where(Vehicle.price <= max_price)
    return list(session.scalars(query.order_by(Vehicle.id)).all())


@app.post("/vehicles", response_model=VehicleRead, status_code=status.HTTP_201_CREATED)
def create_vehicle(
    vehicle: VehicleCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> Vehicle:
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


@app.put("/vehicles/{vehicle_id}", response_model=VehicleRead)
def update_vehicle(
    vehicle_id: int,
    vehicle_update: VehicleCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> Vehicle:
    vehicle = session.get(Vehicle, vehicle_id)
    if vehicle is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle not found")
    for field, value in vehicle_update.model_dump().items():
        setattr(vehicle, field, value)
    session.commit()
    session.refresh(vehicle)
    return vehicle


@app.delete("/vehicles/{vehicle_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_vehicle(
    vehicle_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_admin),
) -> None:
    vehicle = session.get(Vehicle, vehicle_id)
    if vehicle is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle not found")
    session.delete(vehicle)
    session.commit()


@app.post("/vehicles/{vehicle_id}/restock", response_model=VehicleRead)
def restock_vehicle(
    vehicle_id: int,
    restock: RestockRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_admin),
) -> Vehicle:
    vehicle = session.get(Vehicle, vehicle_id)
    if vehicle is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle not found")
    vehicle.quantity += restock.quantity
    session.commit()
    session.refresh(vehicle)
    return vehicle


@app.post("/vehicles/{vehicle_id}/purchase", response_model=VehicleRead)
def purchase_vehicle(
    vehicle_id: int,
    purchase: PurchaseRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> Vehicle:
    result = session.execute(
        update(Vehicle)
        .where(
            Vehicle.id == vehicle_id,
            Vehicle.quantity >= purchase.quantity,
        )
        .values(quantity=Vehicle.quantity - purchase.quantity)
    )
    if result.rowcount == 0:
        if session.get(Vehicle, vehicle_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle not found")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Insufficient vehicle inventory",
        )

    session.commit()
    vehicle = session.get(Vehicle, vehicle_id)
    return vehicle
