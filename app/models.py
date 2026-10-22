from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean
from sqlalchemy import Enum as SAEnum
from sqlalchemy import Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, UTCDateTime
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
from app.utils import utcnow


def enum_col(enum_cls, **kwargs):
    """Énumération stockée en texte (pas de type natif PostgreSQL : plus simple à faire évoluer)."""
    return mapped_column(SAEnum(enum_cls, native_enum=False, length=24), **kwargs)


# ---------------------------------------------------------------- comptes


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[Optional[str]] = mapped_column(String(255))
    google_sub: Mapped[Optional[str]] = mapped_column(String(64), unique=True)
    role: Mapped[UserRole] = enum_col(UserRole)
    status: Mapped[AccountStatus] = enum_col(AccountStatus, default=AccountStatus.PENDING)
    display_name: Mapped[Optional[str]] = mapped_column(String(120))
    rejection_reason: Mapped[Optional[str]] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    patient: Mapped[Optional["PatientProfile"]] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    donor: Mapped[Optional["DonorProfile"]] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    structure: Mapped[Optional["StructureProfile"]] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    sponsor: Mapped[Optional["SponsorProfile"]] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    fcm_token: Mapped[str] = mapped_column(String(512), unique=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


# ---------------------------------------------------------------- profils (clé primaire = identifiant du compte)


class PatientProfile(Base):
    __tablename__ = "patient_profiles"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    blood_group: Mapped[Optional[BloodGroup]] = enum_col(BloodGroup, nullable=True)
    rhesus: Mapped[Optional[Rhesus]] = enum_col(Rhesus, nullable=True)
    latitude: Mapped[Optional[float]] = mapped_column(Float)
    longitude: Mapped[Optional[float]] = mapped_column(Float)

    user: Mapped[User] = relationship(back_populates="patient")


class DonorProfile(Base):
    __tablename__ = "donor_profiles"
    __table_args__ = (Index("ix_donor_search", "is_available", "share_location", "last_seen_at"),)

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    full_name: Mapped[str] = mapped_column(String(120), default="")
    sex: Mapped[Optional[Sex]] = enum_col(Sex, nullable=True)
    medical_history: Mapped[str] = mapped_column(Text, default="")
    phone: Mapped[Optional[str]] = mapped_column(String(20))
    blood_group: Mapped[Optional[BloodGroup]] = enum_col(BloodGroup, nullable=True)
    rhesus: Mapped[Optional[Rhesus]] = enum_col(Rhesus, nullable=True)
    document_path: Mapped[Optional[str]] = mapped_column(String(255))
    is_available: Mapped[bool] = mapped_column(Boolean, default=False)
    share_location: Mapped[bool] = mapped_column(Boolean, default=False)
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime)
    latitude: Mapped[Optional[float]] = mapped_column(Float)
    longitude: Mapped[Optional[float]] = mapped_column(Float)
    last_donation_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime)

    user: Mapped[User] = relationship(back_populates="donor")


class StructureProfile(Base):
    __tablename__ = "structure_profiles"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), default="")
    address: Mapped[str] = mapped_column(String(300), default="")
    latitude: Mapped[Optional[float]] = mapped_column(Float)
    longitude: Mapped[Optional[float]] = mapped_column(Float)
    phone: Mapped[str] = mapped_column(String(20), default="")
    # Frais d'entretien et d'examens payés par le patient, en FCFA (entier : le FCFA n'a pas de centime).
    donation_fee: Mapped[Optional[int]] = mapped_column(Integer)

    user: Mapped[User] = relationship(back_populates="structure")


class SponsorProfile(Base):
    __tablename__ = "sponsor_profiles"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    organisation: Mapped[str] = mapped_column(String(160), default="")
    contact: Mapped[str] = mapped_column(String(160), default="")
    logo_url: Mapped[Optional[str]] = mapped_column(String(500))

    user: Mapped[User] = relationship(back_populates="sponsor")


# ---------------------------------------------------------------- stocks et délais


