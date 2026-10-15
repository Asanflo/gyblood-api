from datetime import timedelta
from urllib.parse import urlencode

import jwt
from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app import schemas as s
from app.config import settings
from app.database import get_db
from app.enums import UserRole
from app.errors import ApiError
from app.models import AuthCode, RefreshToken, User
from app.security import (
    DUMMY_HASH,
    constant_time_equals,
    decode_oauth_state,
    encode_oauth_state,
    hash_password,
    hash_token,
    new_opaque_token,
    pkce_challenge,
    verify_password,
)
from app.services import accounts, google
from app.utils import as_utc, utcnow

router = APIRouter(tags=["auth"])  # monté sous /api/v1
oauth_router = APIRouter(tags=["oauth"])  # monté à la racine : /oauth2/...

APP_CALLBACK = "gyblood://auth"  # schéma déclaré dans WebAuthenticationCallbackActivity (MAUI)


@router.post("/auth/register", response_model=s.AuthResponse, status_code=201)
def register(body: s.RegisterRequest, db: Session = Depends(get_db)):
    if body.role not in accounts.SELF_REGISTRATION_ROLES:
        raise ApiError(403, "ROLE_NOT_ALLOWED", "Ce rôle ne peut pas être choisi à l'inscription.")
    if db.scalar(select(User.id).where(User.email == body.email)) is not None:
        raise ApiError(409, "EMAIL_TAKEN", "Cette adresse email est déjà utilisée.")

    user = accounts.create_account(db, body.email, body.role, password_hash=hash_password(body.password))
    response = accounts.issue_tokens(db, user)
    db.commit()
    return response


@router.post("/auth/login", response_model=s.AuthResponse)
def login(body: s.LoginRequest, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == body.email.strip().lower()))
    # On vérifie toujours un hachage, même si l'email est inconnu : le temps de réponse ne révèle pas l'existence du compte.
    password_ok = verify_password(body.password, user.password_hash if user and user.password_hash else DUMMY_HASH)
    if user is None or not user.password_hash or not password_ok:
        raise ApiError(401, "INVALID_CREDENTIALS", "Identifiants incorrects.")

    response = accounts.issue_tokens(db, user)
    db.commit()
    return response


@router.post("/auth/refresh", response_model=s.AuthResponse)
def refresh(body: s.RefreshRequest, db: Session = Depends(get_db)):
    token = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_token(body.refresh_token)))
    if token is None:
        raise ApiError(401, "INVALID_TOKEN", "Session invalide. Reconnectez-vous.")

    if token.revoked:
        # Un jeton déjà utilisé est présenté de nouveau : il a peut-être été volé, on coupe toutes les sessions du compte.
        db.execute(update(RefreshToken).where(RefreshToken.user_id == token.user_id).values(revoked=True))
        db.commit()
        raise ApiError(401, "TOKEN_REUSED", "Session invalide. Reconnectez-vous.")

    if as_utc(token.expires_at) < utcnow():
        raise ApiError(401, "TOKEN_EXPIRED", "Session expirée. Reconnectez-vous.")

    token.revoked = True  # rotation : chaque jeton ne sert qu'une fois
    user = db.get(User, token.user_id)
    response = accounts.issue_tokens(db, user)
    db.commit()
    return response


@router.post("/auth/logout", status_code=204)
def logout(body: s.RefreshRequest, db: Session = Depends(get_db)) -> Response:
    token = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_token(body.refresh_token)))
    if token is not None and not token.revoked:
        token.revoked = True
        db.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------- Google : jeton d'identité obtenu côté application


@router.post("/auth/google", response_model=s.AuthResponse)
def google_login(body: s.GoogleLoginRequest, db: Session = Depends(get_db)):
    claims = google.verify_id_token(body.id_token)
    user = accounts.login_or_create_google_user(db, claims, body.role)
    response = accounts.issue_tokens(db, user)
    db.commit()
    return response


# ---------------------------------------------------------------- Google : flux navigateur avec PKCE
#
#   1. L'application ouvre  GET /oauth2/authorization/google?code_challenge=...&role=...
#   2. Google renvoie vers  GET /oauth2/callback/google?code=...&state=...
#   3. Le serveur redirige vers  gyblood://auth?code=<code à usage unique>  (jamais de jeton dans l'URL)
#   4. L'application appelle  POST /api/v1/auth/google/exchange { code, codeVerifier }  et reçoit les jetons.
#
# Sans le code_verifier (gardé en mémoire par l'application), un code intercepté par une autre application
# qui aurait déclaré le même schéma gyblood:// ne sert à rien.


@oauth_router.get("/oauth2/authorization/google")
def google_start(
    code_challenge: str = Query(min_length=43, max_length=128, pattern=r"^[A-Za-z0-9_-]+$"),
    role: UserRole = UserRole.PATIENT,
):
    state = encode_oauth_state(role.value, code_challenge)
    return RedirectResponse(google.build_auth_url(state), status_code=302)


def _to_app(**params: str) -> RedirectResponse:
    return RedirectResponse(f"{APP_CALLBACK}?{urlencode(params)}", status_code=302)


@oauth_router.get("/oauth2/callback/google")
def google_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_db),
):
    if error or not code or not state:
        return _to_app(error="access_denied")
    try:
        chosen = decode_oauth_state(state)
    except jwt.PyJWTError:
        return _to_app(error="invalid_state")

    try:
        claims = google.verify_id_token(google.exchange_code(code))
        user = accounts.login_or_create_google_user(db, claims, UserRole(chosen["role"]))
    except ApiError as exc:
        db.rollback()
        return _to_app(error=exc.code.lower())

    raw, digest = new_opaque_token()
    db.add(
        AuthCode(
            code_hash=digest,
            user_id=user.id,
            code_challenge=chosen["cc"],
            expires_at=utcnow() + timedelta(minutes=2),
        )
    )
    db.commit()
    return _to_app(code=raw)


@router.post("/auth/google/exchange", response_model=s.AuthResponse)
def google_exchange(body: s.GoogleExchangeRequest, db: Session = Depends(get_db)):
    invalid = ApiError(400, "INVALID_CODE", "Code de connexion invalide ou expiré. Recommencez.")
    row = db.scalar(select(AuthCode).where(AuthCode.code_hash == hash_token(body.code)))
    if row is None or row.used or as_utc(row.expires_at) < utcnow():
        raise invalid

    row.used = True  # à usage unique, même si la vérification échoue
    db.commit()
    if not constant_time_equals(pkce_challenge(body.code_verifier), row.code_challenge):
        raise invalid

    response = accounts.issue_tokens(db, db.get(User, row.user_id))
    db.commit()
    return response
