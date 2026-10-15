"""Création de comptes, émission des jetons, connexion Google."""

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import schemas as s
from app.config import settings
from app.enums import AccountStatus, UserRole
from app.errors import ApiError
from app.mappers import user_dto
from app.models import DonorProfile, PatientProfile, RefreshToken, SponsorProfile, StructureProfile, User
from app.security import create_access_token, new_opaque_token
from app.utils import utcnow

# Rôles qu'on peut choisir soi-même à l'inscription (l'administrateur est créé au démarrage, jamais par l'API).
SELF_REGISTRATION_ROLES = (UserRole.PATIENT, UserRole.DONOR, UserRole.STRUCTURE, UserRole.SPONSOR)

# Patients et sponsors sont actifs tout de suite ; donneurs et structures attendent la validation de l'administrateur (RG1, RG2).
_AUTO_VALIDATED = (UserRole.PATIENT, UserRole.SPONSOR, UserRole.ADMIN)


def create_account(
    db: Session,
    email: str,
    role: UserRole,
    *,
    password_hash: str | None = None,
    google_sub: str | None = None,
    display_name: str | None = None,
) -> User:
    user = User(
        email=email,
        role=role,
        status=AccountStatus.VALIDATED if role in _AUTO_VALIDATED else AccountStatus.PENDING,
        password_hash=password_hash,
        google_sub=google_sub,
        display_name=display_name,
    )
    if role == UserRole.PATIENT:
        user.patient = PatientProfile()
    elif role == UserRole.DONOR:
        user.donor = DonorProfile()
    elif role == UserRole.STRUCTURE:
        user.structure = StructureProfile()
    elif role == UserRole.SPONSOR:
        user.sponsor = SponsorProfile()
    db.add(user)
    db.flush()
    return user


def issue_tokens(db: Session, user: User) -> s.AuthResponse:
    """Jeton d'accès (JWT court) + jeton de rafraîchissement (aléatoire, stocké haché). À suivre d'un db.commit()."""
    raw, digest = new_opaque_token()
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=digest,
            expires_at=utcnow() + timedelta(days=settings.refresh_token_days),
        )
    )
    db.flush()
    return s.AuthResponse(access_token=create_access_token(user.id), refresh_token=raw, user=user_dto(user))


def login_or_create_google_user(db: Session, claims: dict, role: UserRole | None) -> User:
    """Compte lié à une identité Google vérifiée.

    Si un compte avec mot de passe existe déjà pour cet email, on ne le relie PAS automatiquement : l'inscription par
    email n'est pas vérifiée, donc quelqu'un aurait pu créer ce compte à l'avance avec l'adresse de la victime.
    """
    if not claims.get("email_verified"):
        raise ApiError(401, "GOOGLE_EMAIL_UNVERIFIED", "L'adresse email de ce compte Google n'est pas vérifiée.")

    sub = str(claims["sub"])
    email = str(claims["email"]).lower()

    user = db.scalar(select(User).where(User.google_sub == sub))
    if user is not None:
        return user

    if db.scalar(select(User.id).where(User.email == email)) is not None:
        raise ApiError(
            409,
            "ACCOUNT_EXISTS",
            "Un compte existe déjà avec cette adresse email : connectez-vous avec votre mot de passe.",
        )

    chosen = role if role in SELF_REGISTRATION_ROLES else UserRole.PATIENT
    return create_account(db, email, chosen, google_sub=sub, display_name=claims.get("name"))
