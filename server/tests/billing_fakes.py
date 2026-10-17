"""Journal fake for legacy response-parsing tests, not budget verification."""

import uuid
from typing import Any

from sqlalchemy.orm import Session

from unspun.core.billing import CallContext, Reservation, token_count
from unspun.core.models import LlmUsage


class RecordingJournal:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.requests: dict[str, tuple[str, str]] = {}

    def reserve(
        self, *, purpose: str, model: str, request: dict[str, Any], context: CallContext
    ) -> Reservation:
        identity = uuid.uuid4().hex
        self.requests[identity] = (purpose, model)
        return Reservation(identity)

    def identify(self, identity: str, generation_id: str, http_status: int) -> None:
        pass

    def finish(self, identity: str, data: dict[str, Any], http_status: int) -> bool:
        usage = data["usage"]
        purpose, model = self.requests[identity]
        self.session.add(
            LlmUsage(
                purpose=purpose,
                model=model,
                prompt_tokens=token_count(usage.get("prompt_tokens")),
                completion_tokens=token_count(usage.get("completion_tokens")),
                cost_usd=usage["cost"],
            )
        )
        return True

    def unknown(self, identity: str, reason: str, http_status: int | None = None) -> None:
        pass
