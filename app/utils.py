from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    """Normalise une date en UTC ; une date sans fuseau est considérée comme UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def fmt_date(value: datetime) -> str:
    return as_utc(value).strftime("%d/%m/%Y")
