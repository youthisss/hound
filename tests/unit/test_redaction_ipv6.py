import pytest

from hound.ingest.redact import redact_text


@pytest.mark.parametrize("address", [
    "2001:db8::1", "::1", "::", "fe80::1%eth0",
    "2001:0db8:85a3:0000:0000:8a2e:0370:7334", "::ffff:192.0.2.1",
])
def test_ipv6_is_scrubbed_in_logs_and_urls(address):
    text = f"client_ip={address}\nremote=http://[{address}]:8080/path"
    redacted, hits = redact_text(text)
    assert redacted == "client_ip=[REDACTED:ipv6_address]\nremote=http://[[REDACTED:ipv6_address]]:8080/path"
    assert hits == 2
    assert redact_text(redacted) == (redacted, 0)


def test_ipv6_preserves_sentence_punctuation_and_non_addresses():
    redacted, hits = redact_text("Peer 2001:db8::1. At 12:34:56 test_file.py::test_run passed.")
    assert redacted == "Peer [REDACTED:ipv6_address]. At 12:34:56 test_file.py::test_run passed."
    assert hits == 1
