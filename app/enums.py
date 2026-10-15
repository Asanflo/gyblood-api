"""Énumérations du contrat avec l'application MAUI.

Les valeurs sont en MAJUSCULES_AVEC_TIRET_BAS : c'est ce que produit JsonNamingPolicy.SnakeCaseUpper côté C#
(Requested -> REQUESTED, NoShow -> NO_SHOW, MtnMomo -> MTN_MOMO).
"""

from enum import Enum


class UserRole(str, Enum):
    PATIENT = "PATIENT"
    DONOR = "DONOR"
    STRUCTURE = "STRUCTURE"
    SPONSOR = "SPONSOR"
    ADMIN = "ADMIN"


class AccountStatus(str, Enum):
    PENDING = "PENDING"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"


class BloodGroup(str, Enum):
    A = "A"
    B = "B"
    AB = "AB"
    O = "O"


class Rhesus(str, Enum):
    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"


class AppointmentStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ACCEPTED = "ACCEPTED"
    PAID = "PAID"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class PaymentOperator(str, Enum):
    MTN_MOMO = "MTN_MOMO"
    ORANGE_MONEY = "ORANGE_MONEY"


class PaymentStatus(str, Enum):
    PENDING = "PENDING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    REFUNDED = "REFUNDED"


class Sex(str, Enum):
    MALE = "MALE"
    FEMALE = "FEMALE"


class DonationType(str, Enum):
    WHOLE_BLOOD = "WHOLE_BLOOD"
    PLASMA = "PLASMA"
    PLATELETS = "PLATELETS"


ACTIVE_APPOINTMENT = (AppointmentStatus.REQUESTED, AppointmentStatus.ACCEPTED, AppointmentStatus.PAID)
