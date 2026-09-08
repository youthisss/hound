#!/usr/bin/env python3
"""Acquire and sanitize the redistributable LogChunks evaluation corpus.

This command is deliberately opt-in and network-free when ``--archive`` is
provided.  It verifies the pinned Zenodo archive before extraction, rejects
unsafe ZIP members, retains only sanitized annotation chunks, and writes a
manifest containing the source locator and hashes needed for later review.
The original archive is never copied into the repository output.
"""
from __future__ import annotations

import argparse
from collections.abc import Iterator
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
from typing import Any
from urllib.request import Request, urlopen
import zipfile

from defusedxml import ElementTree as ET
from defusedxml.common import DefusedXmlException

from hound.analyze.fallback import FIX_BY_KIND
from hound.eval_corpus import ALLOWED_LICENSES, MIN_REAL_ARTIFACTS
from hound.ingest.logs import parse_log
from hound.ingest.redact import redact_text
from hound.pathutil import path_has_symlink


SOURCE_ID = "logchunks-zenodo-3632351"
SOURCE_URI = "https://zenodo.org/records/3632351"
SOURCE_LICENSE = "CC-BY-4.0"
SOURCE_LICENSE_URL = "https://creativecommons.org/licenses/by/4.0/"
DEFAULT_DOWNLOAD_URL = "https://zenodo.org/records/3632351/files/LogChunks.zip?download=1"
EXPECTED_ARCHIVE_SHA256 = "fa2e3d10fc700cfe06b92b286741666a6389b46548356da9f0679c0d89be7fa8"
EXPECTED_ARCHIVE_SIZE = 24_108_826
SANITIZER_NAME = "hound-logchunks-sanitizer"
SANITIZER_VERSION = "1.0"
MAX_DOWNLOAD_BYTES = 128 * 1024 * 1024
MAX_CHUNK_BYTES = 2 * 1024 * 1024
MAX_ZIP_MEMBERS = 10_000
MAX_EXTRACTED_BYTES = 512 * 1024 * 1024
MAX_EXTRACTED_MEMBER_BYTES = 64 * 1024 * 1024
MAX_CASE_ID_LENGTH = 80
_CASE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")
_SENSITIVE_LINE_RE = re.compile(
    r"error|fail|exception|traceback|timeout|panic|denied|forbidden|"
    r"unauthori[sz]ed|segmentation|oom|certificate|dependency|assert",
    re.IGNORECASE,
)


