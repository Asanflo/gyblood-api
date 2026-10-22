import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.database import Base, SessionLocal, engine
from app.errors import install_handlers
from app.routers import admin, appointments, auth, campaigns, donors, me, notifications, patients, payments, sponsors, structures
from app.seed import seed_defaults

logging.basicConfig(level=logging.INFO)
app.include_router(module.router, prefix=settings.api_prefix)


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Pratique en développement. En production, préférer des migrations (Alembic) dès que le schéma évolue.
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed_defaults(db)
    yield


app = FastAPI(
    title="GyBlood API",
    version="1.0.0",
    description="API consommée par l'application mobile GyBlood (.NET MAUI).",
    lifespan=lifespan,
    docs_url=None if settings.app_env == "prod" else "/docs",
    redoc_url=None,
    openapi_url=None if settings.app_env == "prod" else "/openapi.json",
)
install_handlers(app)

for module in (
    auth, me, patients, donors, appointments, payments, structures, campaigns, sponsors, notifications, admin
):
    app.include_router(module.router, prefix=API_PREFIX)
app.include_router(auth.oauth_router)  # /oauth2/... à la racine, comme l'attend l'application


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok"}
