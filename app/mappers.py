"""Conversion des entités en DTO du contrat MAUI, et pagination."""

import math
from collections.abc import Callable
from typing import TypeVar

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app import schemas as s
from app.models import (
    Appointment,
    BloodStock,
    Campaign,
    Donation,
    DonorProfile,
    Funding,
    Notification,
    Payment,
    SponsorProfile,
    StructureProfile,
    User,
)

T = TypeVar("T")
R = TypeVar("R")

DONOR_DOCUMENT_URL = "donors/me/blood-document"


def display_name(user: User) -> str | None:
    if user.donor is not None and user.donor.full_name:
        return user.donor.full_name
    if user.structure is not None and user.structure.name:
        return user.structure.name
    if user.sponsor is not None and user.sponsor.organisation:
        return user.sponsor.organisation
    return user.display_name


def user_dto(user: User) -> s.UserDto:
    return s.UserDto(
        id=user.id,
        email=user.email,
        role=user.role,
        status=user.status,
        display_name=display_name(user),
        rejection_reason=user.rejection_reason,
    )


def donor_profile_dto(donor: DonorProfile) -> s.DonorProfileDto:
    return s.DonorProfileDto(
        id=donor.user_id,
        full_name=donor.full_name or "",
        sex=donor.sex,
        medical_history=donor.medical_history or "",
        phone=donor.phone,
        blood_group=donor.blood_group,
        rhesus=donor.rhesus,
        document_url=DONOR_DOCUMENT_URL if donor.document_path else None,
        status=donor.user.status,
        is_available=donor.is_available,
        share_location=donor.share_location,
        last_donation_at=donor.last_donation_at,
    )


def patient_dto(user: User) -> s.PatientDto:
    patient = user.patient
    return s.PatientDto(
        id=user.id,
        blood_group=patient.blood_group if patient else None,
        rhesus=patient.rhesus if patient else None,
        latitude=patient.latitude if patient else None,
        longitude=patient.longitude if patient else None,
    )


def structure_dto(structure: StructureProfile, distance_km: float | None = None) -> s.StructureDto:
    return s.StructureDto(
        id=structure.user_id,
        name=structure.name or "",
        address=structure.address or "",
        latitude=structure.latitude if structure.latitude is not None else 0.0,
        longitude=structure.longitude if structure.longitude is not None else 0.0,
        phone=structure.phone or "",
        status=structure.user.status,
        donation_fee=structure.donation_fee,
        distance_km=round(distance_km, 2) if distance_km is not None else None,
    )


def sponsor_dto(sponsor: SponsorProfile) -> s.SponsorDto:
    return s.SponsorDto(
        id=sponsor.user_id,
        organisation=sponsor.organisation or "",
        contact=sponsor.contact or "",
        logo_url=sponsor.logo_url,
    )


def stock_dto(stock: BloodStock, distance_km: float | None = None) -> s.StockDto:
    return s.StockDto(
        structure_id=stock.structure_id,
        structure_name=stock.structure.name or "",
        blood_group=stock.blood_group,
        rhesus=stock.rhesus,
        quantity=stock.quantity,
        updated_at=stock.updated_at,
        distance_km=round(distance_km, 2) if distance_km is not None else None,
    )


def appointment_dto(appointment: Appointment) -> s.AppointmentDto:
    return s.AppointmentDto(
        id=appointment.id,
        patient_id=appointment.patient_id,
        patient_name=appointment.patient.user.display_name or "Patient",
        donor_id=appointment.donor_id,
        donor_name=appointment.donor.full_name or "Donneur",
        structure_id=appointment.structure_id,
        structure_name=appointment.structure.name or "",
        scheduled_at=appointment.scheduled_at,
        status=appointment.status,
        hospital_fee=appointment.hospital_fee,
        created_at=appointment.created_at,
    )


def payment_dto(payment: Payment) -> s.PaymentDto:
    return s.PaymentDto(
        id=payment.id,
        appointment_id=payment.appointment_id,
        amount=payment.amount,
        platform_fee=payment.platform_fee,
        operator=payment.operator,
        reference=payment.reference,
        status=payment.status,
    )


def campaign_dto(campaign: Campaign, funds_received: int, joined: bool) -> s.CampaignDto:
    return s.CampaignDto(
        id=campaign.id,
        structure_id=campaign.structure_id,
        structure_name=campaign.structure.name or "",
        title=campaign.title,
        location=campaign.location,
        start_date=campaign.start_date,
        end_date=campaign.end_date,
        target_donations=campaign.target_donations,
        funds_received=funds_received,
        joined=joined,
        description=campaign.description,
    )


def funding_dto(funding: Funding) -> s.FundingDto:
    return s.FundingDto(
        id=funding.id,
        campaign_id=funding.campaign_id,
        campaign_title=funding.campaign.title,
        amount=funding.amount,
        created_at=funding.created_at,
        status=funding.status,
    )


def notification_dto(notification: Notification) -> s.NotificationDto:
    return s.NotificationDto(
        id=notification.id,
        title=notification.title,
        message=notification.message,
        read=notification.read,
        created_at=notification.created_at,
        appointment_id=notification.appointment_id,
    )


def donation_dto(donation: Donation) -> s.DonationDto:
    return s.DonationDto(
        id=donation.id,
        donated_at=donation.donated_at,
        structure_name=donation.structure.name or "",
        volume_ml=donation.volume_ml,
        appointment_id=donation.appointment_id,
    )


def account_summary_dto(user: User) -> s.AccountSummaryDto:
    return s.AccountSummaryDto(
        id=user.id,
        email=user.email,
        role=user.role,
        status=user.status,
        display_name=display_name(user),
        created_at=user.created_at,
    )


def paginate(db: Session, stmt: Select, page: int, size: int, mapper: Callable[[T], R]) -> s.Page[R]:
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = db.scalars(stmt.offset(page * size).limit(size)).all()
    return s.Page(
        content=[mapper(row) for row in rows],
        total_elements=total,
        total_pages=math.ceil(total / size) if total else 0,
        number=page,
        size=size,
    )
