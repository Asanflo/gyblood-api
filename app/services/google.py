"""Connexion Google : URL de consentement, échange du code, vérification du jeton d'identité.

NON TESTÉ contre Google (pas d'identifiants dans l'environnement de développement) : les tests simulent ces trois fonctions.
"""

from urllib.parse import urlencode

import httpx
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

from app.config import settings
from app.errors import ApiError

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"


def ensure_configured() -> None:
    if not settings.google_client_id or not settings.google_client_secret:
        raise ApiError(503, "GOOGLE_NOT_CONFIGURED", "La connexion Google n'est pas configurée sur le serveur.")


def redirect_uri() -> str:
    return settings.public_base_url.rstrip("/") + "/oauth2/callback/google"


def build_auth_url(state: str) -> str:
    ensure_configured()
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": settings.google_scope,
        "state": state,
        "prompt": "select_account",
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def exchange_code(code: str) -> str:
    """Échange le code d'autorisation contre un jeton d'identité Google."""
    ensure_configured()
    try:
        response = httpx.post(
            TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": redirect_uri(),
                "grant_type": "authorization_code",
            },
            timeout=10,
        )
        response.raise_for_status()
        return response.json()["id_token"]
    except (httpx.HTTPError, KeyError, ValueError):
        raise ApiError(502, "GOOGLE_EXCHANGE_FAILED", "Échec de la connexion Google. Réessayez.") from None


def verify_id_token(token: str) -> dict:
    """Vérifie la signature, l'émetteur, l'expiration et l'audience (notre client_id) du jeton d'identité."""
    ensure_configured()
    try:
        return google_id_token.verify_oauth2_token(token, google_requests.Request(), settings.google_client_id)
    except ValueError:
        raise ApiError(401, "GOOGLE_TOKEN_INVALID", "Jeton Google invalide.") from None
