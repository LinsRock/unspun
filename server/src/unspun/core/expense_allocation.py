"""Calendar anchored billing periods and exact daily cost allocation."""

import calendar
from datetime import date
from decimal import Decimal
from typing import Literal

Cadence = Literal["once", "monthly", "yearly"]


def _anniversary(anchor: date, months: int) -> date:
    absolute_month = anchor.year * 12 + anchor.month - 1 + months
    year, month_zero = divmod(absolute_month, 12)
    month = month_zero + 1
    return date(year, month, min(anchor.day, calendar.monthrange(year, month)[1]))


def period_for_index(
    anchor: date, cadence: Cadence, index: int, once_end: date | None = None
) -> tuple[date, date]:
    if index < 0:
        raise ValueError("period index must be nonnegative")
    if cadence == "once":
        if index != 0 or once_end is None or once_end <= anchor:
            raise ValueError("one-time coverage must have a valid end")
        return anchor, once_end
    months = 1 if cadence == "monthly" else 12
    return _anniversary(anchor, months * index), _anniversary(anchor, months * (index + 1))


def allocate_days(
    amount: Decimal, coverage_start: date, coverage_end: date, start: date, end: date
) -> Decimal:
    if coverage_end <= coverage_start:
        raise ValueError("coverage end must follow start")
    if end <= start:
        return Decimal(0)
    first = max(coverage_start, min(start, coverage_end))
    last = max(coverage_start, min(end, coverage_end))
    if last <= first:
        return Decimal(0)
    duration = Decimal((coverage_end - coverage_start).days)

    def cumulative(day: date) -> Decimal:
        elapsed = Decimal((day - coverage_start).days)
        return (amount * elapsed / duration).quantize(Decimal("0.000001"))

    return cumulative(last) - cumulative(first)
