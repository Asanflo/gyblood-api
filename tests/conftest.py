"""Les variables d'environnement sont posées AVANT d'importer l'application (app.config lit l'environnement à l'import)."""

import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="gyblood-tests-"))
os.environ.update(
    {
        "APP_ENV": "dev",
        "DATABASE_URL": f"sqlite:///{_TMP / 'test.db'}",
        "UPLOAD_DIR": str(_TMP / "uploads"),
        "JWT_SECRET": "tests-only-secret-0123456789abcdef-0123456789",
        "ADMIN_EMAIL": "admin@gyblood.test",
        "ADMIN_PASSWORD": "Admin-Passw0rd",
        "PAYMENT_PROVIDER": "sandbox",
        "SANDBOX_AUTO_CONFIRM": "true",
        "PAYMENT_WEBHOOK_SECRET": "tests-webhook-secret",
        "GOOGLE_CLIENT_ID": "test-client-id",
        "GOOGLE_CLIENT_SECRET": "test-client-secret",
        "PUBLIC_BASE_URL": "http://testserver",
        "API_PREFIX": "/api/v1",
        "JWT_ALGORITHM": "HS256",
        "OAUTH_STATE_MINUTES": "10",
        "AUTH_CODE_MINUTES": "2",
        "DEFAULT_SEARCH_RADIUS_KM": "10",
        "SEARCH_CANDIDATE_LIMIT": "500",
        "SEARCH_MAX_RESULTS": "50",
        "PAGE_DEFAULT_SIZE": "20",
        "PAGE_MAX_SIZE": "100",
        "IMAGE_CACHE_SECONDS": "3600",
        "GOOGLE_AUTH_URL": "https://accounts.google.com/o/oauth2/v2/auth",
        "GOOGLE_TOKEN_URL": "https://oauth2.googleapis.com/token",
        "GOOGLE_SCOPE": "openid email profile",
        "EXTERNAL_TIMEOUT_SECONDS": "10",
    }
)

import bcrypt  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def _fast_bcrypt(monkeypatch):
    original = bcrypt.gensalt
    monkeypatch.setattr(bcrypt, "gensalt", lambda rounds=4, prefix=b"2b": original(rounds=4, prefix=prefix))


@pytest.fixture
def client():
    """Base neuve à chaque test ; le démarrage de l'application recrée les tables et l'administrateur."""
    Base.metadata.drop_all(engine)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def cfg():
    """Réglages modifiables dans un test (restaurés ensuite)."""
    saved = settings.model_copy()
    yield settings
    for name, value in saved.model_dump().items():
        setattr(settings, name, value)
