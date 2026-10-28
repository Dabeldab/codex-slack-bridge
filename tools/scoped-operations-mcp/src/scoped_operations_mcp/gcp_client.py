from __future__ import annotations

import hashlib
import io
import json
import os
import re
import tarfile
import time
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import AuthorizedSession


PROJECT_ID_RE = re.compile(r"^[a-z][a-z0-9-]{4,61}[a-z0-9]$")
REGION_RE = re.compile(r"^[a-z]+-[a-z]+[0-9]$|^global$")
SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9._/-]{1,240}$")
COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9._:-]{8,200}$")


@dataclass(frozen=True)
class GcpSettings:
    project_id: str
    target_service_account: str
    access_token_path: Path
    default_region: str = "us-central1"
    runtime_zone: str = "us-central1-a"
    runtime_instance: str = "nova-agent-runtime-staging"
    release_journal_path: Path = Path("/var/lib/nova/broker/cloud/runtime-releases.jsonl")

    @classmethod
    def from_environment(cls) -> "GcpSettings":
        settings = cls(
            project_id=os.getenv("GCP_PROJECT_ID", "").strip(),
            target_service_account=os.getenv("GCP_RORY_SERVICE_ACCOUNT", "").strip(),
            access_token_path=Path(os.getenv("GCP_RORY_ACCESS_TOKEN_PATH", "")).expanduser(),
            default_region=os.getenv("GCP_DEFAULT_REGION", "us-central1").strip(),
            runtime_zone=os.getenv("GCP_RUNTIME_ZONE", "us-central1-a").strip(),
            runtime_instance=os.getenv("GCP_RUNTIME_INSTANCE", "nova-agent-runtime-staging").strip(),
            release_journal_path=Path(
                os.getenv(
                    "GCP_RELEASE_JOURNAL_PATH",
                    "/var/lib/nova/broker/cloud/runtime-releases.jsonl",
                )
            ).expanduser(),
        )
        if not PROJECT_ID_RE.fullmatch(settings.project_id):
            raise RuntimeError("GCP_PROJECT_ID is missing or invalid")
        if not settings.target_service_account.endswith(".iam.gserviceaccount.com"):
            raise RuntimeError("GCP_RORY_SERVICE_ACCOUNT is missing or invalid")
        if not settings.access_token_path.is_file():
            raise RuntimeError("Rory's short-lived Google Cloud token is unavailable")
        if not REGION_RE.fullmatch(settings.default_region):
            raise RuntimeError("GCP_DEFAULT_REGION is invalid")
        if not re.fullmatch(r"[a-z]+-[a-z]+[0-9]-[a-z]", settings.runtime_zone):
            raise RuntimeError("GCP_RUNTIME_ZONE is invalid")
        if not re.fullmatch(r"[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?", settings.runtime_instance):
            raise RuntimeError("GCP_RUNTIME_INSTANCE is invalid")
        return settings


