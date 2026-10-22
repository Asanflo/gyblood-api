"""Contrat JSON avec l'application MAUI (voir les records de GyBlood.Mobile/Models).

Propriétés en camelCase, énumérations en MAJUSCULES_AVEC_TIRET_BAS, montants en FCFA (entiers),
listes paginées au format Spring Data (content, totalElements, totalPages, number, size).
"""

import re
from datetime import datetime
from typing import Annotated, Generic, TypeVar

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator
from pydantic.alias_generators import to_camel

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


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)


# ---------------------------------------------------------------- validations partagées

_PHONE_RE = re.compile(r"^(?:\+?237)?([26]\d{8})$")


def normalize_phone(value: str) -> str:
    compact = re.sub(r"[\s\-.]", "", value)
    match = _PHONE_RE.match(compact)
    if not match:
        raise ValueError("Numéro de téléphone invalide (format camerounais attendu).")
    return "+237" + match.group(1)


Phone = Annotated[str, AfterValidator(normalize_phone)]
Latitude = Annotated[float, Field(ge=-90, le=90)]
Longitude = Annotated[float, Field(ge=-180, le=180)]


# ---------------------------------------------------------------- requêtes


class RegisterRequest(CamelModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    role: UserRole
    display_name: str | None = Field(default=None, max_length=120)

    @field_validator("display_name")
    @classmethod
    def clean_display_name(cls, value: str | None) -> str | None:
        return value.strip() or None if value else None

    @field_validator("email")
    @classmethod
    def lower_email(cls, value: str) -> str:
        return value.lower()


class LoginRequest(CamelModel):
    email: str = Field(max_length=255)
    password: str = Field(max_length=128)


class GoogleLoginRequest(CamelModel):
    id_token: str
    role: UserRole | None = None


class RefreshRequest(CamelModel):
    refresh_token: str


class RegisterDeviceRequest(CamelModel):
    fcm_token: str = Field(min_length=10, max_length=512)


class HeartbeatRequest(CamelModel):
    latitude: Latitude
    longitude: Longitude


class UpdatePatientRequest(CamelModel):
    blood_group: BloodGroup
    rhesus: Rhesus
    latitude: Latitude
    longitude: Longitude


class UpdateDonorRequest(CamelModel):
    full_name: str = Field(min_length=2, max_length=120)
    sex: Sex
    medical_history: str = Field(max_length=4000)
    phone: Phone | None = None
    blood_group: BloodGroup
    rhesus: Rhesus

    @field_validator("full_name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        return value.strip()


class AvailabilityRequest(CamelModel):
    is_available: bool
    share_location: bool


class CreateAppointmentRequest(CamelModel):
    donor_id: int
    structure_id: int
    scheduled_at: datetime


class CreatePaymentRequest(CamelModel):
    operator: PaymentOperator
    phone_number: Phone


class UpdateStructureRequest(CamelModel):
    name: str = Field(min_length=2, max_length=160)
    address: str = Field(min_length=2, max_length=300)
    latitude: Latitude
    longitude: Longitude
    phone: Phone
    donation_fee: int | None = Field(default=None, ge=0, le=10_000_000)


class StockItemRequest(CamelModel):
    blood_group: BloodGroup
    rhesus: Rhesus
    quantity: int = Field(ge=0, le=100_000)


class UpdateStocksRequest(CamelModel):
    items: list[StockItemRequest] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def no_duplicates(self):
        seen = {(item.blood_group, item.rhesus) for item in self.items}
        if len(seen) != len(self.items):
            raise ValueError("Un groupe sanguin ne peut apparaître qu'une fois.")
        return self


class CreateCampaignRequest(CamelModel):
    title: str = Field(min_length=3, max_length=200)
    location: str = Field(min_length=2, max_length=300)
    start_date: datetime
    end_date: datetime
    target_donations: int = Field(ge=1, le=100_000)
    description: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def dates_in_order(self):
        if self.end_date < self.start_date:
            raise ValueError("La date de fin doit suivre la date de début.")
        return self


class UpdateSponsorRequest(CamelModel):
    organisation: str = Field(min_length=2, max_length=160)
    contact: str = Field(min_length=2, max_length=160)
    logo_url: str | None = Field(default=None, max_length=500)


class FundCampaignRequest(CamelModel):
    amount: int = Field(gt=0, le=100_000_000)
    operator: PaymentOperator
    phone_number: Phone


class RejectAccountRequest(CamelModel):
    reason: str = Field(min_length=3, max_length=500)


class DonationIntervalDto(CamelModel):
    sex: Sex
    donation_type: DonationType
    min_days: int = Field(ge=1, le=3650)


# ---------------------------------------------------------------- réponses

T = TypeVar("T")


class Page(CamelModel, Generic[T]):
    content: list[T]
    total_elements: int
    total_pages: int
    number: int
    size: int


class UserDto(CamelModel):
    id: int
    email: str
    role: UserRole
    status: AccountStatus
    display_name: str | None = None
    rejection_reason: str | None = None


class AuthResponse(CamelModel):
    access_token: str
    refresh_token: str
    user: UserDto


class DonorDto(CamelModel):
    id: int
    full_name: str
    blood_group: BloodGroup
    rhesus: Rhesus
    latitude: float
    longitude: float
    distance_km: float


class DonorProfileDto(CamelModel):
    id: int
    full_name: str
    sex: Sex | None = None
    medical_history: str
    phone: str | None = None
    blood_group: BloodGroup | None = None
    rhesus: Rhesus | None = None
    document_url: str | None = None
    status: AccountStatus
    is_available: bool
    share_location: bool
    last_donation_at: datetime | None = None


class PatientDto(CamelModel):
    id: int
    blood_group: BloodGroup | None = None
    rhesus: Rhesus | None = None
    latitude: float | None = None
    longitude: float | None = None


class StructureDto(CamelModel):
    id: int
    name: str
    address: str
    latitude: float
    longitude: float
    phone: str
    status: AccountStatus
    donation_fee: int | None = None
    distance_km: float | None = None


class StockDto(CamelModel):
    structure_id: int
    structure_name: str
    blood_group: BloodGroup
    rhesus: Rhesus
    quantity: int
    updated_at: datetime
    distance_km: float | None = None


class AppointmentDto(CamelModel):
    id: int
    patient_id: int
    patient_name: str
    donor_id: int
    donor_name: str
    structure_id: int
    structure_name: str
    scheduled_at: datetime
    status: AppointmentStatus
    hospital_fee: int | None = None
    created_at: datetime


class PaymentDto(CamelModel):
    id: int
    appointment_id: int
    amount: int
    platform_fee: int
    operator: PaymentOperator
    reference: str | None = None
    status: PaymentStatus


class CampaignDto(CamelModel):
    id: int
    structure_id: int
    structure_name: str
    title: str
    location: str
    start_date: datetime
    end_date: datetime
    target_donations: int
    funds_received: int
    joined: bool
    description: str | None = None
    image_url: str | None = None


class FundingDto(CamelModel):
    id: int
    campaign_id: int
    campaign_title: str
    amount: int
    created_at: datetime
    status: PaymentStatus


class SponsorDto(CamelModel):
    id: int
    organisation: str
    contact: str
    logo_url: str | None = None


class NotificationDto(CamelModel):
    id: int
    title: str
    message: str
    read: bool
    created_at: datetime
    appointment_id: int | None = None


class EligibilityDto(CamelModel):
    can_donate: bool
    next_donation_date: datetime | None = None


class DonationDto(CamelModel):
    id: int
    donated_at: datetime
    structure_name: str
    volume_ml: int | None = None
    appointment_id: int


class AccountSummaryDto(CamelModel):
    id: int
    email: str
    role: UserRole
    status: AccountStatus
    display_name: str | None = None
    created_at: datetime


class AccountDetailDto(CamelModel):
    id: int
    email: str
    role: UserRole
    status: AccountStatus
    display_name: str | None = None
    rejection_reason: str | None = None
    created_at: datetime
    donor: DonorProfileDto | None = None
    structure: StructureDto | None = None
    sponsor: SponsorDto | None = None


class GoogleExchangeRequest(CamelModel):
    """Échange du code obtenu après la connexion Google contre des jetons (PKCE)."""

    code: str = Field(min_length=10, max_length=200)
    code_verifier: str = Field(min_length=43, max_length=128)
