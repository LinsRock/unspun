"""Explicit billing cutover and read-only provider reconciliation commands."""

import argparse
import json
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy.orm import Session

from unspun.core.billing import DatabaseJournal, budget_status, initialize_budget, usd
from unspun.core.billing_models import BilledRequest
from unspun.core.config import get_settings
from unspun.core.db import get_engine
from unspun.core.llm import LlmError


def provider_key_status(client: httpx.Client) -> dict[str, Any]:
    response = client.get("/key")
    response.raise_for_status()
    data: dict[str, Any] = response.json()["data"]
    if usd(data.get("usage")) is None or usd(data.get("usage_monthly")) is None:
        raise LlmError("provider usage counters are unavailable")
    if data.get("limit_reset") not in (None, "monthly"):
        raise LlmError("provider key reset period requires reviewed budget support")
    if data.get("limit") is not None and usd(data.get("limit")) is None:
        raise LlmError("provider limit is invalid")
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=("status", "initialize-evaluation", "initialize-production", "reconcile")
    )
    parser.add_argument("--request-id")
    args = parser.parse_args()
    settings = get_settings()
    engine = get_engine()
    with (
        httpx.Client(
            base_url=settings.openrouter_base_url,
            headers={"Authorization": f"Bearer {settings.openrouter_api_key}"},
            timeout=30,
        ) as client,
        Session(engine) as session,
    ):
        if args.action == "initialize-evaluation":
            initialize_budget(session, scope="evaluation")
            session.commit()
        elif args.action == "initialize-production":
            data = provider_key_status(client)
            initialize_budget(
                session,
                scope="production",
                provider_monthly_usd=Decimal(str(data["usage_monthly"])),
                provider_usage_usd=Decimal(str(data["usage"])),
                provider_limit_usd=usd(data.get("limit")),
                provider_limit_kind="monthly"
                if data.get("limit_reset") == "monthly"
                else "lifetime",
            )
            session.commit()
        elif args.action == "reconcile":
            row = session.get(BilledRequest, args.request_id)
            if row is None or not row.provider_generation_id:
                raise LlmError("request has no reconcilable generation identifier")
            generation_id, identity = row.provider_generation_id, row.id
            session.rollback()
            response = client.get("/generation", params={"id": generation_id})
            response.raise_for_status()
            DatabaseJournal(engine).reconcile(identity, response.json()["data"])
        print(json.dumps(budget_status(session), default=str, sort_keys=True))


if __name__ == "__main__":
    main()
