from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any


SECRET_ID = re.compile(r"^[A-Za-z0-9_-]{1,255}$")
NUMERIC_VERSION = re.compile(r"^[1-9][0-9]*$")
ALLOWED_ROOT = Path("/run/nova-secrets")
ALLOWED_ROOT_POSIX = PurePosixPath("/run/nova-secrets")


class SecretManifestError(ValueError):
    """The non-secret deployment manifest is unsafe or malformed."""


def load_manifest(path: str | os.PathLike[str]) -> dict[str, Any]:
    raw = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(raw, dict):
        raise SecretManifestError("Secret manifest must be an object")
    project_id = str(raw.get("project_id") or "").strip()
    if not re.fullmatch(r"[a-z][a-z0-9-]{4,61}[a-z0-9]", project_id):
        raise SecretManifestError("Secret manifest project_id is invalid")
    entries = raw.get("secrets")
    if not isinstance(entries, list) or not entries:
        raise SecretManifestError("Secret manifest must contain at least one secret")

    seen_ids: set[str] = set()
    seen_paths: set[PurePosixPath] = set()
    normalized: list[dict[str, Any]] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise SecretManifestError(f"Secret manifest entry {index} must be an object")
        if set(entry) - {"id", "version", "path", "owner", "group", "mode", "required"}:
            raise SecretManifestError(f"Secret manifest entry {index} contains unsupported fields")
        secret_id = str(entry.get("id") or "").strip()
        version = str(entry.get("version") or "").strip()
        target = PurePosixPath(str(entry.get("path") or "").strip())
        if not SECRET_ID.fullmatch(secret_id):
            raise SecretManifestError(f"Secret manifest entry {index} has an invalid id")
        if secret_id in seen_ids:
            raise SecretManifestError(f"Secret id is duplicated: {secret_id}")
        if not NUMERIC_VERSION.fullmatch(version):
            raise SecretManifestError(f"Secret {secret_id} must use a numeric version pin")
        if not target.is_absolute() or not _is_under_posix(target, ALLOWED_ROOT_POSIX):
            raise SecretManifestError(f"Secret {secret_id} target must be under /run/nova-secrets")
        if target in seen_paths:
            raise SecretManifestError(f"Secret target is duplicated: {target}")
        mode_text = str(entry.get("mode") or "0400")
        if not re.fullmatch(r"0[0-7]{3}", mode_text):
            raise SecretManifestError(f"Secret {secret_id} has an invalid mode")
        normalized.append(
            {
                "id": secret_id,
                "version": version,
                "path": target,
                "owner": str(entry.get("owner") or "root"),
                "group": str(entry.get("group") or "root"),
                "mode": int(mode_text, 8),
                "required": bool(entry.get("required", True)),
            }
        )
        seen_ids.add(secret_id)
        seen_paths.add(target)
    return {"project_id": project_id, "secrets": normalized}


def materialize(manifest: dict[str, Any], *, client: Any | None = None) -> list[dict[str, str]]:
    if client is None:
        from google.cloud import secretmanager  # type: ignore[import-not-found]

        client = secretmanager.SecretManagerServiceClient()

    results: list[dict[str, str]] = []
    for entry in manifest["secrets"]:
        name = (
            f"projects/{manifest['project_id']}/secrets/{entry['id']}"
            f"/versions/{entry['version']}"
        )
        try:
            response = client.access_secret_version(request={"name": name})
            payload = bytes(response.payload.data)
            _verify_crc32c(payload, getattr(response.payload, "data_crc32c", None))
            if not payload:
                raise RuntimeError("secret payload is empty")
            _write_secret(
                Path(str(entry["path"])),
                payload,
                owner=entry["owner"],
                group=entry["group"],
                mode=entry["mode"],
            )
            results.append({"id": entry["id"], "version": entry["version"], "status": "materialized"})
        except Exception:
            if entry["required"]:
                raise RuntimeError(f"Required secret could not be materialized: {entry['id']}") from None
            results.append({"id": entry["id"], "version": entry["version"], "status": "unavailable_optional"})
    return results


def _write_secret(path: Path, payload: bytes, *, owner: str, group: str, mode: int) -> None:
    import grp
    import pwd

    target = path.resolve(strict=False)
    if not _is_under(target, ALLOWED_ROOT):
        raise SecretManifestError("Resolved secret target escaped the allowed root")
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if target.exists() and target.is_symlink():
        raise SecretManifestError("Secret target cannot be a symbolic link")

    uid = pwd.getpwnam(owner).pw_uid
    gid = grp.getgrnam(group).gr_gid
    temporary_name = ""
    try:
        descriptor, temporary_name = tempfile.mkstemp(prefix=".secret-", dir=target.parent)
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chown(temporary_name, uid, gid)
        os.chmod(temporary_name, mode)
        os.replace(temporary_name, target)
        temporary_name = ""
    finally:
        if temporary_name:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass


def _verify_crc32c(payload: bytes, expected: Any) -> None:
    if expected is None:
        raise RuntimeError("Secret Manager response did not include CRC32C metadata")
    try:
        import google_crc32c  # type: ignore[import-not-found]

        actual = int(google_crc32c.value(payload))
    except Exception as exc:
        raise RuntimeError("CRC32C verification is unavailable") from exc
    if actual != int(expected):
        raise RuntimeError("Secret Manager payload CRC32C verification failed")


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _is_under_posix(path: PurePosixPath, root: PurePosixPath) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Materialize pinned Secret Manager versions without printing values")
    parser.add_argument("manifest")
    args = parser.parse_args()
    manifest = load_manifest(args.manifest)
    print(json.dumps({"ok": True, "results": materialize(manifest)}, separators=(",", ":")))


if __name__ == "__main__":
    main()
