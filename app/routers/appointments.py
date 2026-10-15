"""Rendez-vous de don : DEMANDÉ -> ACCEPTÉ -> PAYÉ -> EFFECTUÉ (ou ANNULÉ / ABSENT), RG6."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import schemas as s
from app.config import settings
from app.deps import PageParams, get_db, require_roles
from app.enums import ACTIVE_APPOINTMENT, AccountStatus, AppointmentStatus, DonationType, PaymentStatus, UserRole
from app.errors import ApiError
from app.mappers import appointment_dto, paginate
from app.models import Appointment, Donation, DonorProfile, StructureProfile, User
from app.services.compatibility import can_donate, format_group
from app.services.eligibility import is_eligible, load_intervals, next_donation_date
from app.services.geo import haversine_km
from app.services.notify import notify
from app.services.payments import mark_refund_due
from app.utils import as_utc, fmt_date, utcnow

router = APIRouter(tags=["appointments"])

PatientOnly = Depends(require_roles(UserRole.PATIENT, validated=True))
DonorOnly = Depends(require_roles(UserRole.DONOR, validated=True))
StructureOnly = Depends(require_roles(UserRole.STRUCTURE, validated=True))
AnyParty = Depends(require_roles(UserRole.PATIENT, UserRole.DONOR, UserRole.STRUCTURE, validated=True))


def _not_found() -> ApiError:
    return ApiError(404, "APPOINTMENT_NOT_FOUND", "Rendez-vous introuvable.")


def _load(db: Session, appointment_id: int, user: User) -> Appointment:
    """Un rendez-vous n'est visible que par ses trois parties ; pour les autres il « n'existe pas »."""
    appointment = db.get(Appointment, appointment_id)
    if appointment is None:
        raise _not_found()
    owner = {
        UserRole.PATIENT: appointment.patient_id,
        UserRole.DONOR: appointment.donor_id,
        UserRole.STRUCTURE: appointment.structure_id,
    }.get(user.role)
    if owner != user.id:
        raise _not_found()
    return appointment


def _require_status(appointment: Appointment, *allowed: AppointmentStatus) -> None:
    if appointment.status not in allowed:
        raise ApiError(
            409,
            "INVALID_STATE",
            f"Cette action n'est pas possible : le rendez-vous est au statut {appointment.status.value}.",
        )


@router.post("/appointments", response_model=s.AppointmentDto, status_code=201)
def create_appointment(body: s.CreateAppointmentRequest, user: User = PatientOnly, db: Session = Depends(get_db)):
    patient = user.patient
    if patient is None or patient.blood_group is None or patient.rhesus is None:
        raise ApiError(409, "PATIENT_PROFILE_INCOMPLETE", "Renseignez votre groupe sanguin avant de demander un don.")

    donor = db.get(DonorProfile, body.donor_id)
    if donor is None or donor.user.status != AccountStatus.VALIDATED:
        raise ApiError(404, "DONOR_NOT_FOUND", "Donneur introuvable.")
    if not can_donate(donor.blood_group, donor.rhesus, patient.blood_group, patient.rhesus):
        raise ApiError(409, "INCOMPATIBLE_BLOOD", "Ce donneur n'est pas compatible avec votre groupe sanguin.")

    now = utcnow()
    if not is_eligible(donor, load_intervals(db), now):
        raise ApiError(409, "DONOR_NOT_ELIGIBLE", "Ce donneur ne peut pas donner avant la fin de son délai de repos.")

    structure = db.get(StructureProfile, body.structure_id)
    if structure is None or structure.user.status != AccountStatus.VALIDATED:
        raise ApiError(404, "STRUCTURE_NOT_FOUND", "Structure de santé introuvable.")

    scheduled_at = as_utc(body.scheduled_at)
    if scheduled_at <= now:
        raise ApiError(422, "INVALID_DATE", "Choisissez un créneau dans le futur.")

    already = db.scalar(
        select(Appointment.id).where(
            Appointment.patient_id == user.id,
            Appointment.donor_id == donor.user_id,
            Appointment.status.in_(ACTIVE_APPOINTMENT),
        )
    )
    if already is not None:
        raise ApiError(409, "REQUEST_ALREADY_SENT", "Vous avez déjà une demande en cours avec ce donneur.")

    appointment = Appointment(
        patient_id=user.id,
        donor_id=donor.user_id,
        structure_id=structure.user_id,
        scheduled_at=scheduled_at,
        status=AppointmentStatus.REQUESTED,
        hospital_fee=structure.donation_fee if structure.donation_fee is not None else settings.default_hospital_fee,
    )
    db.add(appointment)
    db.flush()

    # Le donneur voit le groupe du patient et la distance, pas son identité (US-22).
    message = f"Un patient du groupe {format_group(patient.blood_group, patient.rhesus)} a besoin d'un don"
    if None not in (patient.latitude, patient.longitude, donor.latitude, donor.longitude):
        message += f" (à {haversine_km(patient.latitude, patient.longitude, donor.latitude, donor.longitude):.1f} km de vous)"
    message += f", à {structure.name}, le {fmt_date(scheduled_at)}."
    notify(db, donor.user_id, "Demande de don de sang", message, appointment.id)

    db.commit()
    return appointment_dto(appointment)


@router.get("/appointments", response_model=s.Page[s.AppointmentDto])
def list_appointments(
    status: AppointmentStatus | None = Query(default=None),
    user: User = AnyParty,
    page: PageParams = Depends(),
    db: Session = Depends(get_db),
):
    column = {
        UserRole.PATIENT: Appointment.patient_id,
        UserRole.DONOR: Appointment.donor_id,
        UserRole.STRUCTURE: Appointment.structure_id,
    }[user.role]
    stmt = select(Appointment).where(column == user.id)
    if status is not None:
        stmt = stmt.where(Appointment.status == status)
    stmt = stmt.order_by(Appointment.created_at.desc(), Appointment.id.desc())
    return paginate(db, stmt, page.page, page.size, appointment_dto)


@router.get("/appointments/{appointment_id}", response_model=s.AppointmentDto)
def get_appointment(appointment_id: int, user: User = AnyParty, db: Session = Depends(get_db)):
    return appointment_dto(_load(db, appointment_id, user))


@router.post("/appointments/{appointment_id}/accept", response_model=s.AppointmentDto)
def accept(appointment_id: int, user: User = DonorOnly, db: Session = Depends(get_db)):
    appointment = _load(db, appointment_id, user)
    _require_status(appointment, AppointmentStatus.REQUESTED)

    now = utcnow()
    if not is_eligible(appointment.donor, load_intervals(db), now):
        next_date = next_donation_date(appointment.donor, load_intervals(db))
        raise ApiError(409, "DONOR_NOT_ELIGIBLE", f"Vous pourrez donner à partir du {fmt_date(next_date)}.")

    busy = db.scalar(
        select(Appointment.id).where(
            Appointment.donor_id == user.id,
            Appointment.id != appointment.id,
            Appointment.status.in_((AppointmentStatus.ACCEPTED, AppointmentStatus.PAID)),
        )
    )
    if busy is not None:
        raise ApiError(409, "DONOR_BUSY", "Vous avez déjà accepté un autre rendez-vous.")

    appointment.status = AppointmentStatus.ACCEPTED
    notify(
        db,
        appointment.patient_id,
        "Demande acceptée",
        "Un donneur a accepté. Réglez les frais d'entretien et d'examens pour confirmer le rendez-vous.",
        appointment.id,
    )
    db.commit()
    return appointment_dto(appointment)


@router.post("/appointments/{appointment_id}/decline", response_model=s.AppointmentDto)
def decline(appointment_id: int, user: User = DonorOnly, db: Session = Depends(get_db)):
    """Refus sans pénalité : il n'existe pas de statut « refusé », le rendez-vous passe à ANNULÉ."""
    appointment = _load(db, appointment_id, user)
    _require_status(appointment, AppointmentStatus.REQUESTED)
    appointment.status = AppointmentStatus.CANCELLED
    appointment.cancel_reason = "DONOR_DECLINED"
    notify(db, appointment.patient_id, "Demande refusée", "Ce donneur n'est pas disponible. Essayez un autre donneur.", appointment.id)
    db.commit()
    return appointment_dto(appointment)


