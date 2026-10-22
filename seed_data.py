"""Remplit la base avec des données de test : un compte par profil, des stocks, campagnes, rendez-vous, dons, etc.

Usage (depuis le dossier du backend) :
    python seed_data.py            # ajoute ce qui manque (peut être relancé sans danger)
    python seed_data.py --reset    # vide TOUTES les tables puis recrée tout (développement uniquement)

Relancer le script remet aussi les donneurs « en ligne » (signal de présence valable 5 minutes, RG11).
"""

import sys
from datetime import timedelta

from sqlalchemy import select

from app.config import settings
from app.database import Base, SessionLocal, engine
from app.enums import (
    AccountStatus, AppointmentStatus, BloodGroup, DonationType, PaymentOperator, PaymentStatus, Rhesus, Sex, UserRole,
)
from app.models import (
    Appointment, BloodStock, Campaign, CampaignMember, Donation, Funding, Notification, Payment, User,
)
from app.security import hash_password
from app.seed import seed_defaults
from app.services.accounts import create_account
from app.utils import utcnow

PASSWORD = "Demo-1234"
ADMIN_EMAIL = (settings.admin_email or "admin@gyblood.test").strip().lower()
ADMIN_PASSWORD = settings.admin_password or "Admin-1234"

A, B, AB, O = BloodGroup.A, BloodGroup.B, BloodGroup.AB, BloodGroup.O
POS, NEG = Rhesus.POSITIVE, Rhesus.NEGATIVE

# (email, nom, sexe, groupe, rhésus, latitude, longitude, téléphone) — tous autour de Douala
DONORS = [
    ("donneur1@gyblood.test", "Paul Mbarga", Sex.MALE, O, NEG, 4.0580, 9.7300, "+237670000001"),
    ("donneur2@gyblood.test", "Aïcha Ngono", Sex.FEMALE, A, POS, 4.0450, 9.7050, "+237670000002"),
    ("donneur3@gyblood.test", "Jean Tchoumi", Sex.MALE, B, POS, 4.0700, 9.7500, "+237670000003"),
    ("donneur4@gyblood.test", "Marie Fotso", Sex.FEMALE, O, POS, 4.0300, 9.7800, "+237670000004"),
    ("donneur5@gyblood.test", "Samuel Eto'o", Sex.MALE, A, NEG, 4.0900, 9.7200, "+237670000005"),
    ("donneur6@gyblood.test", "Grace Nkeng", Sex.FEMALE, AB, POS, 4.0200, 9.7000, "+237670000006"),
    ("donneur7@gyblood.test", "Hervé Kamga", Sex.MALE, O, NEG, 4.0650, 9.7650, "+237670000007"),
    ("donneur8@gyblood.test", "Estelle Biyong", Sex.FEMALE, B, NEG, 4.0400, 9.7400, "+237670000008"),
    ("donneur9@gyblood.test", "Cyrille Ndjock", Sex.MALE, A, POS, 4.1000, 9.7900, "+237670000009"),
    ("donneur10@gyblood.test", "Nadège Tamo", Sex.FEMALE, O, POS, 4.0550, 9.6900, "+237670000010"),
]

# (email, nom, adresse, latitude, longitude, téléphone, frais)
STRUCTURES = [
    ("hopital1@gyblood.test", "Hôpital Laquintinie", "Avenue Ahmadou Ahidjo, Douala", 4.0617, 9.7176, "+237677000001", 5000),
    ("hopital2@gyblood.test", "Hôpital Général de Douala", "Bonanjo, Douala", 4.0480, 9.6950, "+237677000002", 6000),
    ("hopital3@gyblood.test", "Clinique Bonanjo", "Rue Joss, Douala", 4.0540, 9.6990, "+237677000003", None),
]

# (email, organisation, contact)
SPONSORS = [
    ("sponsor1@gyblood.test", "Fondation Espoir Cameroun", "contact@espoir.test"),
    ("sponsor2@gyblood.test", "Brasseries Solidaires", "rse@brasseries.test"),
]

# (email, nom, groupe, rhésus, latitude, longitude)
PATIENTS = [
    ("patient1@gyblood.test", "Alice Mballa", A, POS, 4.0511, 9.7679),
    ("patient2@gyblood.test", "Bruno Essomba", O, NEG, 4.0600, 9.7100),
    ("patient3@gyblood.test", "Clarisse Ayissi", B, POS, 4.0350, 9.7450),
]


