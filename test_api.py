"""
Tests para FocusFlow backend.
Ejecutar: cd backend && pip install pytest httpx && pytest test_api.py -v
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from main import app
from database import Base, get_db

# ─── Base de datos en memoria para tests ─────────────────────────────────────
# StaticPool: todas las conexiones del TestClient comparten la misma conexión
# in-memory, evitando que cada request vea una DB vacía.

engine_test = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine_test)


def override_get_db():
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine_test)
    yield
    Base.metadata.drop_all(bind=engine_test)


client = TestClient(app)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _register(username="alice", password="pass123"):
    res = client.post("/api/users/register", json={
        "username": username,
        "display_name": "Alice",
        "password": password,
    })
    assert res.status_code == 200, res.text
    return res.json()


def _auth_header(token):
    return {"X-Token": token}


# ─── Auth ─────────────────────────────────────────────────────────────────────

def test_register_and_login():
    data = _register()
    assert "token" in data
    assert data["user"]["username"] == "alice"

    res = client.post("/api/users/login", json={"username": "alice", "password": "pass123"})
    assert res.status_code == 200
    assert "token" in res.json()


def test_login_wrong_password():
    _register()
    res = client.post("/api/users/login", json={"username": "alice", "password": "wrong"})
    assert res.status_code == 401


def test_duplicate_username():
    _register()
    res = client.post("/api/users/register", json={
        "username": "alice",
        "display_name": "Alice 2",
        "password": "other",
    })
    assert res.status_code == 400


# ─── Challenge date validation ────────────────────────────────────────────────

def test_challenge_start_before_end():
    alice = _register("alice2")
    bob = _register("bob2", "bpass")
    headers = _auth_header(alice["token"])

    res = client.post("/api/social/challenges", json={
        "title": "Who finishes first",
        "challenged_username": "bob2",
        "type": "blocks",
        "target": 10,
        "start_date": "2026-04-01",
        "end_date": "2026-04-30",
    }, headers=headers)
    assert res.status_code == 200


def test_challenge_end_before_start_rejected():
    alice = _register("alice3")
    bob = _register("bob3", "bpass")
    headers = _auth_header(alice["token"])

    res = client.post("/api/social/challenges", json={
        "title": "Bad dates",
        "challenged_username": "bob3",
        "type": "blocks",
        "target": 10,
        "start_date": "2026-04-30",
        "end_date": "2026-04-01",  # end < start → debe fallar
    }, headers=headers)
    assert res.status_code == 400
    assert "start_date" in res.json()["detail"].lower()


def test_challenge_same_date_rejected():
    alice = _register("alice4")
    bob = _register("bob4", "bpass")
    headers = _auth_header(alice["token"])

    res = client.post("/api/social/challenges", json={
        "title": "Same day",
        "challenged_username": "bob4",
        "type": "tasks",
        "target": 5,
        "start_date": "2026-04-14",
        "end_date": "2026-04-14",  # start == end → debe fallar
    }, headers=headers)
    assert res.status_code == 400


def test_challenge_invalid_date_format():
    alice = _register("alice5")
    bob = _register("bob5", "bpass")
    headers = _auth_header(alice["token"])

    res = client.post("/api/social/challenges", json={
        "title": "Bad format",
        "challenged_username": "bob5",
        "type": "blocks",
        "target": 10,
        "start_date": "14-04-2026",  # formato incorrecto
        "end_date": "2026-04-30",
    }, headers=headers)
    assert res.status_code == 400


# ─── Admin endpoints requieren auth ──────────────────────────────────────────

def test_list_users_requires_auth():
    res = client.get("/api/users/")
    assert res.status_code == 401


def test_list_users_with_valid_token():
    data = _register("admin_user")
    res = client.get("/api/users/", headers=_auth_header(data["token"]))
    assert res.status_code == 200
    assert isinstance(res.json(), list)
