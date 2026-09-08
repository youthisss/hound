"""Slack alert delivery via incoming webhook."""
from __future__ import annotations

import json
from http.client import InvalidURL
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from hound.models import Ticket
from hound.urlutil import validate_http_url


class SlackError(Exception):
    """Raised when Slack webhook delivery fails."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


urlopen = build_opener(_NoRedirect()).open


def send_slack(ticket: Ticket, webhook_url: str) -> None:
    """POST a compact alert for ``ticket`` to a Slack incoming webhook."""
    if not webhook_url:
        raise SlackError("SLACK_WEBHOOK_URL is required for --slack-webhook")
    try:
        webhook_url = validate_http_url(
            webhook_url,
            label="SLACK_WEBHOOK_URL",
            require_https=True,
            allow_loopback_http=False,
        )
    except ValueError as exc:
        raise SlackError(str(exc)) from exc

    safe_title = _escape_mrkdwn(ticket.title)
    safe_body = _escape_mrkdwn(ticket.body_md[:2000])
    payload = json.dumps(
        {
            "text": f"*Hound Tracer: {safe_title}*\n{safe_body}",
        }
    ).encode("utf-8")
    request = Request(
        webhook_url,
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=30):  # noqa: S310 - user-supplied webhook URL
            pass
    except (HTTPError, URLError, OSError, InvalidURL) as exc:
        raise SlackError(str(exc)) from exc


def _escape_mrkdwn(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
