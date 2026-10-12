from dataclasses import dataclass
from datetime import UTC, datetime, time
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query

from unspun.api.admin.schemas import AdminRangeOut, AdminRangeResponse

router = APIRouter()
BEIJING = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class ResolvedRange:
    start: datetime
    end: datetime
    as_of: datetime


def resolve_range(start: datetime | None, end: datetime | None, as_of: datetime) -> ResolvedRange:
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("snapshot time must include a timezone")
    if (start is None) != (end is None):
        raise ValueError("start and end must be provided together")
    if start is None:
        local_date = as_of.astimezone(BEIJING).date()
        start = datetime.combine(local_date, time.min, tzinfo=BEIJING)
        end = as_of
    assert end is not None
    if any(value.tzinfo is None or value.utcoffset() is None for value in (start, end)):
        raise ValueError("range timestamps must include a timezone")
    start_utc = start.astimezone(UTC)
    end_utc = end.astimezone(UTC)
    as_of_utc = as_of.astimezone(UTC)
    if start_utc >= end_utc:
        raise ValueError("start must be earlier than end")
    if start_utc >= as_of_utc:
        raise ValueError("range starts after the snapshot")
    return ResolvedRange(start_utc, min(end_utc, as_of_utc), as_of_utc)


@router.get("/range", response_model=AdminRangeResponse)
def get_admin_range(
    start: datetime | None = None,
    end: datetime | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
    sort: Literal["newest", "oldest"] = "newest",
) -> AdminRangeResponse:
    try:
        resolved = resolve_range(start, end, datetime.now(UTC))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return AdminRangeResponse(
        range=AdminRangeOut(start=resolved.start, end=resolved.end),
        as_of=resolved.as_of,
        page=page,
        page_size=page_size,
        sort=sort,
    )
