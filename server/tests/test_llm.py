import math

import pytest

from unspun.core.llm import LlmError, parse_json_content, truncate_embedding
from unspun.core.models import EMBEDDING_DIM


def test_truncate_embedding_truncates_and_normalizes() -> None:
    vector = [2.0] * (EMBEDDING_DIM * 2)
    out = truncate_embedding(vector)
    assert len(out) == EMBEDDING_DIM
    assert math.isclose(math.sqrt(sum(x * x for x in out)), 1.0, rel_tol=1e-9)


def test_truncate_embedding_rejects_short_vectors() -> None:
    with pytest.raises(LlmError):
        truncate_embedding([1.0] * (EMBEDDING_DIM - 1))


def test_truncate_embedding_rejects_zero_norm() -> None:
    with pytest.raises(LlmError):
        truncate_embedding([0.0] * EMBEDDING_DIM)


def test_parse_json_content_plain_and_fenced() -> None:
    assert parse_json_content('{"a": 1}') == {"a": 1}
    assert parse_json_content('```json\n{"a": 1}\n```') == {"a": 1}


def test_parse_json_content_rejects_non_object() -> None:
    with pytest.raises(LlmError):
        parse_json_content("[1, 2]")
