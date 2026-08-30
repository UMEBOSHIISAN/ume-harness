#!/usr/bin/env python3
"""Build and compare the public release mirror from the canonical repository.

This command has no publish, push, merge, import, or reverse-sync operation.
Its only supported direction is a clean ume-harness-engineering checkout to a
deterministic staging directory, followed by a read-only public mirror compare.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
from typing import Any


CANONICAL_REPOSITORY = "https://github.com/UMEBOSHIISAN/ume-harness-engineering.git"
PUBLIC_MIRROR_REPOSITORY = "https://github.com/UMEBOSHIISAN/ume-harness.git"
EXPECTED_INSTALL_ROOT_DIGEST = "88ab3241986771ee01deb8a860c17cee0cc4e4e6bc46f4077092c8ad84b723f8"
EXPECTED_HEALTH_CHECK_SHA256 = "302eb1b19e62c3f2de647cf0c14ccea7f4f387ab0bb2198217ae3479e842f102"
OWNED_INSTALL_HEALTH_ANCHORS = {
    "88ab3241986771ee01deb8a860c17cee0cc4e4e6bc46f4077092c8ad84b723f8":
        "302eb1b19e62c3f2de647cf0c14ccea7f4f387ab0bb2198217ae3479e842f102",
    "d4bc55557dff6000c76a2e72fc28baaafd262ed7cbd4abc3fe75f602095526ab":
        "eb9ab9f64c5d536871538a455983d30899490a1d0340d9d8dcc724202310f059",
    "9cb9c48b520b59e2a269a96f760a28d702c4dcb84e46b7eae32f1b064a1f3ff5":
        "c29ca598d75f5fdf3663e965bcc2a28836aff2d1601fe9b3f69b3f146e2d3805",
    "a112e364f71ecfdd486008004a69f72f32a1f06ddbbda2b1cbcb32b9e34e897b":
        "6356d04c7fc9de1e99622f24cec86351579050fa003e2f960f9b04d12359bf2c",
    "f063ae351f2ca0c769fba0375de8b912630e35f0ef2731fe403621a0b88e91a9":
        "b77408b858faebb806847b26ce57231b3576260ff822cc727f5707108021ba99",
    "be8217ac375e7cde1ce682a0031ff4b2912fe02b83d9305e73dfd8524b5a0d82":
        "7108b1ad256cbefa2ca3e5be62e16a0fe8f1f7750a3c742ace74b0ece96a8f05",
    "5e543d5b0c51bee9a81c24b3846eab23ad951db13c3ccc9966f7cc28ca901163":
        "2a2df1f9291fc7dab1fd5a8cea363c9385b45def28c3dcda9f12546c057feb3f",
    "ad24b7e04940f836d26dae439de5a217da74984ce91b912342d2182fcbff79d9":
        "78c75d1650f67b12cb3e6d2c694287fec14a08dedc15adca9f88cc5261548434",
    "d7c968f7d25e4b419992471e374b16f8b1f92053fe10041f740c2d3946629b1a":
        "56048d211061f5ebf0b0078aa08b41804cdb0bca3fa1a2227ef3ba2a1875a2d3",
    "27f2d1a77d6c4ff8c284d3de77533dd9e5b07e240eabdd69d65a88cb15ddb25a":
        "372da4dd0be546dec8e061b955ec8106ce14ff1f44829c07c0cf9fb44ce88918",
    "0c93aee7215591be7249d1cb4e0e28371e00afadfd8138236bd587e98bdc4b38":
        "6163079be522d62a15b1c5da211cb3a8a281d9dde8bdc6de83781a2f09307a87",
}
INSTALL_IDENTITY_ALGORITHM = "sha256-canonical-path-map-v1"


class ReleaseError(RuntimeError):
    pass


def _run_git(source: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(source), *args],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise ReleaseError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


def _run_git_bytes(source: Path, *args: str) -> bytes:
    proc = subprocess.run(
        ["git", "-C", str(source), *args],
        capture_output=True,
    )
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", errors="replace").strip()
        raise ReleaseError(f"git {' '.join(args)} failed: {detail}")
    return proc.stdout


def _normalized_repository(value: str) -> str:
    value = value.strip().rstrip("/")
    if value.startswith("git@github.com:"):
        value = "https://github.com/" + value[len("git@github.com:"):]
    return value[:-4] if value.endswith(".git") else value


def _load_contract(source: Path) -> dict[str, Any]:
    try:
        manifest = json.loads((source / "package_manifest.json").read_text(encoding="utf-8"))
        contract = manifest["release"]
    except Exception as e:
        raise ReleaseError(f"invalid package release contract: {e}") from e
    if contract.get("canonical_repository") != CANONICAL_REPOSITORY:
        raise ReleaseError("release canonical_repository does not name ume-harness-engineering")
    if contract.get("public_mirror_repository") != PUBLIC_MIRROR_REPOSITORY:
        raise ReleaseError("release public_mirror_repository does not name ume-harness")
    if contract.get("promotion_direction") != "canonical_to_public_only":
        raise ReleaseError("release promotion direction must be canonical_to_public_only")
    if contract.get("public_source_edits_supported") is not False:
        raise ReleaseError("public source edits must be explicitly unsupported")
    payload = contract.get("payload")
    generated = contract.get("generated_identity_file")
    if not isinstance(payload, list) or not payload or len(payload) != len(set(payload)):
        raise ReleaseError("release payload must be a non-empty unique path list")
    if not isinstance(generated, str) or payload.count(generated) != 1:
        raise ReleaseError("generated identity file must occur exactly once in release payload")
    for rel in payload:
        path = Path(rel)
        if not isinstance(rel, str) or not rel or path.is_absolute() or ".." in path.parts:
            raise ReleaseError(f"unsafe release payload path: {rel!r}")
    return contract


def assert_canonical_checkout(source: Path) -> str:
    """Require a clean canonical checkout and return its immutable commit id."""
    source = source.resolve()
    top = Path(_run_git(source, "rev-parse", "--show-toplevel")).resolve()
    if top != source:
        raise ReleaseError(f"source must be the checkout root: {top}")
    origin = _run_git(source, "remote", "get-url", "origin")
    if _normalized_repository(origin) != _normalized_repository(CANONICAL_REPOSITORY):
        raise ReleaseError(
            "release source must be ume-harness-engineering; public->engineering reverse promotion is unsupported"
        )
    status_output = _run_git(source, "status", "--porcelain", "--untracked-files=all")
    if status_output:
        raise ReleaseError("canonical checkout is not clean")
    return _run_git(source, "rev-parse", "HEAD")


def _file_record(path: Path) -> dict[str, str]:
    if path.is_symlink():
        link_target = os.readlink(path).encode("utf-8")
        return {
            "sha256": hashlib.sha256(link_target).hexdigest(),
            "mode": "120000",
        }
    mode = path.stat().st_mode
    return {
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "mode": "100755" if mode & stat.S_IXUSR else "100644",
    }


def _root_digest(records: dict[str, dict[str, str]]) -> str:
    canonical = json.dumps(records, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def assert_payload_matches_head(source: Path, payload: list[str]) -> None:
    """Reject filesystem bytes or modes that are not the committed payload."""
    for rel in payload:
        path = source / rel
        if path.is_symlink() or not path.is_file():
            raise ReleaseError(f"release payload is not a regular file: {rel}")
        entry = _run_git_bytes(source, "ls-tree", "-z", "HEAD", "--", rel)
        if not entry:
            raise ReleaseError(f"release payload is not tracked in committed HEAD: {rel}")
        try:
            header, tracked_path = entry.rstrip(b"\0").split(b"\t", 1)
            mode, object_type, object_id = header.decode("ascii").split(" ", 2)
        except Exception as e:
            raise ReleaseError(f"invalid HEAD tree entry for release payload: {rel}") from e
        if tracked_path.decode("utf-8") != rel or object_type != "blob" or mode not in {"100644", "100755"}:
            raise ReleaseError(f"unsupported committed HEAD entry for release payload: {rel}")
        committed = _run_git_bytes(source, "cat-file", "blob", object_id)
        actual_mode = _file_record(path)["mode"]
        if path.read_bytes() != committed or actual_mode != mode:
            raise ReleaseError(f"release payload differs from committed HEAD bytes or mode: {rel}")


def assert_frozen_install_identity(source: Path) -> None:
    try:
        manifest = json.loads((source / "package_manifest.json").read_text(encoding="utf-8"))
        identity = manifest["release_identity"]
        closure = identity["closure"]
    except Exception as e:
        raise ReleaseError(f"invalid install identity contract: {e}") from e
    if identity.get("algorithm") != INSTALL_IDENTITY_ALGORITHM:
        raise ReleaseError("unsupported install identity algorithm")
    if not isinstance(closure, list) or not closure or len(closure) != len(set(closure)):
        raise ReleaseError("install identity closure must be a non-empty unique list")
    mapping: dict[str, str] = {}
    for rel in closure:
        path = Path(rel) if isinstance(rel, str) else Path("..")
        if not isinstance(rel, str) or not rel or path.is_absolute() or ".." in path.parts:
            raise ReleaseError(f"unsafe install identity path: {rel!r}")
        source_path = source / rel
        if source_path.is_symlink() or not source_path.is_file():
            raise ReleaseError(f"install identity member is not a regular file: {rel}")
        mapping[rel] = hashlib.sha256(source_path.read_bytes()).hexdigest()
    actual_root = hashlib.sha256(
        json.dumps(mapping, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if actual_root != EXPECTED_INSTALL_ROOT_DIGEST:
        raise ReleaseError(
            f"frozen install identity mismatch: expected={EXPECTED_INSTALL_ROOT_DIGEST} actual={actual_root}"
        )

    health_path = source / "scripts/health_check.py"
    actual_health_sha = hashlib.sha256(health_path.read_bytes()).hexdigest()
    if actual_health_sha != EXPECTED_HEALTH_CHECK_SHA256:
        raise ReleaseError(
            "health-check trust anchor mismatch: "
            f"expected={EXPECTED_HEALTH_CHECK_SHA256} actual={actual_health_sha}"
        )

    proc = subprocess.run(
        [
            sys.executable,
            str(source / "scripts/health_check.py"),
            "--installed-dir",
            str(source),
            "--identity-only",
            "--json",
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        detail = proc.stdout.strip() or proc.stderr.strip()
        raise ReleaseError(f"health-check verification disagrees with release gate: {detail}")


def stage_release(source: Path, output: Path) -> dict[str, Any]:
    """Copy only explicit closure bytes and add deterministic release identity."""
    source = source.resolve()
    output = output.resolve()
    source_commit = assert_canonical_checkout(source)
    contract = _load_contract(source)
    if output == source or source in output.parents:
        raise ReleaseError("release staging directory must be outside the canonical checkout")
    if output.exists():
        raise ReleaseError(f"release staging path already exists: {output}")

    generated = contract["generated_identity_file"]
    source_payload = [rel for rel in contract["payload"] if rel != generated]
    missing = [rel for rel in source_payload if not (source / rel).is_file()]
    if missing:
        raise ReleaseError(f"explicit release payload is missing source files: {missing}")
    assert_payload_matches_head(source, source_payload)
    assert_frozen_install_identity(source)

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".ume-release-stage-", dir=output.parent))
    try:
        records: dict[str, dict[str, str]] = {}
        for rel in source_payload:
            src = source / rel
            dst = temporary / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            records[rel] = _file_record(dst)

        identity = {
            "schema": "ume-harness-release-identity.v1",
            "canonical_repository": CANONICAL_REPOSITORY,
            "source_commit": source_commit,
            "source_payload_count": len(source_payload),
            "source_payload_root_sha256": _root_digest(records),
            "files": records,
        }
        identity_path = temporary / generated
        identity_path.write_text(
            json.dumps(identity, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.rename(output)
        return identity
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def assert_staging_is_disjoint(source: Path, output: Path, public: Path) -> None:
    source = source.resolve()
    output = output.resolve()
    public = public.resolve()
    if output == source or source in output.parents or output in source.parents:
        raise ReleaseError("release staging must not overlap the canonical checkout")
    if output == public or public in output.parents or output in public.parents:
        raise ReleaseError("release staging must not overlap the read-only public mirror")


def _tree_files(root: Path) -> dict[str, Path]:
    files: dict[str, Path] = {}
    for path in root.rglob("*"):
        rel = path.relative_to(root)
        if rel.parts and rel.parts[0] == ".git":
            continue
        if path.is_file():
            files[rel.as_posix()] = path
    return files


def compare_trees(expected: Path, actual: Path) -> list[str]:
    expected_files = _tree_files(expected)
    actual_files = _tree_files(actual)
    differences = [
        f"missing:{rel}" for rel in sorted(set(expected_files) - set(actual_files))
    ]
    differences.extend(
        f"unexpected:{rel}" for rel in sorted(set(actual_files) - set(expected_files))
    )
    for rel in sorted(set(expected_files) & set(actual_files)):
        if _file_record(expected_files[rel]) != _file_record(actual_files[rel]):
            differences.append(f"changed:{rel}")
    return differences


def compare_public_mirror(staged: Path, public: Path) -> list[str]:
    """Read-only comparison; never copies public bytes back to canonical source."""
    public = public.resolve()
    try:
        top = Path(_run_git(public, "rev-parse", "--show-toplevel")).resolve()
        origin = _run_git(public, "remote", "get-url", "origin")
    except ReleaseError as e:
        return [str(e)]
    if top != public:
        return [f"public mirror must be checkout root:{top}"]
    if _normalized_repository(origin) != _normalized_repository(PUBLIC_MIRROR_REPOSITORY):
        return ["public mirror origin is not UMEBOSHIISAN/ume-harness"]
    dirty = _run_git(public, "status", "--porcelain", "--untracked-files=all")
    if dirty:
        return ["public mirror checkout is dirty"]
    expected_files = _tree_files(staged)
    tracked_output = _run_git_bytes(public, "ls-files", "-s", "-z")
    tracked_entries: dict[str, str] = {}
    for entry in tracked_output.split(b"\0"):
        if not entry:
            continue
        try:
            metadata, path_bytes = entry.split(b"\t", 1)
            mode, _object_id, _stage = metadata.decode("ascii").split(" ", 2)
            rel = path_bytes.decode("utf-8")
        except Exception:
            return ["public mirror contains an unreadable tracked index entry"]
        tracked_entries[rel] = mode
    actual_files = set(tracked_entries)
    differences = [
        f"missing:{rel}" for rel in sorted(set(expected_files) - set(actual_files))
    ]
    differences.extend(
        f"unexpected:{rel}" for rel in sorted(set(actual_files) - set(expected_files))
    )
    for rel in sorted(set(expected_files) & set(actual_files)):
        actual_path = public / rel
        if tracked_entries[rel] not in {"100644", "100755", "120000"}:
            differences.append(f"changed:{rel}")
        elif not actual_path.is_file() and not actual_path.is_symlink():
            differences.append(f"changed:{rel}")
        elif _file_record(expected_files[rel]) != _file_record(actual_path):
            differences.append(f"changed:{rel}")
    return differences


def verify_staged_release(staged: Path) -> None:
    contract = _load_contract(staged)
    generated = contract["generated_identity_file"]
    expected_files = set(contract["payload"])
    actual_files = _tree_files(staged)
    if set(actual_files) != expected_files:
        missing = sorted(expected_files - set(actual_files))
        unexpected = sorted(set(actual_files) - expected_files)
        raise ReleaseError(f"staged closure drift: missing={missing} unexpected={unexpected}")
    try:
        identity = json.loads((staged / generated).read_text(encoding="utf-8"))
    except Exception as e:
        raise ReleaseError(f"invalid generated release identity: {e}") from e
    source_payload = [rel for rel in contract["payload"] if rel != generated]
    records = {rel: _file_record(staged / rel) for rel in source_payload}
    if identity.get("files") != records:
        raise ReleaseError("staged release bytes do not match generated file identity")
    if identity.get("source_payload_root_sha256") != _root_digest(records):
        raise ReleaseError("staged release root digest does not match generated identity")


def run_tests(release_root: Path) -> None:
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "tests",
            "ux/japanese-human-layer/tests",
        ],
        cwd=release_root,
        env=env,
    )
    if proc.returncode != 0:
        raise ReleaseError(f"release tests failed with exit {proc.returncode}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Build deterministic ume-harness release bytes and compare the public mirror"
    )
    parser.add_argument("--source", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--output", required=True)
    parser.add_argument("--mirror", required=True, help="Clean checkout of public ume-harness for read-only comparison")
    args = parser.parse_args(argv)

    source = Path(args.source).resolve()
    output = Path(args.output).resolve()
    public = Path(args.mirror).resolve()
    try:
        assert_canonical_checkout(source)
        assert_staging_is_disjoint(source, output, public)
        identity = stage_release(source, output)
        run_tests(output)
        verify_staged_release(output)
        differences = compare_public_mirror(output, public)
    except ReleaseError as e:
        print(f"RELEASE_GATE_FAIL: {e}", file=sys.stderr)
        return 1

    print(f"STAGED: {output}")
    print(f"SOURCE_COMMIT: {identity['source_commit']}")
    print(f"SOURCE_PAYLOAD_ROOT_SHA256: {identity['source_payload_root_sha256']}")
    if differences:
        print("PUBLIC_MIRROR_DRIFT:")
        for difference in differences:
            print(f"- {difference}")
        print("Publication requires human approval after this drift is reviewed.")
        return 2
    print("PUBLIC_MIRROR_MATCH: true")
    print("READY_FOR_HUMAN_PUBLICATION_APPROVAL: true")
    return 0


if __name__ == "__main__":
    sys.exit(main())
