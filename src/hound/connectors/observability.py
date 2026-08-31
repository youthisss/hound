"""Bounded read-only Prometheus and Tempo-compatible evidence collection."""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from hound.connectors.model import ConnectorAudit
from hound.models import Artifacts

TIMEOUT_SECONDS = 10
MAX_RESPONSE_BYTES = 256 * 1024
MAX_METRIC_SAMPLES = 200
MAX_TRACE_IDS = 5
MAX_TRACE_SPANS = 200
_SERVICE_LABEL = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,251}[A-Za-z0-9])?")
_TRACE_ID = re.compile(r"[0-9a-fA-F]{16,32}")


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


urlopen = build_opener(_NoRedirect()).open


@dataclass
class ObservabilityBundle:
    metric_samples: list[dict] = field(default_factory=list)
    trace_spans: list[dict] = field(default_factory=list)
    audits: list[ConnectorAudit] = field(default_factory=list)


def collect_observability_bundle(
    artifacts: Artifacts,
    *,
    prometheus_url: str = "",
    prometheus_token: str = "",
    tempo_url: str = "",
    tempo_token: str = "",
    window_minutes: int = 15,
) -> ObservabilityBundle:
    """Query bounded pre/post windows and trace IDs already present in evidence."""
    bundle = ObservabilityBundle()
    service = artifacts.deployment.service or artifacts.deployment.target
    window = _deployment_window(artifacts.deployment.started_at, artifacts.deployment.finished_at, window_minutes)
    if prometheus_url and service and _SERVICE_LABEL.fullmatch(service) and window:
        start, end = window
        query = f'sum(rate(http_requests_total{{service="{service}",status=~"5.."}}[5m]))'
        params = urlencode({"query": query, "start": start.timestamp(), "end": end.timestamp(), "step": "60s"})
        payload, audit = _get_json(
            "prometheus", "query_range", service, f"{prometheus_url}/api/v1/query_range?{params}", prometheus_token,
        )
        bundle.audits.append(audit)
        if payload is not None:
            bundle.metric_samples = _parse_prometheus(payload, start, end)

    trace_ids = list(dict.fromkeys(
        event.trace_id for event in artifacts.events if _TRACE_ID.fullmatch(event.trace_id)
    ))[:MAX_TRACE_IDS]
    if tempo_url:
        for trace_id in trace_ids:
            payload, audit = _get_json(
                "tempo", "trace", trace_id, f"{tempo_url}/api/traces/{trace_id}", tempo_token,
            )
            bundle.audits.append(audit)
            if payload is not None:
                remaining = MAX_TRACE_SPANS - len(bundle.trace_spans)
                bundle.trace_spans.extend(_parse_trace(payload, trace_id)[:remaining])
            if len(bundle.trace_spans) >= MAX_TRACE_SPANS:
                break
    return bundle


def _deployment_window(started_at: str, finished_at: str, minutes: int) -> tuple[datetime, datetime] | None:
    start = _parse_time(started_at)
    if start is None:
        return None
    finish = _parse_time(finished_at) or start
    delta = timedelta(minutes=minutes)
    return start - delta, finish + delta


def _parse_time(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _get_json(
    connector: str,
    operation: str,
    resource: str,
    url: str,
    token: str,
) -> tuple[dict | None, ConnectorAudit]:
    observed_at = datetime.now(timezone.utc).isoformat()
    started = time.monotonic()
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        with urlopen(Request(url, headers=headers), timeout=TIMEOUT_SECONDS) as response:  # noqa: S310 - validated config URL
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            return None, _audit(connector, operation, resource, "failed", observed_at, started, error="response exceeded byte limit")
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("response root is not an object")
    except Exception:  # network/parsing failures are isolated from local analysis
        return None, _audit(connector, operation, resource, "failed", observed_at, started, error="bounded query failed")
    return payload, _audit(connector, operation, resource, "collected", observed_at, started, output_bytes=len(raw), returncode=200)


def _parse_prometheus(payload: dict, start: datetime, end: datetime) -> list[dict]:
    result = payload.get("data", {}).get("result", []) if isinstance(payload.get("data"), dict) else []
    if not isinstance(result, list):
        return []
    samples: list[dict] = []
    for series in result:
        if not isinstance(series, dict):
            continue
        raw_metric = series.get("metric")
        metric = raw_metric if isinstance(raw_metric, dict) else {}
        name = str(metric.get("__name__") or "http_5xx_rate")
        values = series.get("values") or ([series["value"]] if isinstance(series.get("value"), list) else [])
        for value in values:
            if not isinstance(value, list) or len(value) < 2:
                continue
            try:
                timestamp = float(value[0])
                numeric = float(value[1])
            except (TypeError, ValueError):
                continue
            samples.append({
                "metric": name,
                "value": numeric,
                "timestamp": datetime.fromtimestamp(timestamp, timezone.utc).isoformat(),
                "source": "prometheus",
                "window_start": start.isoformat(),
                "window_end": end.isoformat(),
                "uncertainty": "correlation only; metric movement does not prove deployment causality",
            })
            if len(samples) >= MAX_METRIC_SAMPLES:
                return samples
    return samples


def _parse_trace(payload: dict, trace_id: str) -> list[dict]:
    raw_spans: list[dict] = []
    if isinstance(payload.get("spans"), list):
        raw_spans.extend(span for span in payload["spans"] if isinstance(span, dict))
    raw_batches = payload.get("batches")
    batches = raw_batches if isinstance(raw_batches, list) else []
    for batch in batches:
        scopes = batch.get("scopeSpans", []) if isinstance(batch, dict) else []
        for scope in scopes if isinstance(scopes, list) else []:
            spans = scope.get("spans", []) if isinstance(scope, dict) else []
            raw_spans.extend(span for span in spans if isinstance(span, dict))
    parsed: list[dict] = []
    for span in raw_spans[:MAX_TRACE_SPANS]:
        start_ns = _integer(span.get("startTimeUnixNano") or span.get("start_ns"))
        end_ns = _integer(span.get("endTimeUnixNano") or span.get("end_ns"))
        parsed.append({
            "trace_id": str(span.get("traceId") or span.get("trace_id") or trace_id),
            "span_id": str(span.get("spanId") or span.get("span_id") or ""),
            "parent_span_id": str(span.get("parentSpanId") or span.get("parent_span_id") or ""),
            "service": str(span.get("service") or span.get("serviceName") or ""),
            "name": str(span.get("name") or ""),
            "start_ns": start_ns,
            "end_ns": end_ns,
            "duration_ns": max(0, end_ns - start_ns) if start_ns and end_ns else 0,
            "status": str(span.get("status") or "unknown"),
            "version": str(span.get("version") or ""),
            "source": "tempo",
            "uncertainty": "runtime trace evidence; missing spans may produce a partial path",
        })
    return parsed


def _integer(value: object) -> int:
    try:
        if isinstance(value, (str, bytes, bytearray, int, float)):
            return int(value or 0)
        return 0
    except (TypeError, ValueError):
        return 0


def _audit(
    connector: str,
    operation: str,
    resource: str,
    status: str,
    observed_at: str,
    started: float,
    *,
    output_bytes: int = 0,
    returncode: int | None = None,
    error: str = "",
) -> ConnectorAudit:
    return ConnectorAudit(
        connector=connector,
        operation=operation,
        resource=resource,
        namespace="",
        status=status,
        observed_at=observed_at,
        duration_ms=max(0, int((time.monotonic() - started) * 1000)),
        output_bytes=output_bytes,
        returncode=returncode,
        error=error,
    )