class AcquisitionError(ValueError):
    """Raised when source acquisition or sanitization cannot be trusted."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _download(url: str, destination: Path) -> None:
    """Download one pinned source with a hard byte limit.

    Redirects are accepted only by the standard HTTPS client for the pinned
    Zenodo URL; the resulting bytes are still checked against the archive
    digest before they can be extracted.
    """
    if url != DEFAULT_DOWNLOAD_URL:
        raise AcquisitionError("download URL is not on the pinned Zenodo source")
    destination = destination.expanduser()
    if path_has_symlink(destination) or destination.is_symlink() or destination.exists():
        raise AcquisitionError("download destination must not already exist or contain symlinked components")
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = Request(url, headers={"Accept": "application/zip"})
    try:
        with urlopen(request, timeout=30) as response, destination.open("wb") as output:
            total = 0
            while chunk := response.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_DOWNLOAD_BYTES:
                    raise AcquisitionError("source archive exceeds the acquisition size limit")
                output.write(chunk)
        if destination.stat().st_size != EXPECTED_ARCHIVE_SIZE or _sha256(destination).lower() != EXPECTED_ARCHIVE_SHA256:
            raise AcquisitionError("downloaded source archive does not match the pinned Zenodo artifact")
    except AcquisitionError:
        destination.unlink(missing_ok=True)
        raise
    except OSError as exc:
        destination.unlink(missing_ok=True)
        raise AcquisitionError(f"could not download pinned source archive: {exc}") from exc


def _safe_zip_member(name: str) -> None:
    normalized = name.replace("\\", "/")
    candidate = Path(normalized)
    if "\x00" in name or len(name) > 1024 or not normalized or candidate.is_absolute() or normalized.startswith("/") or re.match(
        r"^[A-Za-z]:", normalized
    ) or any(
        part in {"", ".", ".."} for part in candidate.parts
    ):
        raise AcquisitionError(f"archive contains an unsafe member path: {name!r}")


def _extract_archive(archive: Path, destination: Path) -> None:
    try:
        with zipfile.ZipFile(archive) as source:
            members = source.infolist()
            if len(members) > MAX_ZIP_MEMBERS:
                raise AcquisitionError("source archive contains too many members")
            extracted_bytes = 0
            files: set[str] = set()
            directories: set[str] = set()
            for member in members:
                _safe_zip_member(member.filename)
                normalized = member.filename.replace("\\", "/")
                canonical = normalized.rstrip("/")
                key = canonical.casefold()
                if not canonical or key in files or key in directories:
                    raise AcquisitionError(f"archive contains a duplicate or colliding member: {member.filename!r}")
                mode = stat.S_IFMT((member.external_attr >> 16) & 0xFFFF)
                if mode not in {0, stat.S_IFREG, stat.S_IFDIR}:
                    raise AcquisitionError(f"archive contains a special member: {member.filename!r}")
                is_directory = member.is_dir()
                if mode == stat.S_IFDIR and not is_directory:
                    raise AcquisitionError(f"archive directory member is malformed: {member.filename!r}")
                if is_directory and mode == stat.S_IFREG:
                    raise AcquisitionError(f"archive directory has a conflicting file mode: {member.filename!r}")
                if member.file_size > MAX_EXTRACTED_MEMBER_BYTES:
                    raise AcquisitionError(f"archive member is too large: {member.filename!r}")
                extracted_bytes += member.file_size
                if extracted_bytes > MAX_EXTRACTED_BYTES:
                    raise AcquisitionError("source archive expands beyond the extraction size limit")
                parts = canonical.split("/")
                parent_keys = ["/".join(parts[:index]).casefold() for index in range(1, len(parts))]
                if any(parent in files for parent in parent_keys):
                    raise AcquisitionError(f"archive member is nested below a file: {member.filename!r}")
                if is_directory:
                    if key in files:
                        raise AcquisitionError(f"archive member collides with a file: {member.filename!r}")
                    directories.add(key)
                    directories.update(parent_keys)
                else:
                    if key in directories:
                        raise AcquisitionError(f"archive member collides with a directory: {member.filename!r}")
                    files.add(key)
                    directories.update(parent_keys)
                target = destination / canonical
                if is_directory:
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                for parent in target.parents:
                    if parent == destination:
                        break
                    if parent.is_symlink():
                        raise AcquisitionError("archive member escaped through a symlinked directory")
                target.parent.mkdir(parents=True, exist_ok=True)
                try:
                    target.parent.resolve().relative_to(destination.resolve())
                    target.resolve().relative_to(destination.resolve())
                except ValueError as exc:
                    raise AcquisitionError("archive member escaped extraction directory") from exc
                flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
                try:
                    target_fd = os.open(target, flags, 0o600)
                except FileExistsError as exc:
                    raise AcquisitionError(f"archive member collides with an existing path: {member.filename!r}") from exc
                try:
                    with source.open(member, "r") as input_stream, os.fdopen(target_fd, "wb") as output:
                        target_fd = None
                        copied = 0
                        while chunk := input_stream.read(1024 * 1024):
                            copied += len(chunk)
                            if copied > MAX_EXTRACTED_MEMBER_BYTES:
                                raise AcquisitionError(f"archive member expanded beyond its limit: {member.filename!r}")
                            output.write(chunk)
                finally:
                    if target_fd is not None:
                        os.close(target_fd)
    except (zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        raise AcquisitionError("source archive is not a valid ZIP") from exc
    except OSError as exc:
        raise AcquisitionError(f"could not extract source archive: {exc}") from exc


def _source_root(extracted: Path) -> Path:
    candidates = [extracted, extracted / "LogChunks"]
    for candidate in candidates:
        if (candidate / "build-failure-reason").is_dir():
            return candidate
    matches = [path.parent for path in extracted.rglob("*.xml") if path.parent.name == "build-failure-reason"]
    if matches:
        return matches[0].parent
    raise AcquisitionError("archive does not contain LogChunks/build-failure-reason")


def _sanitize_metadata(value: str) -> str:
    sanitized, _ = redact_text(value)
    _, residual = redact_text(sanitized)
    if residual:
        raise AcquisitionError("source annotation contains a residual sensitive pattern")
    return sanitized


def _iter_examples(root: Path) -> Iterator[tuple[str, int, str, str, str]]:
    annotation_root = root / "build-failure-reason"
    for xml_path in sorted(annotation_root.rglob("*.xml")):
        relative_xml = xml_path.relative_to(root).as_posix()
        try:
            tree = ET.parse(xml_path)
        except (DefusedXmlException, ET.ParseError, OSError) as exc:
            raise AcquisitionError(f"could not parse annotation file {relative_xml!r}") from exc
        examples = tree.getroot().findall(".//Example")
        for index, example in enumerate(examples):
            chunk = example.findtext("Chunk") or ""
            if not chunk.strip():
                continue
            category = _sanitize_metadata(example.findtext("Category") or "")
            keywords = _sanitize_metadata(example.findtext("Keywords") or "")
            yield relative_xml, index, chunk, category, keywords


def _safe_case_id(index: int) -> str:
    case_id = f"logchunks-{index:04d}"
    if len(case_id) > MAX_CASE_ID_LENGTH or not _CASE_ID_RE.fullmatch(case_id):
        raise AcquisitionError("generated case ID is invalid")
    return case_id


def _evidence_spans(text: str, kind: str) -> list[dict[str, Any]]:
    spans: list[dict[str, Any]] = []
    offset = 0
    for line in text.splitlines(keepends=True):
        content = line.rstrip("\r\n")
        end = offset + len(content)
        if content.strip() and _SENSITIVE_LINE_RE.search(content):
            spans.append({
                "start": offset,
                "end": end,
                "label": "observed_failure_signal",
                "verified": False,
            })
            if len(spans) >= 8:
                break
        offset += len(line)
    if not spans:
        end = len(text)
        spans.append({
            "start": 0,
            "end": max(1, end),
            "label": "observed_log_chunk",
            "verified": False,
        })
    return spans


def _sanitize_chunk(raw: str) -> tuple[str, int]:
    if len(raw.encode("utf-8")) > MAX_CHUNK_BYTES:
        raise AcquisitionError("source chunk exceeds the artifact size limit")
    normalized = raw.replace("\r\n", "\n").replace("\r", "\n")
    sanitized, hits = redact_text(normalized)
    _, residual = redact_text(sanitized)
    if residual:
        raise AcquisitionError("sanitizer left a residual sensitive pattern")
    if not sanitized.strip():
        raise AcquisitionError("sanitizer produced an empty artifact")
    if len(sanitized.encode("utf-8")) > MAX_CHUNK_BYTES:
        raise AcquisitionError("sanitized source chunk exceeds the artifact size limit")
    return sanitized, hits


def _manifest(
    *,
    archive: Path,
    artifacts: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "manifest_version": "1.0",
        "corpus_id": "hound-real-logchunks-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "purpose": (
            "Redistributable sanitized real-world CI build-failure chunks for parser and evidence review. "
            "Source annotations are descriptive labels, not adjudicated Hound root causes."
        ),
        "sanitizer": {
            "name": SANITIZER_NAME,
            "version": SANITIZER_VERSION,
            "raw_retained": False,
            "transformations": [
                "UTF-8 text decoding from XML Chunk values",
                "CRLF/CR normalized to LF",
                "hound deterministic secret and PII redaction patterns",
                "residual redaction scan",
            ],
        },
        "sources": [{
            "id": SOURCE_ID,
            "name": "LogChunks",
            "license": SOURCE_LICENSE,
            "license_url": SOURCE_LICENSE_URL,
            "metadata_url": SOURCE_URI,
            "archive_name": archive.name,
            "archive_size": archive.stat().st_size,
            "archive_sha256": _sha256(archive),
        }],
        "artifacts": artifacts,
    }


def build_corpus(archive: Path, output: Path, minimum: int, limit: int | None = None) -> dict[str, Any]:
    if type(minimum) is not int or minimum < 1:
        raise AcquisitionError("minimum artifact count must be a positive integer")
    if limit is not None and (type(limit) is not int or limit < minimum):
        raise AcquisitionError("limit must be at least the minimum artifact count")
    if SOURCE_LICENSE not in ALLOWED_LICENSES:
        raise AcquisitionError("pinned source license is not allowlisted")
    archive = archive.expanduser()
    if path_has_symlink(archive) or not archive.is_file() or archive.is_symlink():
        raise AcquisitionError("--archive must be a regular file")
    if archive.stat().st_size != EXPECTED_ARCHIVE_SIZE:
        raise AcquisitionError("source archive size does not match the pinned Zenodo artifact")
    archive_hash = _sha256(archive)
    if archive_hash.lower() != EXPECTED_ARCHIVE_SHA256:
        raise AcquisitionError("source archive SHA-256 does not match the pinned Zenodo artifact")
    output = output.expanduser()
    if path_has_symlink(output) or output.is_symlink():
        raise AcquisitionError("output directory must not contain symlinked path components")
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise AcquisitionError("output directory must be absent or empty; refusing to overwrite corpus data")
    output = Path(os.path.abspath(output))
    output.parent.mkdir(parents=True, exist_ok=True)
    if path_has_symlink(output.parent):
        raise AcquisitionError("output directory parent must not contain symlinked path components")
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}.staging-", dir=str(output.parent)))
    artifacts_dir = staging / "artifacts"
    artifacts_dir.mkdir()
    seen_raw: set[str] = set()
    manifest_artifacts: list[dict[str, Any]] = []
    try:
        with tempfile.TemporaryDirectory(prefix="hound-logchunks-") as temp:
            extracted = Path(temp) / "extract"
            extracted.mkdir()
            _extract_archive(archive, extracted)
            root = _source_root(extracted)
            for _xml, _example, raw, category, keywords in _iter_examples(root):
                raw_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
                if raw_hash in seen_raw:
                    continue
                seen_raw.add(raw_hash)
                if limit is not None and len(manifest_artifacts) >= limit:
                    break
                try:
                    sanitized, redaction_hits = _sanitize_chunk(raw)
                except AcquisitionError:
                    # An unsafe item is rejected, never silently included. The
                    # source is still usable when enough independently sanitized
                    # examples remain; the manifest records only accepted items.
                    continue
                case_id = _safe_case_id(len(manifest_artifacts) + 1)
                relative_artifact = f"artifacts/{case_id}.log"
                artifact_path = staging / relative_artifact
                artifact_path.write_text(sanitized, encoding="utf-8", newline="\n")
                stage, kind, _summary, _message = parse_log(sanitized)
                manifest_artifacts.append({
                    "case_id": case_id,
                    "path": relative_artifact,
                    "source_id": SOURCE_ID,
                    "license": SOURCE_LICENSE,
                    "split": "real",
                    "raw_sha256": raw_hash,
                    "sanitized_sha256": hashlib.sha256(sanitized.encode("utf-8")).hexdigest(),
                    "sanitizer_version": SANITIZER_VERSION,
                    "privacy": {
                        "reviewed": True,
                        "review_type": "automated_deterministic_gate",
                        "redaction_hits": redaction_hits,
                        "residual_matches": 0,
                    },
                    "provenance": {
                        "source_id": SOURCE_ID,
                        "source_uri": SOURCE_URI,
                        "source_sha256": archive_hash,
                        "source_locator": f"{_xml}#Example[{_example}]",
                    },
                    "source_annotation": {
                        "category": category,
                        "keywords": keywords,
                        "is_adjudicated_root_cause": False,
                    },
                    "observed_classification": {
                        "stage": stage,
                        "kind": kind,
                        "label_source": "hound-parser-v1; not ground truth",
                    },
                    "evidence_spans": _evidence_spans(sanitized, kind),
                    "verified_cause": {
                        "status": "not_adjudicated",
                        "root_cause_verified": False,
                        "basis": "LogChunks supplies failure chunks and source annotations, not Hound RCA adjudications.",
                    },
                    "recommended_checks": [FIX_BY_KIND.get(kind, FIX_BY_KIND["unknown"])],
                })
        if len(manifest_artifacts) < minimum:
            raise AcquisitionError(
                f"only {len(manifest_artifacts)} safe unique artifacts remained; requires at least {minimum}"
            )
        manifest = _manifest(archive=archive, artifacts=manifest_artifacts)
        (staging / "manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        if output.exists():
            if output.is_symlink() or not output.is_dir() or any(output.iterdir()):
                raise AcquisitionError("output directory changed during acquisition; refusing to overwrite it")
            output.rmdir()
            removed_empty_output = True
        else:
            removed_empty_output = False
        try:
            os.replace(staging, output)
        except OSError:
            if removed_empty_output and not output.exists():
                try:
                    os.replace(staging, output)
                    staging = output
                except OSError:
                    pass
            raise
        staging = output
        return {
            "corpus_id": manifest["corpus_id"],
            "artifact_count": len(manifest_artifacts),
            "archive_sha256": archive_hash,
            "output": str(output),
        }
    finally:
        if staging != output:
            shutil.rmtree(staging, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--archive", type=Path, help="verified local LogChunks.zip; no network access is used")
    source.add_argument("--download", action="store_true", help="download only the pinned Zenodo archive")
    parser.add_argument("--download-to", type=Path, help="destination for --download (outside the corpus output)")
    parser.add_argument("--output", type=Path, default=Path("data/eval/real-logchunks"))
    parser.add_argument("--min-count", type=int, default=MIN_REAL_ARTIFACTS)
    parser.add_argument("--limit", type=int, default=None, help="optional deterministic cap; must still meet --min-count")
    args = parser.parse_args(argv)
    if args.min_count < 1 or args.limit is not None and args.limit < args.min_count:
        parser.error("--min-count must be positive and --limit must be at least --min-count")
    try:
        with tempfile.TemporaryDirectory(prefix="hound-logchunks-download-") as temp:
            if args.download:
                destination = args.download_to or Path(temp) / "LogChunks.zip"
                destination.parent.mkdir(parents=True, exist_ok=True)
                _download(DEFAULT_DOWNLOAD_URL, destination)
                if args.download_to is not None:
                    print(json.dumps({"downloaded": str(destination), "sha256": _sha256(destination)}))
                    return 0
                archive = destination
            else:
                archive = args.archive
            result = build_corpus(archive, args.output, args.min_count, args.limit)
            print(json.dumps(result, sort_keys=True))
    except (AcquisitionError, OSError, ValueError) as exc:
        parser.exit(2, f"acquisition failed: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
