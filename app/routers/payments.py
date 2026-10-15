import json

from fastapi import APIRouter, Depends, Header, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import schemas as s
from app.database import SessionLocal
from app.deps import get_db, require_roles
from app.enums import AppointmentStatus, PaymentStatus, UserRole
from app.errors import ApiError
from app.mappers import payment_dto
from app.models import Appointment, Payment, User
from app.services import payments as payment_service

router = APIRouter(tags=["payments"])

PatientOnly = Depends(require_roles(UserRole.PATIENT, validated=True))


class WebhookEvent(s.CamelModel):
    reference: str
    status: PaymentStatus


@router.post("/appointments/{appointment_id}/payments", response_model=s.PaymentDto, status_code=201)
def pay_appointment(
    appointment_id: int, body: s.CreatePaymentRequest, user: User = PatientOnly, db: Session = Depends(get_db)
):
    appointment = db.get(Appointment, appointment_id)
    if appointment is None or appointment.patient_id != user.id:
        raise ApiError(404, "APPOINTMENT_NOT_FOUND", "Rendez-vous introuvable.")
    if appointment.status != AppointmentStatus.ACCEPTED:
        raise ApiError(409, "INVALID_STATE", "Le donneur doit d'abord accepter le rendez-vous avant le paiement.")
    amount = appointment.hospital_fee or 0
    if amount <= 0:
        raise ApiError(409, "NO_PAYMENT_DUE", "Aucun paiement n'est dû pour ce rendez-vous.")

    in_progress = db.scalar(
        select(Payment.id).where(Payment.appointment_id == appointment.id, Payment.status == PaymentStatus.PENDING)
    )
    if in_progress is not None:
        raise ApiError(409, "PAYMENT_IN_PROGRESS", "Un paiement est déjà en cours pour ce rendez-vous.")

    result = payment_service.get_provider().charge(
        amount, body.operator, body.phone_number, f"Frais de don de sang, rendez-vous {appointment.id}"
    )
    payment = Payment(
        appointment_id=appointment.id,
        amount=amount,
        platform_fee=payment_service.platform_fee(amount),
        operator=body.operator,
        phone_number=body.phone_number,
        reference=result.reference,
        status=PaymentStatus.PENDING,
    )
    db.add(payment)
    db.flush()
    if result.status != PaymentStatus.PENDING:
        payment_service.apply_outcome(db, result.reference, result.status)
    db.commit()
    return payment_dto(payment)


@router.get("/payments/{payment_id}", response_model=s.PaymentDto)
def get_payment(payment_id: int, user: User = PatientOnly, db: Session = Depends(get_db)):
    payment = db.get(Payment, payment_id)
    if payment is None or payment.appointment.patient_id != user.id:
        raise ApiError(404, "PAYMENT_NOT_FOUND", "Paiement introuvable.")
    return payment_dto(payment)


def _process_webhook(event: WebhookEvent) -> bool:
    with SessionLocal() as db:
        known = payment_service.apply_outcome(db, event.reference, event.status)
        db.commit()
        return known


@router.post("/payments/webhook", status_code=200)
async def payment_webhook(request: Request, x_signature: str | None = Header(default=None)):
    """Appelé par l'agrégateur. Le corps brut est signé en HMAC-SHA256 (hexadécimal) dans l'en-tête X-Signature."""
    raw = await request.body()
    if not payment_service.verify_signature(raw, x_signature):
        raise ApiError(401, "INVALID_SIGNATURE", "Signature invalide.")
    try:
        event = WebhookEvent.model_validate(json.loads(raw))
    except (ValueError, ValidationError):
        raise ApiError(422, "INVALID_PAYLOAD", "Corps de la notification invalide.") from None
    if event.status not in (PaymentStatus.SUCCEEDED, PaymentStatus.FAILED):
        raise ApiError(422, "INVALID_PAYLOAD", "Statut non pris en charge.")

    if not await run_in_threadpool(_process_webhook, event):
        raise ApiError(404, "PAYMENT_NOT_FOUND", "Référence inconnue.")
    return Response(status_code=200)

