"""Exposed v4 originals remain immutable and cannot replay as v6 decisions/audits.

No original receipt, score, admission or task is written or certified by this test.
"""

import gzip
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from unspun.core.content import fingerprint
from unspun.core.llm import parse_json_content
from unspun.core.member_contracts import (
    MemberAuditContent,
    MemberDecision,
    member_contract,
)

pytest_plugins = ["tests.test_billing"]
EXPOSED = Path(__file__).resolve().parents[2] / "docs/acceptance/r2-06-grounding"


def exposed(name: str) -> list[dict[str, Any]]:
    return json.loads(gzip.decompress((EXPOSED / name).read_bytes()))


AUDITS = [r for r in exposed("physical-requests.json.gz") if r["stage"] == "topic_review"]


@pytest.mark.parametrize("bill", AUDITS, ids=[r["id"] for r in AUDITS])
def test_old_real_audit_and_decision_cannot_replay_as_new_contract(
    bill: dict[str, Any],
) -> None:
    task = next(t for t in exposed("tasks.json.gz") if t["id"] == bill["task_id"])
    judgment = next(
        j
        for j in exposed("judgments.json.gz")
        if j["input_fingerprint"] == task["payload"]["decision_key"]
    )
    reconstruction = next(
        r for r in exposed("reconstructed-requests.json.gz") if r["request_id"] == bill["id"]
    )
    assert fingerprint(reconstruction["request"]) == bill["request_fingerprint"]
    historical = parse_json_content(bill["response_payload"]["choices"][0]["message"]["content"])
    with pytest.raises(ValidationError):
        MemberAuditContent.model_validate(historical)
    with pytest.raises(ValidationError):
        MemberDecision.model_validate(judgment["decision"])
    assert task["payload"]["contract"] != member_contract()
    # v5 offline projection is retained in Git/acceptance artifacts. It must not
    # reissue old semantic targets or old decisions under the new protocol.
