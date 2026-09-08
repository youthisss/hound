"""Validation primitives for licensed, sanitized evaluation corpora.

The normal Hound evaluation suite is intentionally synthetic and network-free.
This module adds a separate manifest contract for real or private partitions so
license, provenance, privacy review, and file integrity cannot be accidentally
treated as ordinary case labels.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, NoReturn, cast

from hound.fsio import read_bounded_bytes
from hound.ingest.redact import redact_text
from hound.models import KINDS, STAGES
from hound.pathutil import path_has_symlink
from hound.safety import validate_recommendations
from hound.service import SUPPORTED_LOG_SUFFIXES
from hound.urlutil import validate_http_url

MANIFEST_VERSION = "1.0"
MIN_REAL_ARTIFACTS = 500
MAX_MANIFEST_ARTIFACTS = 100_000
MAX_MANIFEST_BYTES = 8 * 1024 * 1024
MAX_ARCHIVE_BYTES = 1024 * 1024 * 1024
MAX_ARTIFACT_BYTES = 2 * 1024 * 1024
MAX_EVIDENCE_SPANS = 128
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
SAFE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")
ALLOWED_LICENSES = {
    "MIT",
    "Apache-2.0",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "CC-BY-4.0",
    "CC-BY-SA-4.0",
}
PRIVACY_REVIEW_TYPES = {
    "automated_deterministic_gate",
    "manual",
    "manual_and_automated",
}


class CorpusValidationError(ValueError):
    """Raised when a corpus cannot be trusted as an evaluation input."""


def _fail(message: str) -> NoReturn:
    raise CorpusValidationError(message)


def _required_mapping(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail(f"{name} must be an object")
    return cast(dict[str, Any], value)


def _non_empty_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail(f"{name} must be a non-empty string")
    return cast(str, value)


def _clean_string(value: object, name: str) -> str:
    text = _non_empty_string(value, name)
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in text):
        _fail(f"{name} contains control characters")
    return text


def _https_url(value: object, name: str) -> str:
    text = _clean_string(value, name)
    try:
        return validate_http_url(text, label=name, require_https=True, allow_loopback_http=False)
    except ValueError as exc:
        _fail(str(exc))


def _safe_relative_path(value: object, name: str) -> str:
    path = _clean_string(value, name).replace("\\", "/")
    candidate = Path(path)
    if candidate.is_absolute() or path.startswith("/") or re.match(r"^[A-Za-z]:", path) or ".." in candidate.parts:
        _fail(f"{name} must be a relative path without '..'")
    if path.startswith("./") or "//" in path or any(part in {"", "."} for part in candidate.parts):
        _fail(f"{name} contains a non-canonical path")
    return path


def _validate_source(source: object, index: int) -> dict[str, Any]:
    item = _required_mapping(source, f"sources[{index}]")
    expected_fields = {
        "id", "name", "license", "license_url", "metadata_url", "archive_name",
        "archive_size", "archive_sha256",
    }
    if set(item) != expected_fields:
        _fail(f"sources[{index}] fields must be exactly {sorted(expected_fields)}")
    source_id = _clean_string(item.get("id"), f"sources[{index}].id")
    if not SAFE_ID_RE.fullmatch(source_id):
        _fail(f"sources[{index}].id is not canonical")
    _clean_string(item.get("name"), f"sources[{index}].name")
    license_id = _clean_string(item.get("license"), f"sources[{index}].license")
    if license_id not in ALLOWED_LICENSES:
        _fail(f"sources[{index}].license is not approved: {license_id}")
    _https_url(item.get("license_url"), f"sources[{index}].license_url")
    metadata_url = item.get("metadata_url") or item.get("doi")
    if "metadata_url" not in item or not isinstance(metadata_url, str):
        _fail(f"sources[{index}].metadata_url is required")
    _https_url(metadata_url, f"sources[{index}].metadata_url")
    archive_name = _clean_string(item.get("archive_name"), f"sources[{index}].archive_name").replace("\\", "/")
    if Path(archive_name).name != archive_name or "/" in archive_name:
        _fail(f"sources[{index}].archive_name must be a file name")
    archive_size = item.get("archive_size")
    if type(archive_size) is not int or not 0 < archive_size <= MAX_ARCHIVE_BYTES:
        _fail(f"sources[{index}].archive_size must be a positive integer within the archive limit")
    archive_sha256 = item.get("archive_sha256")
    if not isinstance(archive_sha256, str) or not SHA256_RE.fullmatch(archive_sha256):
        _fail(f"sources[{index}].archive_sha256 must be a SHA-256 hex digest")
    return item | {
        "id": source_id,
        "name": str(item["name"]),
        "license": license_id,
        "license_url": str(item["license_url"]),
        "metadata_url": metadata_url,
    }


def _validate_privacy(value: object, name: str) -> dict[str, Any]:
    privacy = _required_mapping(value, name)
    expected_fields = {"reviewed", "review_type", "redaction_hits", "residual_matches"}
    if set(privacy) != expected_fields:
        _fail(f"{name} fields must be exactly {sorted(expected_fields)}")
    if type(privacy.get("reviewed")) is not bool or not privacy["reviewed"]:
        _fail(f"{name}.reviewed must be true")
    review_type = _clean_string(privacy.get("review_type"), f"{name}.review_type")
    if review_type not in PRIVACY_REVIEW_TYPES:
        _fail(f"{name}.review_type is not recognized")
    for key in ("redaction_hits", "residual_matches"):
        number = privacy.get(key)
        if type(number) is not int or number < 0:
            _fail(f"{name}.{key} must be a non-negative integer")
    if privacy["residual_matches"] != 0:
        _fail(f"{name}.residual_matches must be zero")
    return privacy


def _validate_artifact(
    value: object,
    index: int,
    sources: dict[str, dict[str, Any]],
    root: Path,
    check_files: bool,
) -> dict[str, Any]:
    item = _required_mapping(value, f"artifacts[{index}]")
    required_fields = {
        "case_id", "path", "source_id", "license", "split", "raw_sha256",
        "sanitized_sha256", "sanitizer_version", "privacy", "provenance",
        "evidence_spans", "verified_cause", "recommended_checks",
    }
    optional_fields = {"source_annotation", "observed_classification"}
    if set(item) - required_fields - optional_fields or not required_fields.issubset(item):
        _fail(f"artifacts[{index}] fields are unsupported or incomplete")
    case_id = _clean_string(item.get("case_id"), f"artifacts[{index}].case_id")
    if not SAFE_ID_RE.fullmatch(case_id):
        _fail(f"artifacts[{index}].case_id is not canonical")
    path_value = item.get("path")
    relative_path = _safe_relative_path(path_value, f"artifacts[{index}].path")
    suffix = Path(relative_path).suffix.lower()
    if suffix not in SUPPORTED_LOG_SUFFIXES:
        _fail(f"artifacts[{index}].path has unsupported format")
    if Path(relative_path).parent != Path("artifacts"):
        _fail(f"artifacts[{index}].path must be a direct child of artifacts/")
    source_id = _clean_string(item.get("source_id"), f"artifacts[{index}].source_id")
    if source_id not in sources:
        _fail(f"artifacts[{index}].source_id is not declared")
    license_id = _clean_string(item.get("license"), f"artifacts[{index}].license")
    if license_id not in ALLOWED_LICENSES:
        _fail(f"artifacts[{index}].license is not approved")
    if license_id != sources[source_id]["license"]:
        _fail(f"artifacts[{index}].license does not match its source license")
    split = _clean_string(item.get("split"), f"artifacts[{index}].split")
    if split not in {"real", "private", "dev", "held_out"}:
        _fail(f"artifacts[{index}].split is invalid")
    for key in ("raw_sha256", "sanitized_sha256"):
        digest = item.get(key)
        if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
            _fail(f"artifacts[{index}].{key} must be a SHA-256 hex digest")
    _validate_privacy(item.get("privacy"), f"artifacts[{index}].privacy")
    sanitizer_version = _clean_string(item.get("sanitizer_version"), f"artifacts[{index}].sanitizer_version")
    provenance = _required_mapping(item.get("provenance"), f"artifacts[{index}].provenance")
    provenance_fields = {"source_id", "source_uri", "source_sha256", "source_locator"}
    if set(provenance) != provenance_fields:
        _fail(f"artifacts[{index}].provenance fields must be exactly {sorted(provenance_fields)}")
    for key in provenance_fields:
        _clean_string(provenance.get(key), f"artifacts[{index}].provenance.{key}")
    source = sources[source_id]
    if provenance["source_id"] != source_id:
        _fail(f"artifacts[{index}].provenance.source_id does not match source_id")
    if provenance["source_uri"] != source["metadata_url"]:
        _fail(f"artifacts[{index}].provenance.source_uri does not match the declared source")
    if provenance["source_sha256"].lower() != str(source["archive_sha256"]).lower():
        _fail(f"artifacts[{index}].provenance.source_sha256 does not match the source archive")
    locator = provenance["source_locator"].replace("\\", "/")
    locator_path = locator.split("#", 1)[0]
    if (
        not locator_path
        or Path(locator_path).is_absolute()
        or locator_path.startswith("/")
        or ".." in Path(locator_path).parts
        or "//" in locator_path
    ):
        _fail(f"artifacts[{index}].provenance.source_locator is not a safe relative locator")
    spans = item.get("evidence_spans", [])
    if not isinstance(spans, list) or not spans:
        _fail(f"artifacts[{index}].evidence_spans must be a non-empty list")
    if len(spans) > MAX_EVIDENCE_SPANS:
        _fail(f"artifacts[{index}].evidence_spans contains too many spans")
    previous_end = -1
    for span_index, span in enumerate(spans):
        span_map = _required_mapping(span, f"artifacts[{index}].evidence_spans[{span_index}]")
        if set(span_map) - {"start", "end", "label", "verified", "text"}:
            _fail(f"artifacts[{index}].evidence_spans[{span_index}] contains unsupported fields")
        start, end = span_map.get("start"), span_map.get("end")
        if type(start) is not int or type(end) is not int or start < 0 or end <= start or start < previous_end:
            _fail(f"artifacts[{index}].evidence_spans[{span_index}] has invalid offsets")
        _clean_string(span_map.get("label"), f"artifacts[{index}].evidence_spans[{span_index}].label")
        if type(span_map.get("verified")) is not bool:
            _fail(f"artifacts[{index}].evidence_spans[{span_index}].verified must be boolean")
        if "text" in span_map:
            _clean_string(span_map.get("text"), f"artifacts[{index}].evidence_spans[{span_index}].text")
        previous_end = end
    cause = _required_mapping(item.get("verified_cause"), f"artifacts[{index}].verified_cause")
    if set(cause) != {"status", "root_cause_verified", "basis"}:
        _fail(f"artifacts[{index}].verified_cause fields are incomplete or unsupported")
    _clean_string(cause.get("status"), f"artifacts[{index}].verified_cause.status")
    if type(cause.get("root_cause_verified")) is not bool:
        _fail(f"artifacts[{index}].verified_cause.root_cause_verified must be boolean")
    _clean_string(cause.get("basis"), f"artifacts[{index}].verified_cause.basis")
    if cause["status"].strip().lower() == "verified" and not cause["root_cause_verified"]:
        _fail(f"artifacts[{index}].verified_cause status contradicts root_cause_verified")
    checks = item.get("recommended_checks")
    try:
        validate_recommendations(checks, field=f"artifacts[{index}].recommended_checks")
    except ValueError as exc:
        _fail(str(exc))
    if not checks:
        _fail(f"artifacts[{index}].recommended_checks must not be empty")

    if "source_annotation" in item:
        annotation = _required_mapping(item["source_annotation"], f"artifacts[{index}].source_annotation")
        if set(annotation) != {"category", "keywords", "is_adjudicated_root_cause"}:
            _fail(f"artifacts[{index}].source_annotation fields are unsupported or incomplete")
        _clean_string(annotation.get("category"), f"artifacts[{index}].source_annotation.category")
        _clean_string(annotation.get("keywords"), f"artifacts[{index}].source_annotation.keywords")
        if type(annotation.get("is_adjudicated_root_cause")) is not bool:
            _fail(f"artifacts[{index}].source_annotation.is_adjudicated_root_cause must be boolean")
        if not annotation["is_adjudicated_root_cause"] and cause["root_cause_verified"]:
            _fail(f"artifacts[{index}] claims a verified cause without an adjudicated source annotation")
    if "observed_classification" in item:
        observed = _required_mapping(item["observed_classification"], f"artifacts[{index}].observed_classification")
        if set(observed) != {"stage", "kind", "label_source"}:
            _fail(f"artifacts[{index}].observed_classification fields are unsupported or incomplete")
        if observed.get("stage") not in STAGES or observed.get("kind") not in KINDS:
            _fail(f"artifacts[{index}].observed_classification is invalid")
        _clean_string(observed.get("label_source"), f"artifacts[{index}].observed_classification.label_source")

    if check_files:
        raw_artifact = root / relative_path
        if path_has_symlink(raw_artifact) or raw_artifact.is_symlink():
            _fail(f"artifacts[{index}].path is a symlink")
        artifact = raw_artifact.resolve()
        try:
            artifact.relative_to(root.resolve())
        except ValueError:
            _fail(f"artifacts[{index}].path escapes corpus root")
        if artifact.is_symlink() or not artifact.is_file():
            _fail(f"artifacts[{index}].path is not a regular file")
        for parent in raw_artifact.parents:
            if parent == root.resolve():
                break
            if parent.is_symlink():
                _fail(f"artifacts[{index}].path contains a symlinked directory")
        try:
            raw = read_bounded_bytes(artifact, MAX_ARTIFACT_BYTES)
            text = raw.decode("utf-8")
        except (OSError, ValueError, UnicodeDecodeError) as exc:
            _fail(f"artifacts[{index}].artifact cannot be decoded safely: {exc}")
        if not raw:
            _fail(f"artifacts[{index}].artifact exceeds the safe size limit")
        if hashlib.sha256(raw).hexdigest() != item["sanitized_sha256"]:
            _fail(f"artifacts[{index}].sanitized_sha256 does not match the artifact")
        _, residual = redact_text(text)
        if residual:
            _fail(f"artifacts[{index}].artifact contains residual sensitive matches")
        for span in spans:
            if span["end"] > len(text):
                _fail(f"artifacts[{index}].evidence_spans exceeds artifact length")
            if "text" in span and span["text"] != text[span["start"]:span["end"]]:
                _fail(f"artifacts[{index}].evidence_spans text does not match artifact offsets")
    return item | {"case_id": case_id, "path": relative_path, "sanitizer_version": sanitizer_version}


def validate_manifest(
    manifest_path: str | Path,
    *,
    min_count: int = MIN_REAL_ARTIFACTS,
    check_files: bool = True,
) -> dict[str, Any]:
    """Validate a corpus manifest and return non-sensitive coverage summary."""
    if type(min_count) is not int or min_count < 1:
        raise CorpusValidationError("min_count must be a positive integer")
    manifest_input = Path(manifest_path)
    if path_has_symlink(manifest_input) or manifest_input.is_symlink() or not manifest_input.is_file():
        _fail("manifest must be a regular file, not a symlink")
    path = manifest_input.resolve()
    try:
        raw_manifest = read_bounded_bytes(path, MAX_MANIFEST_BYTES)
        data = json.loads(raw_manifest.decode("utf-8"))
    except (OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise CorpusValidationError(f"invalid corpus manifest: {exc}") from exc
    root = _required_mapping(data, "manifest")
    manifest_fields = {"manifest_version", "corpus_id", "created_at", "purpose", "sanitizer", "sources", "artifacts"}
    if set(root) != manifest_fields:
        _fail(f"manifest fields must be exactly {sorted(manifest_fields)}")
    if root.get("manifest_version") != MANIFEST_VERSION:
        _fail(f"manifest_version must be {MANIFEST_VERSION}")
    corpus_id = _clean_string(root.get("corpus_id"), "corpus_id")
    if not SAFE_ID_RE.fullmatch(corpus_id):
        _fail("corpus_id is not canonical")
    created_at = _clean_string(root.get("created_at"), "created_at")
    try:
        datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CorpusValidationError("created_at must be ISO 8601") from exc
    _clean_string(root.get("purpose"), "purpose")
    sanitizer = _required_mapping(root.get("sanitizer"), "sanitizer")
    sanitizer_fields = {"name", "version", "raw_retained", "transformations"}
    if set(sanitizer) != sanitizer_fields:
        _fail(f"sanitizer fields must be exactly {sorted(sanitizer_fields)}")
    _clean_string(sanitizer.get("name"), "sanitizer.name")
    _clean_string(sanitizer.get("version"), "sanitizer.version")
    if sanitizer.get("raw_retained") is not False:
        _fail("sanitizer.raw_retained must be false")
    transformations = sanitizer.get("transformations")
    if not isinstance(transformations, list) or not transformations or not all(
        isinstance(value, str) and value.strip() and not any(ord(char) < 0x20 or ord(char) == 0x7F for char in value)
        for value in transformations
    ):
        _fail("sanitizer.transformations must be a non-empty list of strings")
    sources_value = root.get("sources")
    if not isinstance(sources_value, list) or not sources_value:
        _fail("sources must be a non-empty list")
    sources = [_validate_source(value, index) for index, value in enumerate(cast(list[Any], sources_value))]
    source_records = {source["id"]: source for source in sources}
    if len(source_records) != len(sources):
        _fail("source IDs must be unique")
    artifacts_value = root.get("artifacts")
    if not isinstance(artifacts_value, list):
        _fail("artifacts must be a list")
    artifacts_list = cast(list[Any], artifacts_value)
    if len(artifacts_list) > MAX_MANIFEST_ARTIFACTS:
        _fail("manifest contains too many artifacts")
    if len(artifacts_list) < min_count:
        _fail(f"corpus contains {len(artifacts_list)} artifacts, requires at least {min_count}")
    artifacts = [
        _validate_artifact(value, index, source_records, path.parent, check_files)
        for index, value in enumerate(artifacts_list)
    ]
    case_ids = [item["case_id"] for item in artifacts]
    artifact_paths = [item["path"] for item in artifacts]
    raw_hashes = [item["raw_sha256"].lower() for item in artifacts]
    if len(case_ids) != len(set(case_ids)):
        _fail("artifact case IDs must be unique")
    if len(artifact_paths) != len(set(artifact_paths)):
        _fail("artifact paths must be unique")
    if len(raw_hashes) != len(set(raw_hashes)):
        _fail("raw artifact hashes must be unique")
    source_counts = {source_id: 0 for source_id in source_records}
    split_counts: dict[str, int] = {}
    format_counts: dict[str, int] = {}
    for item in artifacts:
        source_counts[item["source_id"]] += 1
        split_counts[item["split"]] = split_counts.get(item["split"], 0) + 1
        suffix = Path(item["path"]).suffix.lower().lstrip(".")
        format_counts[suffix] = format_counts.get(suffix, 0) + 1
    if check_files:
        allowed_root_entries = {path.name, "README.md", "artifacts"}
        for child in path.parent.iterdir():
            if child.name not in allowed_root_entries or child.is_symlink():
                _fail("corpus root contains an unowned or symlinked entry")
            if child.name == "README.md" and not child.is_file():
                _fail("corpus README.md must be a regular file")
        artifact_root = path.parent / "artifacts"
        if not artifact_root.is_dir() or artifact_root.is_symlink():
            _fail("corpus artifacts directory is missing or unsafe")
        actual_paths: set[str] = set()
        for child in artifact_root.rglob("*"):
            if child.is_symlink() or child.is_dir() or not child.is_file():
                _fail("corpus artifacts directory contains an unsafe entry")
            actual_paths.add(child.relative_to(path.parent).as_posix())
            if len(actual_paths) > MAX_MANIFEST_ARTIFACTS:
                _fail("corpus artifacts directory contains too many entries")
        if actual_paths != set(artifact_paths):
            _fail("corpus artifacts directory does not exactly match manifest entries")
    return {
        "manifest_version": MANIFEST_VERSION,
        "corpus_id": corpus_id,
        "artifact_count": len(artifacts),
        "unique_raw_hash_count": len(set(raw_hashes)),
        "source_count": len(sources),
        "source_counts": dict(sorted(source_counts.items())),
        "split_counts": dict(sorted(split_counts.items())),
        "format_counts": dict(sorted(format_counts.items())),
        "licenses": dict(sorted({source["license"]: sum(item["license"] == source["license"] for item in artifacts) for source in sources}.items())),
        "privacy_reviewed": all(item["privacy"]["reviewed"] for item in artifacts),
        "raw_retained": sanitizer["raw_retained"],
    }


def audit_manifest(manifest_path: str | Path, *, min_count: int = MIN_REAL_ARTIFACTS) -> dict[str, Any]:
    """Public alias used by the CLI and offline validation scripts."""
    return validate_manifest(manifest_path, min_count=min_count, check_files=True)
