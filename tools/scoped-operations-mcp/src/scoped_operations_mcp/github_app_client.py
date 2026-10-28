from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding


REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")
BRANCH_RE = re.compile(r"^(?:rory|codex)/[A-Za-z0-9._/-]{1,180}$")
IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9._:-]{8,200}$")
REPO_PATH_RE = re.compile(r"^(?!/)(?!.*(?:^|/)\.\.(?:/|$))[A-Za-z0-9._/@+ -]{1,400}$")
COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
SCOPED_SQL_REPOSITORY = "dariusmakesstuff/codex-slack-bridge"
SCOPED_SQL_SOURCE_PREFIX = "tools/scoped-operations-mcp/src/scoped_operations_mcp/"
SCOPED_SQL_TEST_PREFIX = "tools/scoped-operations-mcp/tests/"
SCOPED_SQL_ALLOWED_EXACT_PATHS = frozenset(
    {
        "config/agent-capabilities.yaml",
        "config/pipeline-registry.json",
        "config/tool-fast-paths.json",
        "deploy/gcp/agent-runtime/preflight.py",
        "docs/agent-tools/salesforce.md",
        "profiles/coding_agent.md",
        "tests/test_gcp_agent_runtime.py",
    }
)
SCOPED_SQL_FORBIDDEN_SOURCE_FILES = frozenset(
    {
        "cloud_ops_server.py",
        "gcp_client.py",
        "github_app_client.py",
        "operator_services_client.py",
        "operator_services_server.py",
    }
)


@dataclass(frozen=True)
class GitHubAppSettings:
    app_id_path: Path
    installation_id_path: Path
    private_key_path: Path
    allowed_repositories: frozenset[str]
    workspace_root: Path
    journal_path: Path

    @classmethod
    def from_environment(cls) -> "GitHubAppSettings":
        allowed = frozenset(
            item.strip().casefold()
            for item in os.getenv("GITHUB_ALLOWED_REPOSITORIES", "").split(",")
            if item.strip()
        )
        settings = cls(
            app_id_path=Path(os.getenv("GITHUB_APP_ID_PATH", "")).expanduser(),
            installation_id_path=Path(os.getenv("GITHUB_APP_INSTALLATION_ID_PATH", "")).expanduser(),
            private_key_path=Path(os.getenv("GITHUB_APP_PRIVATE_KEY_PATH", "")).expanduser(),
            allowed_repositories=allowed,
            workspace_root=Path(os.getenv("GITHUB_WORKSPACE_ROOT", "/srv/nova/workspaces/rory")).expanduser().resolve(),
            journal_path=Path(
                os.getenv("GITHUB_WRITE_JOURNAL_PATH", "/var/lib/nova/broker/cloud/github-writes.jsonl")
            ).expanduser(),
        )
        if not allowed or any(not REPOSITORY_RE.fullmatch(item) for item in allowed):
            raise RuntimeError("GITHUB_ALLOWED_REPOSITORIES is missing or invalid")
        for path in (settings.app_id_path, settings.installation_id_path, settings.private_key_path):
            if not path.is_file():
                raise RuntimeError("GitHub App credential files are unavailable")
        return settings


