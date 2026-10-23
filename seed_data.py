"""Remplit la base avec des données de démonstration GyBlood.

Usage (depuis le dossier du backend) :
    python seed_data.py

Le script ajoute les comptes et données de démonstration manquants.
Il ne supprime aucune table et ne crée pas le schéma : celui-ci doit déjà
exister (migrations Alembic appliquées avant l'exécution).

Relancer le script remet aussi les donneurs « en ligne » (présence valable
5 minutes, RG11).

À exécuter uniquement sur une base de test/démonstration.
"""

from datetime import timedelta

from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.enums import (
    AccountStatus,
    AppointmentStatus,
    BloodGroup,
    DonationType,
    PaymentOperator,
    PaymentStatus,
    Rhesus,
    Sex,
    UserRole,
)
from app.models import (
    Appointment,
    BloodStock,
    Campaign,
    CampaignMember,
    Donation,
    Funding,
    Notification,
    Payment,
    User,
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

# (email, nom, sexe, groupe, rhésus, latitude, longitude, téléphone)
# Tous les donneurs sont situés autour de Douala.
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
    # Conserver cette protection : ne pas lancer le seed si l'environnement
    # est explicitement configuré comme production.
    if settings.app_env == "prod":
        print("Refusé : ce script n'est pas prévu pour la production.")
        return

    now = utcnow()
    pwd = hash_password(PASSWORD)
    rows: list[tuple[str, str, str]] = []
    admin_created = False

    with SessionLocal() as db:
        seed_defaults(db)

        def account(
            email: str,
            role: UserRole,
            name: str | None,
            status: AccountStatus | None = None,
        ):
            """Renvoie (utilisateur, créé ?). Un compte existant n'est pas modifié."""
            existing = db.scalar(select(User).where(User.email == email))
            if existing is not None:
                return existing, False

            user = create_account(
                db,
                email,
                role,
                password_hash=pwd,
                display_name=name,
            )
            if status is not None:
                user.status = status
            return user, True

        # ---- Administrateur
        admin = db.scalar(select(User).where(User.email == ADMIN_EMAIL))
        if admin is None:
            create_account(
                db,
                ADMIN_EMAIL,
                UserRole.ADMIN,
                password_hash=hash_password(ADMIN_PASSWORD),
                display_name="Administrateur",
            )
            admin_created = True

        admin_note = (
            "créé ; mot de passe configuré dans l'environnement"
            if admin_created
            else "compte déjà existant ; mot de passe non modifié"
        )
        rows.append(("ADMIN", ADMIN_EMAIL, admin_note))

        # ---- Structures et stocks
        structures = []
        for i, (email, name, address, lat, lon, phone, fee) in enumerate(STRUCTURES):
            user, created = account(
                email, UserRole.STRUCTURE, name, AccountStatus.VALIDATED
            )
            if created:
                p = user.structure
                p.name = name
                p.address = address
                p.latitude = lat
                p.longitude = lon
                p.phone = phone
                p.donation_fee = fee
                db.flush()

                for group in BloodGroup:
                    for rhesus in Rhesus:
                        quantity = (
                            0
                            if (group, rhesus) == (AB, NEG) and i == 0
                            else i * 3
                            + len(group.value) * 4
                            + (6 if rhesus == POS else 1)
                        )
                        db.add(
                            BloodStock(
                                structure_id=user.id,
                                blood_group=group,
                                rhesus=rhesus,
                                quantity=quantity,
                                updated_at=now,
                            )
                        )

            structures.append(user)
            rows.append(("STRUCTURE", email, name))

        pending_structure, created = account(
            "hopital-attente@gyblood.test",
            UserRole.STRUCTURE,
            "Clinique en attente",
        )
        if created:
            pending_structure.structure.name = "Clinique en attente"
            pending_structure.structure.address = "Akwa, Douala"
        rows.append(
            (
                "STRUCTURE",
                "hopital-attente@gyblood.test",
                "EN ATTENTE de validation",
            )
        )

        # ---- Sponsors
        sponsors = []
        for email, organisation, contact in SPONSORS:
            user, created = account(email, UserRole.SPONSOR, organisation)
            if created:
                user.sponsor.organisation = organisation
                user.sponsor.contact = contact
            sponsors.append(user)
            rows.append(("SPONSOR", email, organisation))

        # ---- Patients
        patients = []
        for email, name, group, rhesus, lat, lon in PATIENTS:
            user, created = account(email, UserRole.PATIENT, name)
            if created:
                user.patient.blood_group = group
                user.patient.rhesus = rhesus
                user.patient.latitude = lat
                user.patient.longitude = lon
            patients.append(user)
            rows.append(("PATIENT", email, name))

        # ---- Donneurs validés, disponibles et visibles sur la carte
        donors = []
        for email, name, sex, group, rhesus, lat, lon, phone in DONORS:
            user, created = account(
                email, UserRole.DONOR, name, AccountStatus.VALIDATED
            )
            donor = user.donor
            if created:
                donor.full_name = name
                donor.sex = sex
                donor.phone = phone
                donor.medical_history = "Aucun antécédent"
                donor.blood_group = group
                donor.rhesus = rhesus
                # Fichier fictif : aucun document réel n'est fourni avec le seed.
                donor.document_path = "document-absent.pdf"
                donor.is_available = True
                donor.share_location = True
                donor.latitude = lat
                donor.longitude = lon

            # La présence est rafraîchie à chaque lancement.
            donor.last_seen_at = now
            donors.append(user)
            rows.append(
                (
                    "DONOR",
                    email,
                    f"{name} ({group.value}{'+' if rhesus == POS else '-'})",
                )
            )

        for email, label, status, reason in (
            (
                "donneur-attente@gyblood.test",
                "Luc Ondoa",
                AccountStatus.PENDING,
                None,
            ),
            (
                "donneur-rejete@gyblood.test",
                "Yvan Kouam",
                AccountStatus.REJECTED,
                "Document illisible.",
            ),
        ):
            user, created = account(email, UserRole.DONOR, label, status)
            if created:
                user.donor.full_name = label
                user.donor.sex = Sex.MALE
                user.donor.blood_group = O
                user.donor.rhesus = POS
                user.donor.document_path = "document-absent.pdf"
                user.rejection_reason = reason
            rows.append(("DONOR", email, f"{label} — {status.value}"))

        db.flush()

        # ---- Campagnes, membres et financements : créés si aucune campagne
        # n'existe déjà.
        if db.scalar(select(Campaign.id).limit(1)) is None:
            h1, h2, h3 = structures
            day = timedelta(days=1)
            campaigns = [
                Campaign(
                    structure_id=h1.id,
                    title="Grande collecte de rentrée",
                    location="Place du Gouvernement, Bonanjo",
                    start_date=now - 2 * day,
                    end_date=now + 12 * day,
                    target_donations=150,
                    description="Collecte ouverte à tous les volontaires en bonne santé.",
                ),
                Campaign(
                    structure_id=h2.id,
                    title="Don du sang étudiant",
                    location="Campus ENSPD, Douala",
                    start_date=now + 7 * day,
                    end_date=now + 9 * day,
                    target_donations=80,
                    description="Une journée de sensibilisation et de don avec les étudiants.",
                ),
                Campaign(
                    structure_id=h3.id,
                    title="Urgence groupe O négatif",
                    location="Clinique Bonanjo",
                    start_date=now - day,
                    end_date=now + 30 * day,
                    target_donations=40,
                    description="Les stocks de O- sont au plus bas : nous comptons sur vous.",
                ),
                Campaign(
                    structure_id=h1.id,
                    title="Journée mondiale du donneur",
                    location="Stade de la Réunification",
                    start_date=now - 60 * day,
                    end_date=now - 58 * day,
                    target_donations=120,
                    description="Campagne terminée.",
                ),
            ]
            db.add_all(campaigns)
            db.flush()

            for campaign, members in (
                (campaigns[0], donors[0:5]),
                (campaigns[1], donors[3:7]),
                (campaigns[2], donors[6:9]),
            ):
                for donor in members:
                    db.add(
                        CampaignMember(
                            campaign_id=campaign.id,
                            donor_id=donor.id,
                        )
                    )

            for n, (sponsor, campaign, amount, operator) in enumerate(
                (
                    (sponsors[0], campaigns[0], 250000, PaymentOperator.MTN_MOMO),
                    (sponsors[1], campaigns[0], 100000, PaymentOperator.ORANGE_MONEY),
                    (sponsors[0], campaigns[1], 75000, PaymentOperator.MTN_MOMO),
                ),
                start=1,
            ):
                db.add(
                    Funding(
                        campaign_id=campaign.id,
                        sponsor_id=sponsor.id,
                        amount=amount,
                        operator=operator,
                        phone_number="+237690000000",
                        reference=f"SEED-FUND-{n:03d}",
                        status=PaymentStatus.SUCCEEDED,
                        created_at=now - n * day,
                    )
                )

        # ---- Rendez-vous, paiements, dons et notifications : créés si aucun
        # rendez-vous n'existe déjà.
        if db.scalar(select(Appointment.id).limit(1)) is None:
            h1, h2, _ = structures
            day = timedelta(days=1)
            alice, bruno, clarisse = patients

            def appointment(
                patient,
                donor,
                structure,
                status,
                when,
                fee=5000,
            ):
                appt = Appointment(
                    patient_id=patient.id,
                    donor_id=donor.id,
                    structure_id=structure.id,
                    scheduled_at=when,
                    status=status,
                    hospital_fee=fee,
                    created_at=when - 2 * day,
                    updated_at=when - day,
                )
                db.add(appt)
                db.flush()
                return appt

            def pay(appt, status=PaymentStatus.SUCCEEDED, n=0):
                db.add(
                    Payment(
                        appointment_id=appt.id,
                        amount=(appt.hospital_fee or 0) + 1000,
                        platform_fee=250,
                        operator=PaymentOperator.MTN_MOMO,
                        phone_number="+237690000001",
                        reference=f"SEED-PAY-{appt.id:03d}-{n}",
                        status=status,
                    )
                )

            # Historique : dons terminés il y a 5 à 7 mois.
            for patient, donor, structure, months in (
                (alice, donors[0], h1, 5),
                (bruno, donors[1], h2, 6),
                (clarisse, donors[2], h1, 7),
            ):
                when = now - timedelta(days=30 * months)
                appt = appointment(
                    patient,
                    donor,
                    structure,
                    AppointmentStatus.COMPLETED,
                    when,
                )
                pay(appt)
                db.add(
                    Donation(
                        appointment_id=appt.id,
                        donor_id=donor.id,
                        structure_id=structure.id,
                        donated_at=when,
                        volume_ml=450,
                        donation_type=DonationType.WHOLE_BLOOD,
                    )
                )
                donor.donor.last_donation_at = when

            # Rendez-vous de démonstration avec différents statuts.
            appointment(
                alice,
                donors[4],
                h1,
                AppointmentStatus.REQUESTED,
                now + 3 * day,
            )
            accepted = appointment(
                bruno,
                donors[5],
                h2,
                AppointmentStatus.ACCEPTED,
                now + 2 * day,
                6000,
            )
            paid = appointment(
                clarisse,
                donors[7],
                h1,
                AppointmentStatus.PAID,
                now + day,
            )
            pay(paid)
            cancelled = appointment(
                alice,
                donors[8],
                h2,
                AppointmentStatus.CANCELLED,
                now - 10 * day,
                6000,
            )
            cancelled.cancel_reason = "PATIENT"

            db.add_all(
                [
                    Notification(
                        user_id=alice.id,
                        title="Demande envoyée",
                        message="Votre demande de don a été transmise au donneur.",
                    ),
                    Notification(
                        user_id=bruno.id,
                        title="Rendez-vous accepté",
                        message="Le donneur a accepté. Procédez au paiement.",
                        appointment_id=accepted.id,
                    ),
                    Notification(
                        user_id=donors[4].id,
                        title="Nouvelle demande",
                        message="Un patient vous demande de donner votre sang.",
                    ),
                    Notification(
                        user_id=structures[0].id,
                        title="Rendez-vous payé",
                        message="Un rendez-vous a été payé.",
                        appointment_id=paid.id,
                    ),
                ]
            )

        db.commit()

    width = max(len(row[1]) for row in rows)
    print(f"\n{'RÔLE':<10} {'EMAIL':<{width}}  REMARQUE")
    for role, email, note in rows:
        print(f"{role:<10} {email:<{width}}  {note}")

    print(f"\nMot de passe des comptes de démonstration (sauf admin) : {PASSWORD}")
    if admin_created:
        print(
            "Mot de passe admin : celui défini par ADMIN_PASSWORD / "
            "admin_password dans la configuration."
        )
    else:
        print(
            "Le compte admin existait déjà : son mot de passe n'a pas été "
            "modifié. Utilisez le mot de passe déjà associé à ce compte."
        )
    print(
        "Les donneurs sont « en ligne » pendant 5 minutes : "
        "relancez le script avant de tester la carte."
    )


if __name__ == "__main__":
    main()