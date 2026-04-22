import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import bcrypt
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from database import get_db
from limiter import limiter
import models
import schemas

logger = logging.getLogger(__name__)

router = APIRouter()

_TOKEN_TTL_DAYS = 30


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _new_token() -> tuple[str, str, datetime]:
    """Returns (raw_token, token_hash, expires_at)."""
    raw = secrets.token_hex(32)
    expires = datetime.now(timezone.utc) + timedelta(days=_TOKEN_TTL_DAYS)
    return raw, _hash_token(raw), expires


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    """Verifica password migrando transparentemente hashes SHA-256 legacy a bcrypt."""
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except Exception:
        return hashlib.sha256(password.encode()).hexdigest() == password_hash


def _is_legacy_password_hash(h: str) -> bool:
    return not h.startswith("$2")


def get_current_user(
    x_token: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> models.User:
    if not x_token:
        raise HTTPException(status_code=401, detail="X-Token header required")

    token_hash = _hash_token(x_token)
    user = db.query(models.User).filter(models.User.token == token_hash).first()

    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    if user.token_expires_at and datetime.now(timezone.utc) > user.token_expires_at:
        raise HTTPException(status_code=401, detail="Token expired — please log in again")

    return user


# ─── Auth endpoints ───────────────────────────────────────────────────────────

@router.post("/register", response_model=schemas.LoginResponse, tags=["Auth"])
@limiter.limit("5/minute")
def register(request: Request, data: schemas.UserCreate, db: Session = Depends(get_db)):
    if db.query(models.User).filter(models.User.username == data.username).first():
        raise HTTPException(status_code=400, detail="Username already taken")
    if data.email and db.query(models.User).filter(models.User.email == data.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")

    raw, token_hash, expires = _new_token()
    user = models.User(
        username=data.username,
        display_name=data.display_name,
        email=data.email,
        avatar_emoji=data.avatar_emoji,
        avatar_color=data.avatar_color,
        bio=data.bio,
        password_hash=hash_password(data.password),
        token=token_hash,
        token_expires_at=expires,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"token": raw, "user": user}


@router.post("/login", response_model=schemas.LoginResponse, tags=["Auth"])
@limiter.limit("10/minute")
def login(request: Request, data: schemas.LoginRequest, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.username == data.username).first()
    if not user or not verify_password(data.password, user.password_hash):
        logger.warning("Login fallido para usuario: '%s'", data.username)
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account disabled")

    if _is_legacy_password_hash(user.password_hash):
        logger.info("Migrando hash SHA-256 → bcrypt para usuario: '%s'", data.username)
        user.password_hash = hash_password(data.password)

    raw, token_hash, expires = _new_token()
    user.token = token_hash
    user.token_expires_at = expires
    db.commit()
    db.refresh(user)
    logger.info("Login exitoso: '%s'", data.username)
    return {"token": raw, "user": user}


@router.get("/me", response_model=schemas.UserResponse, tags=["Auth"])
def get_me(current_user: models.User = Depends(get_current_user)):
    return current_user


# ─── User CRUD (requiere token válido) ───────────────────────────────────────

@router.get("/", response_model=List[schemas.UserResponse])
def list_users(
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    return db.query(models.User).order_by(models.User.created_at.desc()).all()


@router.get("/{user_id}", response_model=schemas.UserResponse)
def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.post("/", response_model=schemas.UserResponse)
def create_user(
    data: schemas.UserCreate,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    if db.query(models.User).filter(models.User.username == data.username).first():
        raise HTTPException(status_code=400, detail="Username already taken")
    _, token_hash, expires = _new_token()
    user = models.User(
        username=data.username,
        display_name=data.display_name,
        email=data.email,
        avatar_emoji=data.avatar_emoji,
        avatar_color=data.avatar_color,
        bio=data.bio,
        password_hash=hash_password(data.password),
        token=token_hash,
        token_expires_at=expires,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.put("/{user_id}", response_model=schemas.UserResponse)
def update_user(
    user_id: int,
    data: schemas.UserUpdate,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    update_data = data.model_dump(exclude_none=True)
    if "password" in update_data:
        user.password_hash = hash_password(update_data.pop("password"))
    for field, value in update_data.items():
        setattr(user, field, value)
    db.commit()
    db.refresh(user)
    return user


@router.delete("/{user_id}")
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    db.delete(user)
    db.commit()
    return {"ok": True}