class GitHubAppClient:
    """GitHub App reads plus guarded branch/PR writes and scoped SQL PR promotion."""

    def __init__(self, settings: GitHubAppSettings, *, session: requests.Session | None = None) -> None:
        self.settings = settings
        self._session = session or requests.Session()
        self._token = ""
        self._token_expires_at = 0.0

    def capabilities(self) -> dict[str, Any]:
        return {
            "ok": True,
            "accessMode": "github_app_selected_repositories",
            "repositories": sorted(self.settings.allowed_repositories),
            "directProtectedBranchWrites": False,
            "mergeToolsExposed": True,
            "mergeScope": "tested_scoped_sql_broker_pull_requests_only",
            "workflowMutationToolsExposed": False,
            "branchPrefixes": ["rory/", "codex/"],
            "inlineFilePayloadsAccepted": True,
            "brokerWorkspaceTraversalRequired": False,
        }

    def list_repositories(self, *, max_rows: int = 100) -> dict[str, Any]:
        limit = max(1, min(int(max_rows), 100))
        payload = self._api("GET", "/installation/repositories", params={"per_page": limit})
        repositories = []
        for row in payload.get("repositories", [])[:limit]:
            full_name = str(row.get("full_name") or "")
            if full_name.casefold() not in self.settings.allowed_repositories:
                continue
            repositories.append(_repo_summary(row))
        return {"ok": True, "count": len(repositories), "repositories": repositories}

    def repository(self, repository: str) -> dict[str, Any]:
        repo = self._repository(repository)
        payload = self._api("GET", f"/repos/{repo}")
        return {"ok": True, "repository": _repo_summary(payload)}

    def list_pull_requests(self, repository: str, state: str = "open", *, max_rows: int = 50) -> dict[str, Any]:
        repo = self._repository(repository)
        clean_state = str(state or "open").strip().casefold()
        if clean_state not in {"open", "closed", "all"}:
            raise ValueError("state is invalid")
        limit = max(1, min(int(max_rows), 100))
        rows = self._api("GET", f"/repos/{repo}/pulls", params={"state": clean_state, "per_page": limit})
        return {
            "ok": True,
            "count": len(rows[:limit]),
            "pullRequests": [_pull_summary(row) for row in rows[:limit]],
        }

    def list_workflow_runs(self, repository: str, *, max_rows: int = 30) -> dict[str, Any]:
        repo = self._repository(repository)
        limit = max(1, min(int(max_rows), 100))
        payload = self._api("GET", f"/repos/{repo}/actions/runs", params={"per_page": limit})
        runs = []
        for row in payload.get("workflow_runs", [])[:limit]:
            runs.append(
                {
                    "id": int(row.get("id") or 0),
                    "name": str(row.get("name") or "")[:240],
                    "event": str(row.get("event") or "")[:80],
                    "status": str(row.get("status") or "")[:80],
                    "conclusion": str(row.get("conclusion") or "")[:80],
                    "headBranch": str(row.get("head_branch") or "")[:240],
                    "headSha": str(row.get("head_sha") or "")[:80],
                    "htmlUrl": str(row.get("html_url") or "")[:500],
                    "createdAt": str(row.get("created_at") or "")[:80],
                }
            )
        return {"ok": True, "count": len(runs), "workflowRuns": runs}

    def publish_branch(
        self,
        repository: str,
        branch: str,
        commit_message: str,
        files: list[dict[str, str]],
        idempotency_key: str,
        base_branch: str = "",
    ) -> dict[str, Any]:
        repo = self._repository(repository)
        clean_branch = self._branch(branch)
        key = self._idempotency(idempotency_key)
        message = str(commit_message or "").strip()
        if not message or len(message) > 500:
            raise ValueError("commit_message is required and must be at most 500 characters")
        specs = self._file_specs(files)
        metadata = self._api("GET", f"/repos/{repo}")
        base = str(base_branch or metadata.get("default_branch") or "main").strip()
        if not re.fullmatch(r"[A-Za-z0-9._/-]{1,200}", base):
            raise ValueError("base_branch is invalid")

        encoded_branch = urllib.parse.quote(clean_branch, safe="")
        existing = self._api_optional("GET", f"/repos/{repo}/git/ref/heads/{encoded_branch}")
        if existing:
            return {
                "ok": True,
                "status": "already_exists",
                "repository": repo,
                "branch": clean_branch,
                "commitSha": str((existing.get("object") or {}).get("sha") or ""),
                "idempotencyKey": key,
            }

        base_ref = self._api("GET", f"/repos/{repo}/git/ref/heads/{urllib.parse.quote(base, safe='')}")
        base_sha = str((base_ref.get("object") or {}).get("sha") or "")
        base_commit = self._api("GET", f"/repos/{repo}/git/commits/{base_sha}")
        base_tree = str((base_commit.get("tree") or {}).get("sha") or "")
        if not base_sha or not base_tree:
            raise RuntimeError("GitHub base branch could not be resolved")

        self._journal("pending", key, repo, "publish_branch", {"branch": clean_branch, "base": base})
        tree_entries = []
        for repo_path, data in specs:
            blob = self._api(
                "POST",
                f"/repos/{repo}/git/blobs",
                json={"content": base64.b64encode(data).decode("ascii"), "encoding": "base64"},
            )
            tree_entries.append({"path": repo_path, "mode": "100644", "type": "blob", "sha": blob["sha"]})
        tree = self._api(
            "POST",
            f"/repos/{repo}/git/trees",
            json={"base_tree": base_tree, "tree": tree_entries},
        )
        commit = self._api(
            "POST",
            f"/repos/{repo}/git/commits",
            json={"message": message, "tree": tree["sha"], "parents": [base_sha]},
        )
        created = self._api(
            "POST",
            f"/repos/{repo}/git/refs",
            json={"ref": f"refs/heads/{clean_branch}", "sha": commit["sha"]},
        )
        readback = self._api("GET", f"/repos/{repo}/git/ref/heads/{encoded_branch}")
        readback_sha = str((readback.get("object") or {}).get("sha") or "")
        if readback_sha != str(commit.get("sha") or ""):
            raise RuntimeError("GitHub branch readback did not match the created commit")
        result = {
            "ok": True,
            "status": "created",
            "repository": repo,
            "branch": clean_branch,
            "commitSha": readback_sha,
            "refUrl": str(created.get("url") or "")[:500],
            "idempotencyKey": key,
        }
        self._journal("verified", key, repo, "publish_branch", result)
        return result

    def open_pull_request(
        self,
        repository: str,
        branch: str,
        title: str,
        body: str,
        idempotency_key: str,
        base_branch: str = "",
    ) -> dict[str, Any]:
        repo = self._repository(repository)
        clean_branch = self._branch(branch)
        key = self._idempotency(idempotency_key)
        clean_title = str(title or "").strip()
        clean_body = str(body or "").strip()
        if not clean_title or len(clean_title) > 256 or len(clean_body) > 20_000:
            raise ValueError("pull request title/body is invalid")
        metadata = self._api("GET", f"/repos/{repo}")
        base = str(base_branch or metadata.get("default_branch") or "main").strip()
        owner = repo.split("/", 1)[0]
        existing = self._api(
            "GET",
            f"/repos/{repo}/pulls",
            params={"state": "open", "head": f"{owner}:{clean_branch}", "base": base, "per_page": 20},
        )
        if existing:
            return {"ok": True, "status": "already_exists", **_pull_summary(existing[0]), "idempotencyKey": key}
        self._journal("pending", key, repo, "open_pull_request", {"branch": clean_branch, "base": base})
        created = self._api(
            "POST",
            f"/repos/{repo}/pulls",
            json={"title": clean_title, "body": clean_body, "head": clean_branch, "base": base},
        )
        readback = self._api("GET", f"/repos/{repo}/pulls/{int(created['number'])}")
        result = {"ok": True, "status": "created", **_pull_summary(readback), "idempotencyKey": key}
        self._journal("verified", key, repo, "open_pull_request", result)
        return result

    def preview_scoped_sql_pull_request(
        self,
        repository: str,
        pull_number: int,
        expected_head_sha: str,
    ) -> dict[str, Any]:
        repo = self._repository(repository)
        if repo.casefold() != SCOPED_SQL_REPOSITORY:
            raise ValueError("scoped SQL promotion is limited to codex-slack-bridge")
        number = int(pull_number)
        if number < 1:
            raise ValueError("pull_number is invalid")
        expected = str(expected_head_sha or "").strip().casefold()
        if not COMMIT_SHA_RE.fullmatch(expected):
            raise ValueError("expected_head_sha must be one full lowercase commit SHA")

        pull = self._api("GET", f"/repos/{repo}/pulls/{number}")
        head = pull.get("head") if isinstance(pull.get("head"), dict) else {}
        base = pull.get("base") if isinstance(pull.get("base"), dict) else {}
        head_branch = str(head.get("ref") or "")
        head_sha = str(head.get("sha") or "").casefold()
        base_branch = str(base.get("ref") or "")
        if str(pull.get("state") or "") != "open" or bool(pull.get("draft")):
            raise ValueError("scoped SQL pull request must be open and ready for review")
        if not head_branch.startswith("codex/") or base_branch != "main":
            raise ValueError("scoped SQL pull request must merge codex/* into main")
        if head_sha != expected:
            raise ValueError("pull request head changed after review")
        if str(pull.get("mergeable_state") or "") not in {"clean", "unstable", "has_hooks"}:
            raise ValueError("pull request is not currently mergeable")
        changed_count = int(pull.get("changed_files") or 0)
        if changed_count < 1 or changed_count > 100:
            raise ValueError("scoped SQL pull request changed-file count is invalid")

        rows = self._api("GET", f"/repos/{repo}/pulls/{number}/files", params={"per_page": 100})
        paths = [str(row.get("filename") or "") for row in rows if isinstance(row, dict)]
        if len(paths) != changed_count:
            raise ValueError("scoped SQL pull request file list was incomplete")
        invalid_paths = [path for path in paths if not _scoped_sql_path_allowed(path)]
        if invalid_paths:
            raise ValueError("scoped SQL pull request contains files outside the guarded path set")
        if not any(path.startswith(SCOPED_SQL_SOURCE_PREFIX) for path in paths):
            raise ValueError("scoped SQL pull request must include broker source")
        if not any(path.startswith(SCOPED_SQL_TEST_PREFIX) for path in paths):
            raise ValueError("scoped SQL pull request must include focused broker tests")

        check_payload = self._api(
            "GET",
            f"/repos/{repo}/commits/{head_sha}/check-runs",
            params={"per_page": 100},
        )
        check_runs = check_payload.get("check_runs") if isinstance(check_payload, dict) else []
        incomplete = [
            str(row.get("name") or "")
            for row in check_runs
            if str(row.get("status") or "") != "completed"
        ]
        failed = [
            str(row.get("name") or "")
            for row in check_runs
            if str(row.get("status") or "") == "completed"
            and str(row.get("conclusion") or "") not in {"success", "neutral", "skipped"}
        ]
        if incomplete or failed:
            raise ValueError("scoped SQL pull request checks are incomplete or failing")

        plan = {
            "repository": repo,
            "pullNumber": number,
            "headBranch": head_branch,
            "headSha": head_sha,
            "baseBranch": base_branch,
            "changedFiles": paths,
            "completedCheckCount": len(check_runs),
            "mergeMethod": "squash",
            "directProtectedBranchWrite": False,
            "workflowChangesAllowed": False,
            "scope": "scoped_sql_broker_only",
        }
        plan_hash = hashlib.sha256(
            json.dumps(plan, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return {"ok": True, "previewHash": plan_hash, **plan}

    def merge_scoped_sql_pull_request(
        self,
        repository: str,
        pull_number: int,
        expected_head_sha: str,
        preview_hash: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        repo = self._repository(repository)
        number = int(pull_number)
        expected = str(expected_head_sha or "").strip().casefold()
        key = self._idempotency(idempotency_key)
        expected_preview = str(preview_hash or "").strip().casefold()
        if repo.casefold() != SCOPED_SQL_REPOSITORY:
            raise ValueError("scoped SQL promotion is limited to codex-slack-bridge")
        if number < 1:
            raise ValueError("pull_number is invalid")
        if not COMMIT_SHA_RE.fullmatch(expected):
            raise ValueError("expected_head_sha must be one full lowercase commit SHA")
        if not re.fullmatch(r"[0-9a-f]{64}", expected_preview):
            raise ValueError("preview_hash is invalid")
        replay = self._verified_journal_record(key, repo, "merge_scoped_sql_pull_request")
        if replay:
            if (
                replay.get("pullNumber") != number
                or replay.get("headSha") != expected
                or replay.get("previewHash") != expected_preview
            ):
                raise ValueError("idempotency_key was already used for another scoped SQL merge")
            return {**replay, "replay": True}

        preview = self.preview_scoped_sql_pull_request(
            repo,
            number,
            expected,
        )
        if preview["previewHash"] != expected_preview:
            raise ValueError("scoped SQL pull request changed after preview")

        self._journal(
            "pending",
            key,
            repo,
            "merge_scoped_sql_pull_request",
            {
                "pullNumber": number,
                "headSha": preview["headSha"],
                "previewHash": expected_preview,
            },
        )
        merged = self._api(
            "PUT",
            f"/repos/{repo}/pulls/{number}/merge",
            json={
                "sha": preview["headSha"],
                "merge_method": "squash",
                "commit_title": f"Promote scoped SQL broker capability (#{number})",
            },
        )
        if not bool(merged.get("merged")):
            raise RuntimeError("GitHub did not merge the scoped SQL pull request")
        readback = self._api("GET", f"/repos/{repo}/pulls/{number}")
        merge_sha = str(merged.get("sha") or "").casefold()
        if not readback.get("merged_at") or not COMMIT_SHA_RE.fullmatch(merge_sha):
            raise RuntimeError("scoped SQL pull request merge readback failed")
        result = {
            "ok": True,
            "status": "merged",
            "repository": repo,
            "pullNumber": number,
            "headSha": preview["headSha"],
            "mergeCommitSha": merge_sha,
            "previewHash": expected_preview,
            "idempotencyKey": key,
            "replay": False,
        }
        self._journal("verified", key, repo, "merge_scoped_sql_pull_request", result)
        return result

    def _file_specs(self, files: list[dict[str, str]]) -> list[tuple[str, bytes]]:
        if not isinstance(files, list) or not files or len(files) > 50:
            raise ValueError("files must contain between 1 and 50 entries")
        result: list[tuple[str, bytes]] = []
        total = 0
        for item in files:
            if not isinstance(item, dict):
                raise ValueError("each file entry must be an object")
            repo_path = str(item.get("path") or "").replace("\\", "/").strip()
            workspace_path = str(item.get("workspace_path") or "").strip()
            content_text = item.get("content_text")
            content_base64 = str(item.get("content_base64") or "").strip()
            if not REPO_PATH_RE.fullmatch(repo_path) or repo_path.casefold().startswith(".github/workflows/"):
                raise ValueError("repository file path is invalid or workflow-protected")
            supplied = sum(
                (
                    bool(workspace_path),
                    content_text is not None,
                    bool(content_base64),
                )
            )
            if supplied != 1:
                raise ValueError(
                    "each file must provide exactly one of workspace_path, content_text, or content_base64"
                )
            if workspace_path:
                local = (self.settings.workspace_root / workspace_path).resolve()
                try:
                    local.relative_to(self.settings.workspace_root)
                except ValueError as exc:
                    raise ValueError("workspace_path escaped the configured workspace") from exc
                if not local.is_file():
                    raise ValueError("workspace file does not exist")
                data = local.read_bytes()
            elif content_text is not None:
                data = str(content_text).encode("utf-8")
            else:
                try:
                    data = base64.b64decode(content_base64, validate=True)
                except (ValueError, TypeError) as exc:
                    raise ValueError("content_base64 is invalid") from exc
            size = len(data)
            if size > 2_000_000:
                raise ValueError("individual files must be at most 2 MB")
            total += size
            result.append((repo_path, data))
        if total > 10_000_000:
            raise ValueError("branch publish payload must be at most 10 MB")
        return result

    def _repository(self, repository: str) -> str:
        clean = str(repository or "").strip()
        if not REPOSITORY_RE.fullmatch(clean) or clean.casefold() not in self.settings.allowed_repositories:
            raise ValueError("repository is not in the installed allowlist")
        return clean

    @staticmethod
    def _branch(branch: str) -> str:
        clean = str(branch or "").strip()
        if not BRANCH_RE.fullmatch(clean) or ".." in clean or clean.endswith("/"):
            raise ValueError("branch must use the rory/ or codex/ prefix")
        return clean

    @staticmethod
    def _idempotency(value: str) -> str:
        clean = str(value or "").strip()
        if not IDEMPOTENCY_RE.fullmatch(clean):
            raise ValueError("idempotency_key is invalid")
        return clean

    def _api_optional(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self._request(method, path, **kwargs)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()

    def _api(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self._request(method, path, **kwargs)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, (dict, list)):
            raise RuntimeError("GitHub returned an unexpected response")
        return payload

    def _request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        headers = dict(kwargs.pop("headers", {}) or {})
        headers.update(
            {
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self._installation_token()}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "nova-rory-cloud-ops",
            }
        )
        return self._session.request(
            method,
            "https://api.github.com" + path,
            headers=headers,
            timeout=30,
            **kwargs,
        )

    def _installation_token(self) -> str:
        if self._token and time.time() < self._token_expires_at - 120:
            return self._token
        app_id = self.settings.app_id_path.read_text(encoding="utf-8").strip()
        installation_id = self.settings.installation_id_path.read_text(encoding="utf-8").strip()
        if not app_id.isdigit() or not installation_id.isdigit():
            raise RuntimeError("GitHub App identifiers are invalid")
        now = int(time.time())
        jwt = _app_jwt(app_id, self.settings.private_key_path.read_bytes(), now=now)
        response = self._session.post(
            f"https://api.github.com/app/installations/{installation_id}/access_tokens",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {jwt}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "nova-rory-cloud-ops",
            },
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        token = str(payload.get("token") or "")
        if not token:
            raise RuntimeError("GitHub App installation token was not returned")
        self._token = token
        self._token_expires_at = now + 50 * 60
        return token

    def _journal(self, status: str, key: str, repository: str, operation: str, evidence: dict[str, Any]) -> None:
        path = self.settings.journal_path
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        record = {
            "time": int(time.time()),
            "status": status,
            "idempotencyKey": key,
            "repository": repository,
            "operation": operation,
            "evidence": evidence,
        }
        descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def _verified_journal_record(
        self,
        key: str,
        repository: str,
        operation: str,
    ) -> dict[str, Any] | None:
        path = self.settings.journal_path
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
                and row.get("repository") == repository
                and row.get("operation") == operation
                and isinstance(row.get("evidence"), dict)
            ):
                return dict(row["evidence"])
        return None


def _app_jwt(app_id: str, private_key_pem: bytes, *, now: int) -> str:
    header = _b64url(json.dumps({"alg": "RS256", "typ": "JWT"}, separators=(",", ":")).encode())
    claims = _b64url(
        json.dumps({"iat": now - 30, "exp": now + 540, "iss": app_id}, separators=(",", ":")).encode()
    )
    signing_input = f"{header}.{claims}".encode("ascii")
    key = serialization.load_pem_private_key(private_key_pem, password=None)
    signature = key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    return f"{header}.{claims}.{_b64url(signature)}"


def _b64url(payload: bytes) -> str:
    return base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")


def _repo_summary(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "fullName": str(row.get("full_name") or "")[:240],
        "private": bool(row.get("private")),
        "defaultBranch": str(row.get("default_branch") or "")[:200],
        "archived": bool(row.get("archived")),
        "htmlUrl": str(row.get("html_url") or "")[:500],
        "updatedAt": str(row.get("updated_at") or "")[:80],
    }


def _pull_summary(row: dict[str, Any]) -> dict[str, Any]:
    head = row.get("head") if isinstance(row.get("head"), dict) else {}
    base = row.get("base") if isinstance(row.get("base"), dict) else {}
    return {
        "number": int(row.get("number") or 0),
        "title": str(row.get("title") or "")[:500],
        "state": str(row.get("state") or "")[:40],
        "draft": bool(row.get("draft")),
        "headBranch": str(head.get("ref") or "")[:240],
        "baseBranch": str(base.get("ref") or "")[:240],
        "htmlUrl": str(row.get("html_url") or "")[:500],
        "updatedAt": str(row.get("updated_at") or "")[:80],
    }


def _scoped_sql_path_allowed(path: str) -> bool:
    clean = str(path or "").replace("\\", "/").strip()
    if not REPO_PATH_RE.fullmatch(clean) or clean.casefold().startswith(".github/workflows/"):
        return False
    if clean in SCOPED_SQL_ALLOWED_EXACT_PATHS:
        return True
    if clean.startswith(SCOPED_SQL_TEST_PREFIX):
        return clean.endswith(".py")
    if clean.startswith("tools/scoped-operations-mcp/docs/"):
        return clean.endswith(".md")
    if clean.startswith(SCOPED_SQL_SOURCE_PREFIX):
        name = clean.rsplit("/", 1)[-1]
        return clean.endswith(".py") and name not in SCOPED_SQL_FORBIDDEN_SOURCE_FILES
    if clean.startswith("docs/agent-tools/"):
        return clean.endswith(".md")
    return False
