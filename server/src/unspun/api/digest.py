"""Latest and historical daily digests, served from immutable stored snapshots."""

import re
from datetime import date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, BeforeValidator
from sqlalchemy import select
from sqlalchemy.orm import Session

from unspun.api.events import EventOut, get_db
from unspun.core.models import Digest

router = APIRouter()


def iso_report_date(value: Any) -> date:
    if not isinstance(value, str) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is None:
        raise ValueError("report_date must use YYYY-MM-DD")
    return date.fromisoformat(value)


class DigestPayload(BaseModel):
    intro: str
    window_start: datetime
    window_end: datetime
    timezone: str
    events: list[EventOut]


class DigestResponse(BaseModel):
    report_date: date
    kind: str
    generated_at: datetime
    payload: DigestPayload


def digest_response(row: Digest | None) -> DigestResponse:
    if row is None:
        raise HTTPException(status_code=404, detail="Daily digest not found")
    return DigestResponse(
        report_date=row.report_date,
        kind=row.kind,
        generated_at=row.generated_at,
        payload=DigestPayload.model_validate(row.payload),
    )


@router.get("/api/digest/latest", response_model=DigestResponse)
def latest_digest(session: Session = Depends(get_db)) -> DigestResponse:  # noqa: B008
    row = session.scalar(
        select(Digest).where(Digest.kind == "daily").order_by(Digest.report_date.desc()).limit(1)
    )
    return digest_response(row)


@router.get("/api/digest/{report_date}", response_model=DigestResponse)
def historical_digest(
    report_date: Annotated[date, BeforeValidator(iso_report_date)],
    session: Session = Depends(get_db),  # noqa: B008
) -> DigestResponse:
    row = session.scalar(
        select(Digest).where(
            Digest.report_date == report_date,
            Digest.kind == "daily",
        )
    )
    return digest_response(row)
