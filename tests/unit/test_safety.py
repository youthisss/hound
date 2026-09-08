from __future__ import annotations

import pytest

from hound.safety import validate_recommendation, validate_recommendations


@pytest.mark.parametrize(
    "value",
    [
        "rm -rf /tmp/work",
        "kubectl delete deployment/api",
        "curl https://example.invalid/secret",
        "disable TLS verification",
        "api_key=not-a-value",
    ],
)
def test_operational_recommendations_fail_closed(value: str):
    with pytest.raises(ValueError):
        validate_recommendation(value)


def test_recommendations_are_bounded_and_non_empty():
    with pytest.raises(ValueError, match="more than"):
        validate_recommendations(["inspect logs"] * 9)
    with pytest.raises(ValueError, match="non-empty"):
        validate_recommendations([""])
