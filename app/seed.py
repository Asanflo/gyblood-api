"""Données de départ.

- `seed_defaults` tourne à chaque démarrage : délais entre dons (valeurs de départ) et compte administrateur.
- `python -m app.seed --demo` crée un compte par rôle et quelques stocks pour essayer l'application (développement uniquement).
"""

import logging
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import Base, SessionLocal, engine
from app.enums import (
    AccountStatus,
    BloodGroup,
    Rhesus,
    Sex,
    UserRole,
)
from app.models import BloodStock, DonationInterval, User
from app.security import hash_password
from app.services.accounts import create_account
from app.services.eligibility import STARTER_INTERVALS
from app.utils import utcnow

logger = logging.getLogger("gyblood.seed")

DEMO_PASSWORD = "Demo-1234"


def seed_defaults(db: Session) -> None:
    if db.scalar(select(DonationInterval.id).limit(1)) is None:
        for (sex, donation_type), days in STARTER_INTERVALS.items():
            db.add(DonationInterval(sex=sex, donation_type=donation_type, min_days=days))
        db.commit()
        logger.warning("Délais entre dons initialisés avec des valeurs de départ : à faire valider d'après le CNTS.")

    if settings.admin_email and settings.admin_password:
        email = settings.admin_email.strip().lower()
        if len(settings.admin_password) < 8:
            logger.error("ADMIN_PASSWORD fait moins de 8 caractères : compte administrateur non créé.")
        elif db.scalar(select(User.id).where(User.email == email)) is None:
            create_account(db, email, UserRole.ADMIN, password_hash=hash_password(settings.admin_password))
            db.commit()
            logger.info("Compte administrateur créé : %s", email)


def seed_demo(db: Session) -> list[tuple[str, str]]:
    """Un compte validé par rôle, autour de Douala. Renvoie (email, rôle) pour l'affichage."""
    created: list[tuple[str, str]] = []

    def make(email: str, role: UserRole) -> User | None:
        if db.scalar(select(User.id).where(User.email == email)) is not None:
            return None
        user = create_account(db, email, role, password_hash=hash_password(DEMO_PASSWORD))
        created.append((email, role.value))
        return user

    if (patient := make("patient@demo.gyblood.test", UserRole.PATIENT)) is not None:
        patient.patient.blood_group, patient.patient.rhesus = BloodGroup.A, Rhesus.POSITIVE
        patient.patient.latitude, patient.patient.longitude = 4.0511, 9.7679

    if (donor := make("donneur@demo.gyblood.test", UserRole.DONOR)) is not None:
        profile = donor.donor
        profile.full_name, profile.sex, profile.medical_history = "Donneur Démo", Sex.MALE, "Aucun"
        profile.blood_group, profile.rhesus = BloodGroup.O, Rhesus.NEGATIVE
        profile.document_path = "demo-document-absent.pdf"  # fichier fictif : le téléchargement renverra 404
        donor.status = AccountStatus.VALIDATED

    if (structure := make("hopital@demo.gyblood.test", UserRole.STRUCTURE)) is not None:
        profile = structure.structure
        profile.name, profile.address = "Hôpital Laquintinie (démo)", "Douala"
        profile.latitude, profile.longitude, profile.phone = 4.0617, 9.7176, "+237677000000"
        structure.status = AccountStatus.VALIDATED
        db.flush()
        now = utcnow()
        for group in BloodGroup:
            for rhesus in Rhesus:
                db.add(
                    BloodStock(structure_id=structure.id, blood_group=group, rhesus=rhesus, quantity=5, updated_at=now)
                )

    if (sponsor := make("sponsor@demo.gyblood.test", UserRole.SPONSOR)) is not None:
        sponsor.sponsor.organisation, sponsor.sponsor.contact = "Sponsor Démo", "contact@demo.gyblood.test"

    db.commit()
    return created


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    if "--demo" not in sys.argv:
        print("Usage : python -m app.seed --demo")
        return
    if settings.app_env == "prod":
        print("Refusé : les comptes de démonstration ne sont pas créés en production.")
        return
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed_defaults(db)
        created = seed_demo(db)
    if not created:
        print("Les comptes de démonstration existent déjà.")
    for email, role in created:
        print(f"{role:<10} {email}  (mot de passe : {DEMO_PASSWORD})")


if __name__ == "__main__":
    main()

