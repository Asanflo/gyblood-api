import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.config import settings

_ALGORITHM = settings.jwt_algorithm


# ------------------------------------------------------------------ mots de passe
def _prehash(password: str) -> bytes:
    # bcrypt ignore (ou refuse) tout ce qui dépasse 72 octets : on passe par SHA-256 pour garder tout le mot de passe.
    return base64.b64encode(hashlib.sha256(password.encode("utf-8")).digest())


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_prehash(password), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_prehash(password), hashed.encode("ascii"))
    except ValueError:
        return False


# Hachage factice : on le vérifie quand l'email est inconnu pour ne pas révéler son existence par le temps de réponse.
DUMMY_HASH = hash_password("dummy-password-for-timing")


# ------------------------------------------------------------------ jetons
def _encode(claims: dict, minutes: int) -> str:
    now = datetime.now(timezone.utc)
    payload = {**claims, "iat": now, "exp": now + timedelta(minutes=minutes)}
    return jwt.encode(payload, settings.jwt_secret, algorithm=_ALGORITHM)


def create_access_token(user_id: int) -> str:
    return _encode({"sub": str(user_id), "typ": "access"}, settings.access_token_minutes)


def decode_access_token(token: str) -> dict:
    payload = jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[_ALGORITHM],
        options={"require": ["exp", "sub", "typ"]},
    )
    if payload["typ"] != "access":
        raise jwt.InvalidTokenError("mauvais type de jeton")
    return payload


def encode_oauth_state(role: str, code_challenge: str) -> str:
        return _encode({"typ": "oauth_state", "role": role, "cc": code_challenge, "n": secrets.token_urlsafe(8)}, settings.oauth_state_minutes)


def decode_oauth_state(state: str) -> dict:
    payload = jwt.decode(state, settings.jwt_secret, algorithms=[_ALGORITHM], options={"require": ["exp", "typ"]})
    if payload["typ"] != "oauth_state":
        raise jwt.InvalidTokenError("mauvais type de jeton")
    return payload


def new_opaque_token() -> tuple[str, str]:
    """Renvoie (jeton à donner au client, empreinte à stocker). Le jeton lui-même n'est jamais stocké."""
    raw = secrets.token_urlsafe(48)
    return raw, hash_token(raw)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii", errors="ignore")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))
