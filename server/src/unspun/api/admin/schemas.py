from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class AdminRangeOut(BaseModel):
    start: datetime
    end: datetime
    timezone: Literal["Asia/Shanghai"] = "Asia/Shanghai"
    end_exclusive: bool = True


class AdminRangeResponse(BaseModel):
    range: AdminRangeOut
    as_of: datetime
    page: int
    page_size: int
    sort: Literal["newest", "oldest"]
