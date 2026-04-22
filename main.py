import logging
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()  # carga .env si existe; no-op en producción donde las vars vienen del host

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy.orm import Session

from limiter import limiter

from database import engine, Base, get_db
import models
from routers import tasks, categories
from routers import users, social

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("focusflow")


# ─── Admin auth ───────────────────────────────────────────────────────────────

_basic = HTTPBasic()
_ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
_ADMIN_PASS = os.environ.get("ADMIN_PASSWORD", "")


def _require_admin(credentials: HTTPBasicCredentials = Depends(_basic)) -> None:
    if not _ADMIN_PASS:
        raise HTTPException(
            status_code=503,
            detail="Admin panel disabled: set ADMIN_PASSWORD env var to enable it.",
        )
    ok_user = secrets.compare_digest(credentials.username.encode(), _ADMIN_USER.encode())
    ok_pass = secrets.compare_digest(credentials.password.encode(), _ADMIN_PASS.encode())
    if not (ok_user and ok_pass):
        raise HTTPException(
            status_code=401,
            headers={"WWW-Authenticate": "Basic"},
            detail="Invalid admin credentials",
        )


# ─── App lifecycle ────────────────────────────────────────────────────────────

def _migrate_token_expires_at() -> None:
    """Agrega la columna token_expires_at a users si no existe (SQLite legacy)."""
    try:
        with engine.connect() as conn:
            conn.execute(
                __import__("sqlalchemy").text(
                    "ALTER TABLE users ADD COLUMN token_expires_at DATETIME"
                )
            )
            conn.commit()
            logger.info("Migración: columna token_expires_at agregada a users")
    except Exception:
        pass  # La columna ya existe o el motor no la necesita (PostgreSQL usa create_all)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    _migrate_token_expires_at()
    yield


# ─── FastAPI instance ─────────────────────────────────────────────────────────

app = FastAPI(
    title="FocusFlow CMS",
    description="Content management system for the FocusFlow mobile app",
    version="2.0.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Routers ─────────────────────────────────────────────────────────────────

app.include_router(tasks.router,      prefix="/api/tasks",      tags=["Tasks"])
app.include_router(categories.router, prefix="/api/categories", tags=["Categories"])
app.include_router(users.router,      prefix="/api/users",      tags=["Users"])
app.include_router(social.router,     prefix="/api/social",     tags=["Social"])


# ─── Stats endpoint ───────────────────────────────────────────────────────────

@app.get("/api/stats", tags=["Stats"])
def get_stats(db: Session = Depends(get_db)):
    total          = db.query(models.Task).count()
    pending        = db.query(models.Task).filter(models.Task.status == 0).count()
    in_progress    = db.query(models.Task).filter(models.Task.status == 1).count()
    completed      = db.query(models.Task).filter(models.Task.status == 2).count()
    category_count = db.query(models.Category).count()
    user_count     = db.query(models.User).count()

    return {
        "total": total,
        "pending": pending,
        "in_progress": in_progress,
        "completed": completed,
        "categories": category_count,
        "users": user_count,
    }


# ─── Admin panel (requiere Basic Auth) ───────────────────────────────────────

_static_dir = Path(__file__).parent / "static"

app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


@app.get("/", include_in_schema=False)
@app.get("/admin", include_in_schema=False)
def admin_panel(_: None = Depends(_require_admin)):
    return FileResponse(str(_static_dir / "index.html"))


# ─── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
