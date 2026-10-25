import bcrypt
from jose import jwt

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    password_bytes = password.encode("utf-8")
    if len(password_bytes) > 72:
        raise ValueError("Password must be at most 72 bytes when encoded as UTF-8")
    return bcrypt.hashpw(password_bytes, bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed_password.encode("ascii"))
    except (UnicodeEncodeError, ValueError):
        return False


def create_access_token(subject: str, secret_key: str, expires_at: int) -> str:
    return jwt.encode(
        {"sub": subject, "exp": expires_at},
        secret_key,
        algorithm=ALGORITHM,
    )