class ScopedGcpClient:
    """Google Cloud discovery plus one immutable agent-runtime promotion path."""

    def __init__(self, settings: GcpSettings, *, session: Any | None = None) -> None:
        self.settings = settings
        self._session = session or self._authorized_session()
        self._project_number = ""

    def _authorized_session(self) -> AuthorizedSession:
        token = self.settings.access_token_path.read_text(encoding="utf-8").strip()
        if not token or len(token) > 16_384:
            raise RuntimeError("Rory's short-lived Google Cloud token is invalid")
        return AuthorizedSession(Credentials(token=token))

    def capabilities(self) -> dict[str, Any]:
        return {
            "ok": True,
            "projectId": self.settings.project_id,
            "serviceAccount": self.settings.target_service_account,
            "accessMode": "project_read_and_guarded_agent_runtime_promotion",
            "credentialMode": "root_minted_short_lived_token",
            "metadataAccess": False,
            "futureServiceDiscovery": True,
            "secretPayloadAccess": False,
            "mutationToolsExposed": True,
            "mutationScope": "one immutable successful build to one pinned agent VM",
            "releaseOrderPolicy": "newer_immutable_main_build_only",
            "activeReleaseVerificationRequired": True,
            "rollbackExposed": False,
            "genericMutationExposed": False,
        }

    def project_status(self) -> dict[str, Any]:
        payload = self._json(
            "GET",
            f"https://cloudresourcemanager.googleapis.com/v3/projects/{self.settings.project_id}",
        )
        name = str(payload.get("name") or "")
        if name.startswith("projects/"):
            self._project_number = name.split("/", 1)[1]
        return {
            "ok": bool(self._project_number or payload.get("projectId")),
            "projectId": str(payload.get("projectId") or self.settings.project_id),
            "projectNumber": self._project_number,
            "displayName": str(payload.get("displayName") or "")[:200],
            "state": str(payload.get("state") or "")[:40],
        }

    def list_enabled_services(self, *, max_rows: int = 200) -> dict[str, Any]:
        number = self._number()
        limit = max(1, min(int(max_rows), 500))
        payload = self._json(
            "GET",
            f"https://serviceusage.googleapis.com/v1/projects/{number}/services",
            params={"filter": "state:ENABLED", "pageSize": str(limit)},
        )
        services = []
        for row in payload.get("services", [])[:limit]:
            config = row.get("config") if isinstance(row.get("config"), dict) else {}
            services.append(
                {
                    "name": str(config.get("name") or "")[:240],
                    "title": str(config.get("title") or "")[:240],
                    "state": str(row.get("state") or "")[:40],
                }
            )
        return {"ok": True, "count": len(services), "services": services}

    def search_resources(self, query: str = "", *, max_rows: int = 100) -> dict[str, Any]:
        clean_query = str(query or "").strip()[:500]
        limit = max(1, min(int(max_rows), 250))
        payload = self._json(
            "GET",
            f"https://cloudasset.googleapis.com/v1/projects/{self.settings.project_id}:searchAllResources",
            params={"query": clean_query, "pageSize": str(limit)},
        )
        results = []
        for row in payload.get("results", [])[:limit]:
            results.append(
                {
                    "name": str(row.get("name") or "")[:500],
                    "assetType": str(row.get("assetType") or "")[:240],
                    "displayName": str(row.get("displayName") or "")[:240],
                    "location": str(row.get("location") or "")[:120],
                    "state": str(row.get("state") or "")[:80],
                    "createTime": str(row.get("createTime") or "")[:80],
                    "updateTime": str(row.get("updateTime") or "")[:80],
                }
            )
        return {"ok": True, "query": clean_query, "count": len(results), "resources": results}

    def list_cloud_run_services(self, region: str = "", *, max_rows: int = 100) -> dict[str, Any]:
        clean_region = self._region(region)
        limit = max(1, min(int(max_rows), 200))
        payload = self._json(
            "GET",
            f"https://run.googleapis.com/v2/projects/{self.settings.project_id}/locations/{clean_region}/services",
            params={"pageSize": str(limit)},
        )
        services = []
        for row in payload.get("services", [])[:limit]:
            services.append(
                {
                    "name": str(row.get("name") or "")[:500],
                    "uri": str(row.get("uri") or "")[:500],
                    "latestReadyRevision": str(row.get("latestReadyRevision") or "")[:500],
                    "updateTime": str(row.get("updateTime") or "")[:80],
                    "reconciling": bool(row.get("reconciling")),
                }
            )
        return {"ok": True, "region": clean_region, "count": len(services), "services": services}

    def list_cloud_builds(self, region: str = "global", *, max_rows: int = 50) -> dict[str, Any]:
        clean_region = self._region(region or "global")
        limit = max(1, min(int(max_rows), 100))
        payload = self._json(
            "GET",
            f"https://cloudbuild.googleapis.com/v1/projects/{self.settings.project_id}/locations/{clean_region}/builds",
            params={"pageSize": str(limit)},
        )
        builds = []
        for row in payload.get("builds", [])[:limit]:
            substitutions = row.get("substitutions") if isinstance(row.get("substitutions"), dict) else {}
            builds.append(
                {
                    "id": str(row.get("id") or "")[:200],
                    "status": str(row.get("status") or "")[:40],
                    "createTime": str(row.get("createTime") or "")[:80],
                    "finishTime": str(row.get("finishTime") or "")[:80],
                    "commitSha": str(substitutions.get("COMMIT_SHA") or "")[:80],
                    "logUrl": str(row.get("logUrl") or "")[:500],
                }
            )
        return {"ok": True, "region": clean_region, "count": len(builds), "builds": builds}

    def list_secret_metadata(self, *, max_rows: int = 100) -> dict[str, Any]:
        limit = max(1, min(int(max_rows), 200))
        payload = self._json(
            "GET",
            f"https://secretmanager.googleapis.com/v1/projects/{self.settings.project_id}/secrets",
            params={"pageSize": str(limit)},
        )
        rows = [
            {
                "name": str(item.get("name") or "")[:500],
                "createTime": str(item.get("createTime") or "")[:80],
                "expireTime": str(item.get("expireTime") or "")[:80],
            }
            for item in payload.get("secrets", [])[:limit]
        ]
        return {"ok": True, "count": len(rows), "secrets": rows, "payloadAccess": False}

    def read_recent_logs(
        self,
        resource_type: str,
        resource_name: str = "",
        severity: str = "WARNING",
        minutes: int = 60,
        max_rows: int = 50,
    ) -> dict[str, Any]:
        clean_type = str(resource_type or "").strip()
        clean_name = str(resource_name or "").strip()
        clean_severity = str(severity or "WARNING").strip().upper()
        if not SAFE_NAME_RE.fullmatch(clean_type):
            raise ValueError("resource_type is invalid")
        if clean_name and not SAFE_NAME_RE.fullmatch(clean_name):
            raise ValueError("resource_name is invalid")
        if clean_severity not in {"DEFAULT", "DEBUG", "INFO", "NOTICE", "WARNING", "ERROR", "CRITICAL", "ALERT", "EMERGENCY"}:
            raise ValueError("severity is invalid")
        window = max(1, min(int(minutes), 24 * 60))
        limit = max(1, min(int(max_rows), 100))
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=window)
        parts = [
            f'resource.type="{clean_type}"',
            f"severity>={clean_severity}",
            f'timestamp>="{cutoff.isoformat().replace("+00:00", "Z")}"',
        ]
        if clean_name:
            parts.append(f'resource.labels.service_name="{clean_name}"')
        payload = self._json(
            "POST",
            "https://logging.googleapis.com/v2/entries:list",
            json={
                "resourceNames": [f"projects/{self.settings.project_id}"],
                "filter": " AND ".join(parts),
                "orderBy": "timestamp desc",
                "pageSize": limit,
            },
        )
        entries = [_sanitize_log_entry(row) for row in payload.get("entries", [])[:limit]]
        return {"ok": True, "count": len(entries), "entries": entries}

    def agent_runtime_release_preview(self, commit_sha: str) -> dict[str, Any]:
        commit = self._commit(commit_sha)
        instance = self._runtime_instance()
        metadata = instance.get("metadata") if isinstance(instance.get("metadata"), dict) else {}
        items = _metadata_items(metadata)
        source_bucket = str(items.get("nova-source-bucket") or "").strip()
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{1,220}[a-z0-9]", source_bucket):
            raise RuntimeError("agent runtime source bucket metadata is invalid")
        object_name = f"releases/{commit}.tar.gz"
        encoded_object = urllib.parse.quote(object_name, safe="")
        artifact = self._json(
            "GET",
            f"https://storage.googleapis.com/storage/v1/b/{source_bucket}/o/{encoded_object}",
        )
        artifact_metadata = (
            artifact.get("metadata") if isinstance(artifact.get("metadata"), dict) else {}
        )
        if (
            str(artifact_metadata.get("source-commit") or "").casefold() != commit
            or str(artifact_metadata.get("source-repository") or "") != "codex-slack-bridge"
        ):
            raise ValueError("agent runtime artifact provenance does not match the candidate commit")
        builds_payload = self._json(
            "GET",
            f"https://cloudbuild.googleapis.com/v1/projects/{self.settings.project_id}/locations/global/builds",
            params={"pageSize": "1000"},
        )
        builds = [
            row
            for row in builds_payload.get("builds", [])
            if isinstance(row, dict)
        ]
        successful_build = _newest_successful_main_build(builds, commit)
        if successful_build is None:
            raise ValueError("the candidate commit has no successful immutable Cloud Build")

        metadata_commit = str(items.get("nova-source-commit") or "").strip().casefold()
        active_commit = self._active_release_commit()
        if metadata_commit and not active_commit:
            raise RuntimeError(
                "the active runtime release could not be independently verified; "
                "a new promotion is blocked"
            )
        if (
            active_commit
            and metadata_commit
            and active_commit != metadata_commit
        ):
            raise RuntimeError(
                "the active release and runtime metadata do not match; a new promotion is blocked"
            )
        active_build = None
        if active_commit:
            active_build = _newest_successful_main_build(builds, active_commit)
            if active_build is None:
                raise ValueError(
                    "the active release has no verifiable immutable main-branch build; "
                    "a new promotion is blocked"
                )

        candidate_finish_time = _cloud_build_finish_time(successful_build)
        active_finish_time = (
            _cloud_build_finish_time(active_build)
            if active_build is not None
            else None
        )
        candidate_newer_than_active = bool(
            not active_commit
            or active_commit == commit
            or (
                active_finish_time is not None
                and candidate_finish_time > active_finish_time
            )
        )
        if not candidate_newer_than_active:
            raise ValueError(
                "the candidate build is older than the active production release; "
                "runtime rollback is not exposed through this promotion tool"
            )

        plan = {
            "projectId": self.settings.project_id,
            "zone": self.settings.runtime_zone,
            "instance": self.settings.runtime_instance,
            "candidateCommit": commit,
            "currentMetadataCommit": metadata_commit[:80],
            "activeReleaseCommit": active_commit,
            "sourceBucket": source_bucket,
            "sourceObject": object_name,
            "artifactGeneration": str(artifact.get("generation") or "")[:80],
            "artifactSize": int(artifact.get("size") or 0),
            "buildId": str(successful_build.get("id") or "")[:200],
            "buildFinishTime": str(successful_build.get("finishTime") or "")[:80],
            "activeBuildId": str((active_build or {}).get("id") or "")[:200],
            "activeBuildFinishTime": str(
                (active_build or {}).get("finishTime") or ""
            )[:80],
            "candidateNewerThanActive": candidate_newer_than_active,
            "releaseOrderPolicy": "newer_immutable_main_build_only",
            "rollbackExposed": False,
            "activation": "fixed_instance_metadata_update_then_reset",
            "rollbackCommit": str(items.get("nova-source-commit") or "")[:80],
            "genericGcpMutationExposed": False,
        }
        preview_hash = hashlib.sha256(
            json.dumps(plan, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return {
            "ok": True,
            "previewHash": preview_hash,
            "metadataFingerprint": str(metadata.get("fingerprint") or ""),
            **plan,
        }

    def agent_runtime_release_apply(
        self,
        commit_sha: str,
        preview_hash: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        commit = self._commit(commit_sha)
        key = self._idempotency(idempotency_key)
        expected_preview = str(preview_hash or "").strip().casefold()
        if not re.fullmatch(r"[0-9a-f]{64}", expected_preview):
            raise ValueError("preview_hash is invalid")
        replay = self._release_replay(key)
        if replay:
            if replay.get("candidateCommit") != commit or replay.get("previewHash") != expected_preview:
                raise ValueError("idempotency_key was already used for another runtime release")
            return {**replay, "replay": True}

        preview = self.agent_runtime_release_preview(commit)
        if preview["previewHash"] != expected_preview:
            raise ValueError("agent runtime release changed after preview")
        if preview["activeReleaseCommit"] == commit and preview["currentMetadataCommit"] == commit:
            result = {
                "ok": True,
                "status": "already_active",
                "candidateCommit": commit,
                "previewHash": expected_preview,
                "idempotencyKey": key,
                "replay": False,
            }
            self._release_journal("verified", key, result)
            return result

        self._release_journal(
            "pending",
            key,
            {
                "candidateCommit": commit,
                "previewHash": expected_preview,
                "rollbackCommit": preview["rollbackCommit"],
            },
        )
        archive = self._download_release_archive(preview["sourceBucket"], preview["sourceObject"])
        startup_script = _startup_script_from_archive(archive)
        instance = self._runtime_instance()
        metadata = instance.get("metadata") if isinstance(instance.get("metadata"), dict) else {}
        if str(metadata.get("fingerprint") or "") != preview["metadataFingerprint"]:
            raise ValueError("agent runtime metadata changed after preview")
        items = _metadata_items(metadata)
        items["nova-source-object"] = preview["sourceObject"]
        items["nova-source-commit"] = commit
        items["startup-script"] = startup_script
        updated = self._json(
            "POST",
            (
                "https://compute.googleapis.com/compute/v1/projects/"
                f"{self.settings.project_id}/zones/{self.settings.runtime_zone}/instances/"
                f"{self.settings.runtime_instance}/setMetadata"
            ),
            json={
                "fingerprint": preview["metadataFingerprint"],
                "items": [{"key": name, "value": value} for name, value in sorted(items.items())],
            },
        )
        self._wait_zone_operation(str(updated.get("name") or ""))
        activation = self._json(
            "POST",
            (
                "https://compute.googleapis.com/compute/v1/projects/"
                f"{self.settings.project_id}/zones/{self.settings.runtime_zone}/instances/"
                f"{self.settings.runtime_instance}/reset"
            ),
        )
        result = {
            "ok": True,
            "status": "activation_requested",
            "candidateCommit": commit,
            "rollbackCommit": preview["rollbackCommit"],
            "previewHash": expected_preview,
            "metadataUpdated": True,
            "resetOperation": str(activation.get("name") or "")[:240],
            "postBootVerificationRequired": True,
            "idempotencyKey": key,
            "replay": False,
        }
        self._release_journal("verified", key, result)
        return result

    def agent_runtime_release_status(self, commit_sha: str = "") -> dict[str, Any]:
        candidate = self._commit(commit_sha) if str(commit_sha or "").strip() else ""
        instance = self._runtime_instance()
        metadata = instance.get("metadata") if isinstance(instance.get("metadata"), dict) else {}
        items = _metadata_items(metadata)
        metadata_commit = str(items.get("nova-source-commit") or "")[:80]
        active_commit = self._active_release_commit()
        return {
            "ok": bool(active_commit),
            "instanceStatus": str(instance.get("status") or "")[:40],
            "metadataCommit": metadata_commit,
            "activeReleaseCommit": active_commit,
            "candidateCommit": candidate,
            "candidateActive": bool(candidate and metadata_commit == candidate and active_commit == candidate),
            "metadataAndActiveMatch": bool(metadata_commit and metadata_commit == active_commit),
        }

    def _number(self) -> str:
        if not self._project_number:
            self.project_status()
        if not self._project_number.isdigit():
            raise RuntimeError("Google Cloud project number could not be resolved")
        return self._project_number

    def _region(self, value: str) -> str:
        clean = str(value or self.settings.default_region).strip()
        if not REGION_RE.fullmatch(clean):
            raise ValueError("region is invalid")
        return clean

    def _json(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        response = self._session.request(method, url, timeout=30, **kwargs)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("Google Cloud returned an unexpected response")
        return payload

    def _runtime_instance(self) -> dict[str, Any]:
        return self._json(
            "GET",
            (
                "https://compute.googleapis.com/compute/v1/projects/"
                f"{self.settings.project_id}/zones/{self.settings.runtime_zone}/instances/"
                f"{self.settings.runtime_instance}"
            ),
        )

    def _download_release_archive(self, bucket: str, object_name: str) -> bytes:
        encoded_object = urllib.parse.quote(object_name, safe="")
        response = self._session.request(
            "GET",
            f"https://storage.googleapis.com/storage/v1/b/{bucket}/o/{encoded_object}",
            params={"alt": "media"},
            timeout=60,
        )
        response.raise_for_status()
        payload = bytes(response.content)
        if not payload or len(payload) > 100_000_000:
            raise RuntimeError("agent runtime release archive size is invalid")
        return payload

    def _wait_zone_operation(self, operation_name: str) -> None:
        if not SAFE_NAME_RE.fullmatch(operation_name):
            raise RuntimeError("Google Cloud did not return a valid zone operation")
        url = (
            "https://compute.googleapis.com/compute/v1/projects/"
            f"{self.settings.project_id}/zones/{self.settings.runtime_zone}/operations/{operation_name}"
        )
        for _ in range(30):
            payload = self._json("GET", url)
            if str(payload.get("status") or "") == "DONE":
                if payload.get("error"):
                    raise RuntimeError("Google Cloud metadata update failed")
                return
            time.sleep(1)
        raise TimeoutError("Google Cloud metadata update did not finish")

    def _active_release_commit(self) -> str:
        try:
            resolved = Path("/opt/nova/current").resolve()
        except OSError:
            return ""
        name = resolved.name.casefold()
        return name if COMMIT_SHA_RE.fullmatch(name) else ""

    @staticmethod
    def _commit(value: str) -> str:
        clean = str(value or "").strip().casefold()
        if not COMMIT_SHA_RE.fullmatch(clean):
            raise ValueError("commit_sha must be one full lowercase commit SHA")
        return clean

    @staticmethod
    def _idempotency(value: str) -> str:
        clean = str(value or "").strip()
        if not IDEMPOTENCY_RE.fullmatch(clean):
            raise ValueError("idempotency_key is invalid")
        return clean

    def _release_journal(self, status: str, key: str, evidence: dict[str, Any]) -> None:
        path = self.settings.release_journal_path
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        record = {
            "time": int(time.time()),
            "status": status,
            "idempotencyKey": key,
            "operation": "agent_runtime_release_apply",
            "evidence": evidence,
        }
        descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def _release_replay(self, key: str) -> dict[str, Any] | None:
        path = self.settings.release_journal_path
        if not path.is_file():
            return None
        for line in reversed(path.read_text(encoding="utf-8").splitlines()):
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if (
                row.get("status") == "verified"
                and row.get("idempotencyKey") == key
                and row.get("operation") == "agent_runtime_release_apply"
                and isinstance(row.get("evidence"), dict)
            ):
                return dict(row["evidence"])
        return None


def _cloud_build_finish_time(build: dict[str, Any]) -> datetime:
    value = str(build.get("finishTime") or "").strip()
    if not value:
        raise ValueError("immutable Cloud Build omitted its finish time")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("immutable Cloud Build returned an invalid finish time") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _newest_successful_main_build(
    builds: list[dict[str, Any]],
    commit: str,
) -> dict[str, Any] | None:
    matches = []
    for row in builds:
        substitutions = (
            row.get("substitutions")
            if isinstance(row.get("substitutions"), dict)
            else {}
        )
        if (
            str(substitutions.get("COMMIT_SHA") or "").casefold() == commit
            and str(substitutions.get("BRANCH_NAME") or "") == "main"
            and str(substitutions.get("REPO_NAME") or "") == "codex-slack-bridge"
            and str(row.get("status") or "") == "SUCCESS"
        ):
            matches.append(row)
    return max(matches, key=_cloud_build_finish_time) if matches else None


def _metadata_items(metadata: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for row in metadata.get("items", []):
        if not isinstance(row, dict):
            continue
        key = str(row.get("key") or "")
        value = str(row.get("value") or "")
        if key:
            result[key] = value
    return result


def _startup_script_from_archive(payload: bytes) -> str:
    target = "deploy/gcp/agent-runtime/bootstrap-private-runtime.sh"
    try:
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
            member = next(
                (
                    entry
                    for entry in archive.getmembers()
                    if entry.name.removeprefix("./") == target
                ),
                None,
            )
            if member is None:
                raise RuntimeError("release startup script entry is missing")
            if not member.isfile() or member.size > 1_000_000:
                raise RuntimeError("release startup script entry is invalid")
            handle = archive.extractfile(member)
            if handle is None:
                raise RuntimeError("release startup script could not be read")
            script = handle.read().decode("utf-8")
    except (KeyError, tarfile.TarError, UnicodeDecodeError) as exc:
        raise RuntimeError("release archive did not contain a valid startup script") from exc
    if not script.startswith(("#!/bin/sh\n", "#!/bin/bash\n")) or (
        "nova-agent-preflight.service" not in script
    ):
        raise RuntimeError("release startup script failed the fixed safety signature")
    return script


def _sanitize_log_entry(row: Any) -> dict[str, Any]:
    if not isinstance(row, dict):
        return {}
    payload: Any = row.get("jsonPayload")
    if payload is None:
        payload = row.get("textPayload")
    if payload is None:
        payload = row.get("protoPayload")
    return {
        "timestamp": str(row.get("timestamp") or "")[:80],
        "severity": str(row.get("severity") or "")[:40],
        "logName": str(row.get("logName") or "")[:500],
        "payload": _sanitize_value(payload, depth=0),
    }


def _sanitize_value(value: Any, *, depth: int) -> Any:
    if depth > 4:
        return "[truncated]"
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in list(value.items())[:80]:
            clean_key = str(key)[:120]
            if any(marker in clean_key.casefold() for marker in ("token", "secret", "password", "authorization", "credential", "cookie")):
                result[clean_key] = "[redacted]"
            else:
                result[clean_key] = _sanitize_value(item, depth=depth + 1)
        return result
    if isinstance(value, list):
        return [_sanitize_value(item, depth=depth + 1) for item in value[:50]]
    if isinstance(value, str):
        return value[:4000]
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    return str(value)[:500]
