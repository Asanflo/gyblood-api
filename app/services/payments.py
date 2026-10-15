"""Paiements MoMo / Orange Money via un agrégateur (RG7).

Le patient paie `hospital_fee` ; la plateforme retient `platform_fee` (pourcentage) et le reste revient à l'hôpital.
Aucun agrégateur réel n'est branché : `SandboxProvider` simule le paiement. Pour en brancher un (Campay, CinetPay,
Notch Pay, Flutterwave...), écrire une classe avec la même méthode `charge` et l'ajouter dans `get_provider`.
Le webhook de l'agrégateur doit être converti vers { "reference": ..., "status": "SUCCEEDED" | "FAILED" } (voir routers/payments.py).
"""

import hashlib
import hmac
import secrets
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.enums import AppointmentStatus, PaymentOperator, PaymentStatus, UserRole
from app.errors import ApiError
from app.models import Funding, Payment, User
from app.services.notify import notify


# Montant minimum d'un financement de campagne (FCFA).
MIN_FUNDING_AMOUNT = 500


@dataclass
class ChargeResult:
    reference: str
    status: PaymentStatus


class SandboxProvider:
    """Paiement simulé. Réussit tout de suite si SANDBOX_AUTO_CONFIRM=true, sinon reste PENDING jusqu'au webhook.

    Pour tester l'échec : un numéro qui se termine par 0000.
    """

    def charge(self, amount: int, operator: PaymentOperator, phone_number: str, description: str) -> ChargeResult:
        reference = "SBX-" + secrets.token_hex(8).upper()
        if phone_number.endswith("0000"):
            return ChargeResult(reference, PaymentStatus.FAILED)
        status = PaymentStatus.SUCCEEDED if settings.sandbox_auto_confirm else PaymentStatus.PENDING
        return ChargeResult(reference, status)


def get_provider() -> SandboxProvider:
    if settings.payment_provider == "sandbox":
        return SandboxProvider()
    raise ApiError(503, "PAYMENT_PROVIDER_UNAVAILABLE", "Le paiement en ligne n'est pas disponible pour le moment.")


def platform_fee(amount: int) -> int:
    """Commission arrondie au FCFA le plus proche (0,5 arrondi vers le haut)."""
    return int(amount * settings.platform_fee_percent / 100 + 0.5)


def verify_signature(raw_body: bytes, signature: str | None) -> bool:
    """HMAC-SHA256 hexadécimal du corps brut, avec PAYMENT_WEBHOOK_SECRET."""
    if not signature:
        return False
    expected = hmac.new(settings.payment_webhook_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.strip().lower())


def _notify_admins(db: Session, title: str, message: str) -> None:
    for admin_id in db.scalars(select(User.id).where(User.role == UserRole.ADMIN)):
        notify(db, admin_id, title, message)


def mark_refund_due(db: Session, payment: Payment) -> None:
    """Un paiement réussi doit être remboursé : le remboursement est manuel au MVP, les administrateurs sont prévenus."""
    payment.refund_due = True
    _notify_admins(
        db,
        "Remboursement à effectuer",
        f"Paiement {payment.reference} de {payment.amount} FCFA à rembourser (rendez-vous {payment.appointment_id}).",
    )


def apply_outcome(db: Session, reference: str, status: PaymentStatus) -> bool:
    """Applique le résultat d'un paiement (appel de l'agrégateur ou webhook). Idempotent. Renvoie False si la référence est inconnue."""
    if status not in (PaymentStatus.SUCCEEDED, PaymentStatus.FAILED):
        raise ValueError("Seuls SUCCEEDED et FAILED sont acceptés.")

    payment = db.scalar(select(Payment).where(Payment.reference == reference))
    if payment is not None:
        _apply_to_payment(db, payment, status)
        return True

    funding = db.scalar(select(Funding).where(Funding.reference == reference))
    if funding is not None:
        _apply_to_funding(db, funding, status)
        return True

    return False


def _apply_to_payment(db: Session, payment: Payment, status: PaymentStatus) -> None:
    if payment.status != PaymentStatus.PENDING:
        return  # déjà traité : un webhook peut être rejoué
    payment.status = status
    appointment = payment.appointment

    if status == PaymentStatus.FAILED:
        notify(db, appointment.patient_id, "Paiement échoué", "Votre paiement n'a pas abouti. Vous pouvez réessayer.", appointment.id)
        return

    if appointment.status == AppointmentStatus.ACCEPTED:
        appointment.status = AppointmentStatus.PAID
        notify(db, appointment.patient_id, "Paiement reçu", "Votre paiement est confirmé. Présentez-vous au rendez-vous.", appointment.id)
        notify(db, appointment.donor_id, "Rendez-vous payé", "Le patient a réglé les frais : le rendez-vous est confirmé.", appointment.id)
        notify(db, appointment.structure_id, "Rendez-vous payé", "Un rendez-vous de don vient d'être payé.", appointment.id)
    else:
        # Le rendez-vous a été annulé pendant que le paiement était en cours.
        mark_refund_due(db, payment)


def _apply_to_funding(db: Session, funding: Funding, status: PaymentStatus) -> None:
    if funding.status != PaymentStatus.PENDING:
        return
    funding.status = status
    if status == PaymentStatus.SUCCEEDED:
        notify(db, funding.sponsor_id, "Financement reçu", f"Merci ! Votre financement de {funding.amount} FCFA est confirmé.")
        notify(
            db,
            funding.campaign.structure_id,
            "Nouveau financement",
            f"Un sponsor a financé « {funding.campaign.title} » à hauteur de {funding.amount} FCFA.",
        )
    else:
        notify(db, funding.sponsor_id, "Financement échoué", "Le paiement de votre financement n'a pas abouti.")