def main() -> None:
    if settings.app_env == "prod":
        print("Refusé : ce script n'est pas prévu pour la production.")
        return
    if "--reset" in sys.argv:
        Base.metadata.drop_all(engine)
        print("Toutes les tables ont été vidées.")
    Base.metadata.create_all(engine)

    now = utcnow()
    pwd = hash_password(PASSWORD)
    rows: list[tuple[str, str, str]] = []  # (rôle, email, remarque)

    with SessionLocal() as db:
        seed_defaults(db)

        def account(email: str, role: UserRole, name: str | None, status: AccountStatus | None = None):
            """Renvoie (utilisateur, créé ?). Un compte existant n'est pas modifié."""
            existing = db.scalar(select(User).where(User.email == email))
            if existing is not None:
                return existing, False
            user = create_account(db, email, role, password_hash=pwd, display_name=name)
            if status is not None:
                user.status = status
            return user, True

        # ---- administrateur
        admin = db.scalar(select(User).where(User.email == ADMIN_EMAIL))
        if admin is None:
            admin = create_account(db, ADMIN_EMAIL, UserRole.ADMIN, password_hash=hash_password(ADMIN_PASSWORD),
                                   display_name="Administrateur")
        rows.append(("ADMIN", ADMIN_EMAIL, f"mot de passe : {ADMIN_PASSWORD}"))

        # ---- structures (+ stocks)
        structures = []
        for i, (email, name, address, lat, lon, phone, fee) in enumerate(STRUCTURES):
            user, created = account(email, UserRole.STRUCTURE, name, AccountStatus.VALIDATED)
            if created:
                p = user.structure
                p.name, p.address, p.latitude, p.longitude, p.phone, p.donation_fee = name, address, lat, lon, phone, fee
                db.flush()
                for g in BloodGroup:
                    for r in Rhesus:
                        qty = 0 if (g, r) == (AB, NEG) and i == 0 else (i * 3 + len(g.value) * 4 + (6 if r == POS else 1))
                        db.add(BloodStock(structure_id=user.id, blood_group=g, rhesus=r, quantity=qty, updated_at=now))
            structures.append(user)
            rows.append(("STRUCTURE", email, name))
        pending_structure, created = account("hopital-attente@gyblood.test", UserRole.STRUCTURE, "Clinique en attente")
        if created:
            pending_structure.structure.name = "Clinique en attente"
            pending_structure.structure.address = "Akwa, Douala"
        rows.append(("STRUCTURE", "hopital-attente@gyblood.test", "EN ATTENTE de validation"))

        # ---- sponsors
        sponsors = []
        for email, org, contact in SPONSORS:
            user, created = account(email, UserRole.SPONSOR, org)
            if created:
                user.sponsor.organisation, user.sponsor.contact = org, contact
            sponsors.append(user)
            rows.append(("SPONSOR", email, org))

        # ---- patients
        patients = []
        for email, name, g, r, lat, lon in PATIENTS:
            user, created = account(email, UserRole.PATIENT, name)
            if created:
                user.patient.blood_group, user.patient.rhesus = g, r
                user.patient.latitude, user.patient.longitude = lat, lon
            patients.append(user)
            rows.append(("PATIENT", email, name))

        # ---- donneurs validés, disponibles, visibles sur la carte
        donors = []
        for email, name, sex, g, r, lat, lon, phone in DONORS:
            user, created = account(email, UserRole.DONOR, name, AccountStatus.VALIDATED)
            d = user.donor
            if created:
                d.full_name, d.sex, d.phone, d.medical_history = name, sex, phone, "Aucun antécédent"
                d.blood_group, d.rhesus = g, r
                d.document_path = "document-absent.pdf"  # fichier fictif : le téléchargement renverra 404
                d.is_available, d.share_location = True, True
                d.latitude, d.longitude = lat, lon
            d.last_seen_at = now  # présence rafraîchie à chaque lancement
            donors.append(user)
            rows.append(("DONOR", email, f"{name} ({g.value}{'+' if r == POS else '-'})"))
        for email, label, status, reason in (
            ("donneur-attente@gyblood.test", "Luc Ondoa", AccountStatus.PENDING, None),
            ("donneur-rejete@gyblood.test", "Yvan Kouam", AccountStatus.REJECTED, "Document illisible."),
        ):
            user, created = account(email, UserRole.DONOR, label, status)
            if created:
                user.donor.full_name, user.donor.sex = label, Sex.MALE
                user.donor.blood_group, user.donor.rhesus = O, POS
                user.donor.document_path = "document-absent.pdf"
                user.rejection_reason = reason
            rows.append(("DONOR", email, f"{label} — {status.value}"))
        db.flush()

        # ---- le reste n'est créé qu'une fois (évite les doublons à chaque relance)
        if db.scalar(select(Campaign.id).limit(1)) is None:
            h1, h2, h3 = structures
            day = timedelta(days=1)
            campaigns = [
                Campaign(structure_id=h1.id, title="Grande collecte de rentrée", location="Place du Gouvernement, Bonanjo",
                         start_date=now - 2 * day, end_date=now + 12 * day, target_donations=150,
                         description="Collecte ouverte à tous les volontaires en bonne santé."),
                Campaign(structure_id=h2.id, title="Don du sang étudiant", location="Campus ENSPD, Douala",
                         start_date=now + 7 * day, end_date=now + 9 * day, target_donations=80,
                         description="Une journée de sensibilisation et de don avec les étudiants."),
                Campaign(structure_id=h3.id, title="Urgence groupe O négatif", location="Clinique Bonanjo",
                         start_date=now - day, end_date=now + 30 * day, target_donations=40,
                         description="Les stocks de O- sont au plus bas : nous comptons sur vous."),
                Campaign(structure_id=h1.id, title="Journée mondiale du donneur", location="Stade de la Réunification",
                         start_date=now - 60 * day, end_date=now - 58 * day, target_donations=120,
                         description="Campagne terminée."),
            ]
            db.add_all(campaigns)
            db.flush()
            for camp, members in ((campaigns[0], donors[0:5]), (campaigns[1], donors[3:7]), (campaigns[2], donors[6:9])):
                for donor in members:
                    db.add(CampaignMember(campaign_id=camp.id, donor_id=donor.id))
            for n, (sponsor, camp, amount, op) in enumerate((
                (sponsors[0], campaigns[0], 250000, PaymentOperator.MTN_MOMO),
                (sponsors[1], campaigns[0], 100000, PaymentOperator.ORANGE_MONEY),
                (sponsors[0], campaigns[1], 75000, PaymentOperator.MTN_MOMO),
            ), start=1):
                db.add(Funding(campaign_id=camp.id, sponsor_id=sponsor.id, amount=amount, operator=op,
                               phone_number="+237690000000", reference=f"SEED-FUND-{n:03d}",
                               status=PaymentStatus.SUCCEEDED, created_at=now - n * day))

        if db.scalar(select(Appointment.id).limit(1)) is None:
            h1, h2, _ = structures
            day = timedelta(days=1)
            alice, bruno, clarisse = patients

            def appointment(patient, donor, structure, status, when, fee=5000):
                appt = Appointment(patient_id=patient.id, donor_id=donor.id, structure_id=structure.id,
                                   scheduled_at=when, status=status, hospital_fee=fee,
                                   created_at=when - 2 * day, updated_at=when - day)
                db.add(appt)
                db.flush()
                return appt

            def pay(appt, status=PaymentStatus.SUCCEEDED, n=0):
                db.add(Payment(appointment_id=appt.id, amount=(appt.hospital_fee or 0) + 1000, platform_fee=250,
                               operator=PaymentOperator.MTN_MOMO, phone_number="+237690000001",
                               reference=f"SEED-PAY-{appt.id:03d}-{n}", status=status))

            # Historique : dons terminés il y a 5 à 7 mois (les donneurs sont de nouveau éligibles).
            for patient, donor, structure, months in ((alice, donors[0], h1, 5), (bruno, donors[1], h2, 6), (clarisse, donors[2], h1, 7)):
                when = now - timedelta(days=30 * months)
                appt = appointment(patient, donor, structure, AppointmentStatus.COMPLETED, when)
                pay(appt)
                db.add(Donation(appointment_id=appt.id, donor_id=donor.id, structure_id=structure.id, donated_at=when,
                                volume_ml=450, donation_type=DonationType.WHOLE_BLOOD))
                donor.donor.last_donation_at = when

            # En cours : un de chaque statut actif, avec des donneurs réservés (ils sortent des recherches).
            appointment(alice, donors[4], h1, AppointmentStatus.REQUESTED, now + 3 * day)
            accepted = appointment(bruno, donors[5], h2, AppointmentStatus.ACCEPTED, now + 2 * day, 6000)
            paid = appointment(clarisse, donors[7], h1, AppointmentStatus.PAID, now + day)
            pay(paid)
            appointment(alice, donors[8], h2, AppointmentStatus.CANCELLED, now - 10 * day, 6000).cancel_reason = "PATIENT"

            db.add_all([
                Notification(user_id=alice.id, title="Demande envoyée", message="Votre demande de don a été transmise au donneur."),
                Notification(user_id=bruno.id, title="Rendez-vous accepté", message="Le donneur a accepté. Procédez au paiement.",
                             appointment_id=accepted.id),
                Notification(user_id=donors[4].id, title="Nouvelle demande", message="Un patient vous demande de donner votre sang."),
                Notification(user_id=structures[0].id, title="Rendez-vous payé", message="Un rendez-vous a été payé.",
                             appointment_id=paid.id),
            ])

        db.commit()

    width = max(len(r[1]) for r in rows)
    print(f"\n{'RÔLE':<10} {'EMAIL':<{width}}  REMARQUE")
    for role, email, note in rows:
        print(f"{role:<10} {email:<{width}}  {note}")
    print(f"\nMot de passe de tous les comptes (sauf admin) : {PASSWORD}")
    print("Les donneurs sont « en ligne » pendant 5 minutes : relancez le script avant de tester la carte.")


if __name__ == "__main__":
    main()
