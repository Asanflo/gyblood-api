"""Délai minimal entre deux dons (RG5)."""

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.enums import DonationType, Sex
from app.models import DonationInterval, DonorProfile

Intervals = dict[tuple[Sex, DonationType], int]

# Valeurs de départ, à remplacer par celles du CNTS via PUT /admin/settings/donation-intervals.
STARTER_INTERVALS: Intervals = {
    (Sex.MALE, DonationType.WHOLE_BLOOD): 56,
    (Sex.FEMALE, DonationType.WHOLE_BLOOD): 84,
}


def load_intervals(db: Session) -> Intervals:
    rows = db.scalars(select(DonationInterval)).all()
    return {(row.sex, row.donation_type): row.min_days for row in rows}


def min_days_for(intervals: Intervals, sex: Sex | None, donation_type: DonationType = DonationType.WHOLE_BLOOD) -> int:
    if sex is not None and (sex, donation_type) in intervals:
        return intervals[(sex, donation_type)]
    return settings.default_min_days_between_donations


def next_donation_date(donor: DonorProfile, intervals: Intervals) -> datetime | None:
    if donor.last_donation_at is None:
        return None
    return donor.last_donation_at + timedelta(days=min_days_for(intervals, donor.sex))


def is_eligible(donor: DonorProfile, intervals: Intervals, now: datetime) -> bool:
    next_date = next_donation_date(donor, intervals)
    return next_date is None or next_date <= now
