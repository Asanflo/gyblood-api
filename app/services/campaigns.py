from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.enums import PaymentStatus
from app.errors import ApiError
from app.models import Campaign, CampaignMember, Funding
from app.utils import as_utc


def funds_received(db: Session, campaign_id: int) -> int:
    total = db.scalar(
        select(func.coalesce(func.sum(Funding.amount), 0)).where(
            Funding.campaign_id == campaign_id, Funding.status == PaymentStatus.SUCCEEDED
        )
    )
    return int(total or 0)


def has_joined(db: Session, campaign_id: int, donor_id: int) -> bool:
    return db.get(CampaignMember, (campaign_id, donor_id)) is not None


def ensure_open(campaign: Campaign, now: datetime) -> None:
    if as_utc(campaign.end_date) < now:
        raise ApiError(409, "CAMPAIGN_CLOSED", "Cette campagne est terminée.")