@router.post("/appointments/{appointment_id}/cancel", response_model=s.AppointmentDto)
def cancel(
    appointment_id: int,
    user: User = Depends(require_roles(UserRole.PATIENT, UserRole.DONOR, validated=True)),
    db: Session = Depends(get_db),
):
    appointment = _load(db, appointment_id, user)
    _require_status(appointment, AppointmentStatus.REQUESTED, AppointmentStatus.ACCEPTED, AppointmentStatus.PAID)

    by_patient = user.role == UserRole.PATIENT
    was_paid = appointment.status == AppointmentStatus.PAID
    appointment.status = AppointmentStatus.CANCELLED
    appointment.cancel_reason = "PATIENT_CANCELLED" if by_patient else "DONOR_CANCELLED"

    if was_paid:
        for payment in appointment.payments:
            if payment.status == PaymentStatus.SUCCEEDED and not payment.refund_due:
                mark_refund_due(db, payment)

    other = appointment.donor_id if by_patient else appointment.patient_id
    notify(db, other, "Rendez-vous annulé", "Le rendez-vous de don a été annulé.", appointment.id)
    if was_paid:
        notify(db, appointment.structure_id, "Rendez-vous annulé", "Un rendez-vous payé a été annulé.", appointment.id)
    db.commit()
    return appointment_dto(appointment)


