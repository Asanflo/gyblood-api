from collections.abc import Callable

import jwt
from fastapi import Depends, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.database import get_db
from app.enums import AccountStatus, UserRole
from app.errors import ApiError
from app.models import User
from app.security import decode_access_token

bearer = HTTPBearer(auto_error=False)

__all__ = ["get_db", "current_user", "active_user", "require_roles", "PageParams"]


def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    """Utilisateur du jeton, quel que soit l'état de son compte."""
    if credentials is None:
        raise ApiError(401, "UNAUTHORIZED", "Authentification requise.")
    try:
        payload = decode_access_token(credentials.credentials)
    except jwt.ExpiredSignatureError:
        raise ApiError(401, "TOKEN_EXPIRED", "Session expirée.") from None
    except jwt.PyJWTError:
        raise ApiError(401, "INVALID_TOKEN", "Jeton invalide.") from None

    user = db.get(User, int(payload["sub"]))
    if user is None:
        raise ApiError(401, "INVALID_TOKEN", "Jeton invalide.")
    return user


def active_user(user: User = Depends(current_user)) -> User:
    """Utilisateur dont le compte n'est pas suspendu."""
    if user.status == AccountStatus.SUSPENDED:
        raise ApiError(403, "ACCOUNT_SUSPENDED", "Votre compte est suspendu. Contactez l'administrateur.")
    return user


def require_roles(*roles: UserRole, validated: bool = False) -> Callable[..., User]:
    """Autorise certains rôles ; validated=True exige en plus un compte validé (RG1, RG2)."""

    def dependency(user: User = Depends(active_user)) -> User:
        if user.role not in roles:
            raise ApiError(403, "FORBIDDEN", "Action non autorisée pour votre rôle.")
        if validated and user.status != AccountStatus.VALIDATED:
            raise ApiError(403, "ACCOUNT_NOT_VALIDATED", "Votre compte n'est pas encore validé.")
        return user

    return dependency


class PageParams:
    def __init__(self, page: int = Query(0, ge=0), size: int = Query(20, ge=1, le=100)):
        self.page = page
        self.size = size
