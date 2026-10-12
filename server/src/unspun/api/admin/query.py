"""Shared bounded query parameters for admin history."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Query

from unspun.api.admin.ranges import ResolvedRange, resolve_range

Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]


def admin_range(start: datetime | None = None, end: datetime | None = None) -> ResolvedRange:
    try:
        return resolve_range(start, end, datetime.now(UTC))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


RangeDep = Annotated[ResolvedRange, Depends(admin_range)]


def page_result(
    rows: list[dict[str, object]], period: ResolvedRange, page: int, page_size: int
) -> dict[str, object]:
    return {
        "range": {
            "start": period.start,
            "end": period.end,
            "timezone": "Asia/Shanghai",
            "end_exclusive": True,
        },
        "as_of": period.as_of,
        "page": page,
        "page_size": page_size,
        "total": len(rows),
        "items": rows[(page - 1) * page_size : page * page_size],
    }
