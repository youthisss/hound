"""Slack alert delivery via incoming webhook."""
from __future__ import annotations

import json
from http.client import InvalidURL
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlsplit

from hound_agent.models import Ticket


class SlackError(Exception):
    """Raised when Slack webhook delivery fails."""


def send_slack(ticket: Ticket, webhook_url: str) -> None:
    """POST a compact alert for ``ticket`` to a Slack incoming webhook."""
    if not webhook_url:
        raise SlackError("SLACK_WEBHOOK_URL is required for --slack-webhook")
    parsed = urlsplit(webhook_url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise SlackError("SLACK_WEBHOOK_URL must be a valid HTTPS URL")

    safe_title = _escape_mrkdwn(ticket.title)
    safe_body = _escape_mrkdwn(ticket.body_md[:2000])
    payload = json.dumps(
        {
            "text": f"*Hound Agent: {safe_title}*\n{safe_body}",
        }
    ).encode("utf-8")
    request = Request(
        webhook_url,
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=30) as resp:  # noqa: S310 - user-supplied webhook URL
            resp.read()
    except (HTTPError, URLError, OSError, InvalidURL) as exc:
        raise SlackError(str(exc)) from exc


def _escape_mrkdwn(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