@router.post("/appointments/{appointment_id}/complete", response_model=s.AppointmentDto)
def complete(appointment_id: int, user: User = StructureOnly, db: Session = Depends(get_db)):
    """La structure confirme le don : enregistre le don et lance le délai de repos du donneur (RG5, RG6)."""
    appointment = _load(db, appointment_id, user)
    allowed = [AppointmentStatus.PAID]
    if not appointment.hospital_fee:
        allowed.append(AppointmentStatus.ACCEPTED)  # rien à payer
    _require_status(appointment, *allowed)

    now = utcnow()
    appointment.status = AppointmentStatus.COMPLETED
    db.add(
        Donation(
            appointment_id=appointment.id,
            donor_id=appointment.donor_id,
            structure_id=appointment.structure_id,
            donated_at=now,
            donation_type=DonationType.WHOLE_BLOOD,
        )
    )
    donor = appointment.donor
    donor.last_donation_at = now
    donor.is_available = False

    next_date = next_donation_date(donor, load_intervals(db))
    notify(
        db,
        donor.user_id,
        "Merci pour votre don",
        f"Votre don est enregistré. Vous pourrez redonner à partir du {fmt_date(next_date)}.",
        appointment.id,
    )
    notify(db, appointment.patient_id, "Don effectué", "Le don de sang a bien eu lieu.", appointment.id)
    db.commit()
    return appointment_dto(appointment)


@router.post("/appointments/{appointment_id}/no-show", response_model=s.AppointmentDto)
def no_show(appointment_id: int, user: User = StructureOnly, db: Session = Depends(get_db)):
    """Le donneur ne s'est pas présenté. Le paiement n'est pas remboursé automatiquement : règle à confirmer."""
    appointment = _load(db, appointment_id, user)
    _require_status(appointment, AppointmentStatus.ACCEPTED, AppointmentStatus.PAID)
    appointment.status = AppointmentStatus.NO_SHOW
    notify(db, appointment.patient_id, "Donneur absent", "Le donneur ne s'est pas présenté au rendez-vous.", appointment.id)
    db.commit()
    return appointment_dto(appointment)
