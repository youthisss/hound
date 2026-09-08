from __future__ import annotations

import pytest

from hound.urlutil import validate_http_url


@pytest.mark.parametrize(
    "value",
    [
        "https://user:password@example.test/api",
        "https://example.test/api?token=secret",
        "https://example.test/api#fragment",
        "https://example.test:bad/api",
        "http://example.test/api",
        "http://localhost.evil/api",
    ],
)
def test_http_url_validation_rejects_unsafe_forms(value: str) -> None:
    with pytest.raises(ValueError):
        validate_http_url(value)


def test_http_url_validation_allows_explicit_loopback_development_endpoint() -> None:
    assert validate_http_url("http://127.0.0.1:8123/api") == "http://127.0.0.1:8123/api"
    assert validate_http_url("https://example.test/api") == "https://example.test/api"


def test_http_url_validation_can_allow_query_without_allowing_fragment() -> None:
    assert validate_http_url("https://example.test/api?query=1", allow_query=True).endswith("query=1")
    with pytest.raises(ValueError):
        validate_http_url("https://example.test/api?query=1#fragment", allow_query=True)