class BloodStock(Base):
    __tablename__ = "blood_stocks"
    __table_args__ = (UniqueConstraint("structure_id", "blood_group", "rhesus"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    structure_id: Mapped[int] = mapped_column(ForeignKey("structure_profiles.user_id", ondelete="CASCADE"), index=True)
    blood_group: Mapped[BloodGroup] = enum_col(BloodGroup)
    rhesus: Mapped[Rhesus] = enum_col(Rhesus)
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    structure: Mapped[StructureProfile] = relationship()


class DonationInterval(Base):
    """Délai minimal entre deux dons (RG5), configuré par l'administrateur."""

    __tablename__ = "donation_intervals"
    __table_args__ = (UniqueConstraint("sex", "donation_type"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    sex: Mapped[Sex] = enum_col(Sex)
    donation_type: Mapped[DonationType] = enum_col(DonationType)
    min_days: Mapped[int] = mapped_column(Integer)


# ---------------------------------------------------------------- rendez-vous, dons, paiements


class Appointment(Base):
    __tablename__ = "appointments"

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patient_profiles.user_id"), index=True)
    donor_id: Mapped[int] = mapped_column(ForeignKey("donor_profiles.user_id"), index=True)
    structure_id: Mapped[int] = mapped_column(ForeignKey("structure_profiles.user_id"), index=True)
    scheduled_at: Mapped[datetime] = mapped_column(UTCDateTime)
    status: Mapped[AppointmentStatus] = enum_col(AppointmentStatus, default=AppointmentStatus.REQUESTED)
    hospital_fee: Mapped[Optional[int]] = mapped_column(Integer)
    cancel_reason: Mapped[Optional[str]] = mapped_column(String(60))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    patient: Mapped[PatientProfile] = relationship()
    donor: Mapped[DonorProfile] = relationship()
    structure: Mapped[StructureProfile] = relationship()
    payments: Mapped[list["Payment"]] = relationship(back_populates="appointment")


class Donation(Base):
    __tablename__ = "donations"

    id: Mapped[int] = mapped_column(primary_key=True)
    appointment_id: Mapped[int] = mapped_column(ForeignKey("appointments.id"), unique=True)
    donor_id: Mapped[int] = mapped_column(ForeignKey("donor_profiles.user_id"), index=True)
    structure_id: Mapped[int] = mapped_column(ForeignKey("structure_profiles.user_id"))
    donated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    volume_ml: Mapped[Optional[int]] = mapped_column(Integer)
    donation_type: Mapped[DonationType] = enum_col(DonationType, default=DonationType.WHOLE_BLOOD)

    structure: Mapped[StructureProfile] = relationship()


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    appointment_id: Mapped[int] = mapped_column(ForeignKey("appointments.id"), index=True)
    amount: Mapped[int] = mapped_column(Integer)
    platform_fee: Mapped[int] = mapped_column(Integer, default=0)
    operator: Mapped[PaymentOperator] = enum_col(PaymentOperator)
    phone_number: Mapped[str] = mapped_column(String(20))
    reference: Mapped[str] = mapped_column(String(40), unique=True)
    status: Mapped[PaymentStatus] = enum_col(PaymentStatus, default=PaymentStatus.PENDING)
    # Vrai si un paiement réussi doit être remboursé (annulation, absence). Le remboursement est manuel au MVP.
    refund_due: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    appointment: Mapped[Appointment] = relationship(back_populates="payments")


# ---------------------------------------------------------------- campagnes et sponsors


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(primary_key=True)
    structure_id: Mapped[int] = mapped_column(ForeignKey("structure_profiles.user_id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    location: Mapped[str] = mapped_column(String(300))
    start_date: Mapped[datetime] = mapped_column(UTCDateTime)
    end_date: Mapped[datetime] = mapped_column(UTCDateTime)
    target_donations: Mapped[int] = mapped_column(Integer)
    description: Mapped[Optional[str]] = mapped_column(Text)
    image_path: Mapped[Optional[str]] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    structure: Mapped[StructureProfile] = relationship()


class CampaignMember(Base):
    __tablename__ = "campaign_members"

    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), primary_key=True)
    donor_id: Mapped[int] = mapped_column(ForeignKey("donor_profiles.user_id", ondelete="CASCADE"), primary_key=True)
    joined_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Funding(Base):
    __tablename__ = "fundings"

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id"), index=True)
    sponsor_id: Mapped[int] = mapped_column(ForeignKey("sponsor_profiles.user_id"), index=True)
    amount: Mapped[int] = mapped_column(Integer)
    operator: Mapped[PaymentOperator] = enum_col(PaymentOperator)
    phone_number: Mapped[str] = mapped_column(String(20))
    reference: Mapped[str] = mapped_column(String(40), unique=True)
    status: Mapped[PaymentStatus] = enum_col(PaymentStatus, default=PaymentStatus.PENDING)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    campaign: Mapped[Campaign] = relationship()


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(160))
    message: Mapped[str] = mapped_column(String(500))
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    appointment_id: Mapped[Optional[int]] = mapped_column(ForeignKey("appointments.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


# ---------------------------------------------------------------- connexion Google (navigateur) avec PKCE


class AuthCode(Base):
    """Code à usage unique rendu à l'application après la connexion Google ; échangé contre des jetons avec le code_verifier (PKCE)."""

    __tablename__ = "auth_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    code_challenge: Mapped[str] = mapped_column(String(128))
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    used: Mapped[bool] = mapped_column(Boolean, default=False)
