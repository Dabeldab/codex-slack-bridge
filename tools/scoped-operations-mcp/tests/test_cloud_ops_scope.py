from __future__ import annotations

from pathlib import Path
import base64
import io
import json
import tarfile
import time

import pytest

from scoped_operations_mcp.cloud_ops_server import build_mcp
from scoped_operations_mcp.gcp_client import GcpSettings, ScopedGcpClient, _startup_script_from_archive
from scoped_operations_mcp.github_app_client import GitHubAppClient, GitHubAppSettings


class FakeResponse:
    def __init__(self, payload, status_code: int = 200, content: bytes = b"") -> None:
        self._payload = payload
        self.status_code = status_code
        self.content = content

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError("request failed")

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses) -> None:
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return FakeResponse(self.responses.pop(0))


def _gcp(responses) -> tuple[ScopedGcpClient, FakeSession]:
    session = FakeSession(responses)
    return (
        ScopedGcpClient(
                GcpSettings(
                    project_id="gen-lang-client-0051653266",
                    target_service_account="nova-rory-cloud-ops@example.iam.gserviceaccount.com",
                    access_token_path=Path("unused-in-injected-session"),
                ),
            session=session,
        ),
        session,
    )


def _github(tmp_path: Path, responses=None) -> GitHubAppClient:
    for name, value in (("app", "1"), ("installation", "2"), ("key", "unused")):
        (tmp_path / name).write_text(value, encoding="utf-8")
    client = GitHubAppClient(
        GitHubAppSettings(
            app_id_path=tmp_path / "app",
            installation_id_path=tmp_path / "installation",
            private_key_path=tmp_path / "key",
            allowed_repositories=frozenset({"dariusmakesstuff/codex-slack-bridge"}),
            workspace_root=tmp_path.resolve(),
            journal_path=tmp_path / "journal.jsonl",
        ),
        session=FakeSession(responses or []),
    )
    client._token = "test-installation-token"
    client._token_expires_at = time.time() + 3_600
    return client


def test_gcp_future_service_discovery_is_read_only() -> None:
    client, session = _gcp(
        [
            {"name": "projects/63366976264", "projectId": "gen-lang-client-0051653266", "state": "ACTIVE"},
            {"services": [{"config": {"name": "run.googleapis.com", "title": "Cloud Run"}, "state": "ENABLED"}]},
        ]
    )
    assert client.capabilities()["futureServiceDiscovery"] is True
    assert client.capabilities()["genericMutationExposed"] is False
    assert client.capabilities()["mutationScope"] == "one immutable successful build to one pinned agent VM"
    result = client.list_enabled_services()
    assert result["services"][0]["name"] == "run.googleapis.com"
    assert session.calls[-1][0] == "GET"


def test_gcp_log_payloads_redact_secret_fields() -> None:
    client, _ = _gcp(
        [{"entries": [{"severity": "ERROR", "jsonPayload": {"message": "safe", "access_token": "never"}}]}]
    )
    result = client.read_recent_logs("cloud_run_revision")
    assert result["entries"][0]["payload"]["access_token"] == "[redacted]"
    assert "never" not in str(result)


def test_github_rejects_protected_branches_workflows_and_unknown_repositories(tmp_path: Path) -> None:
    client = _github(tmp_path)
    with pytest.raises(ValueError, match="branch"):
        client.publish_branch(
            "dariusmakesstuff/codex-slack-bridge",
            "main",
            "unsafe",
            [{"path": "README.md", "workspace_path": "README.md"}],
            "setup:test:123",
        )
    with pytest.raises(ValueError, match="allowlist"):
        client.repository("someone/else")
    workflow = tmp_path / "workflow.yml"
    workflow.write_text("name: unsafe", encoding="utf-8")
    with pytest.raises(ValueError, match="workflow-protected"):
        client.publish_branch(
            "dariusmakesstuff/codex-slack-bridge",
            "rory/test",
            "unsafe",
            [{"path": ".github/workflows/deploy.yml", "workspace_path": "workflow.yml"}],
            "setup:test:456",
        )


def test_github_accepts_only_explicit_bounded_inline_branch_files(tmp_path: Path) -> None:
    client = _github(tmp_path)

    specs = client._file_specs(
        [
            {
                "path": "tools/scoped-operations-mcp/tests/test_new_tool.py",
                "content_text": "def test_new_tool():\n    assert True\n",
            },
            {
                "path": "tools/scoped-operations-mcp/src/scoped_operations_mcp/new_tool.py",
                "content_base64": base64.b64encode(b"ENABLED = True\n").decode("ascii"),
            },
        ]
    )

    assert specs == [
        (
            "tools/scoped-operations-mcp/tests/test_new_tool.py",
            b"def test_new_tool():\n    assert True\n",
        ),
        (
            "tools/scoped-operations-mcp/src/scoped_operations_mcp/new_tool.py",
            b"ENABLED = True\n",
        ),
    ]
    with pytest.raises(ValueError, match="exactly one"):
        client._file_specs(
            [
                {
                    "path": "README.md",
                    "workspace_path": "README.md",
                    "content_text": "ambiguous",
                }
            ]
        )
    with pytest.raises(ValueError, match="content_base64"):
        client._file_specs(
            [{"path": "README.md", "content_base64": "not-base64!"}]
        )


def test_cloud_mcp_keeps_sql_promotion_out_of_non_taylor_lane(tmp_path: Path) -> None:
    gcp, _ = _gcp([])
    mcp = build_mcp(gcp, _github(tmp_path))
    names = set(mcp._tool_manager._tools)
    assert "gcp_search_resources" in names
    assert "github_publish_branch" in names
    assert "github_open_pull_request" in names
    assert all("merge" not in name for name in names)
    assert "gcp_agent_runtime_release_apply" not in names


def test_taylor_cloud_lane_can_promote_only_scoped_sql_and_pinned_runtime(tmp_path: Path) -> None:
    gcp, _ = _gcp([])
    mcp = build_mcp(gcp, _github(tmp_path), lane="coding_agent")
    names = set(mcp._tool_manager._tools)

    assert {
        "github_publish_branch",
        "github_open_pull_request",
        "github_scoped_sql_pull_request_preview",
        "github_scoped_sql_pull_request_merge",
        "gcp_agent_runtime_release_preview",
        "gcp_agent_runtime_release_apply",
        "gcp_agent_runtime_release_status",
    }.issubset(names)
    assert all(not name.startswith(("gcp_create", "gcp_update_iam", "gcp_delete")) for name in names)


def test_scoped_sql_pr_preview_requires_codex_main_source_and_tests(tmp_path: Path) -> None:
    head = "a" * 40
    client = _github(
        tmp_path,
        [
            {
                "number": 17,
                "state": "open",
                "draft": False,
                "mergeable_state": "clean",
                "changed_files": 2,
                "head": {"ref": "codex/sql-tool", "sha": head},
                "base": {"ref": "main"},
            },
            [
                {
                    "filename": "tools/scoped-operations-mcp/src/scoped_operations_mcp/nova_sql_new_tool.py"
                },
                {"filename": "tools/scoped-operations-mcp/tests/test_nova_sql_new_tool.py"},
            ],
            {"check_runs": []},
        ],
    )

    result = client.preview_scoped_sql_pull_request(
        "dariusmakesstuff/codex-slack-bridge",
        17,
        head,
    )

    assert result["headSha"] == head
    assert result["scope"] == "scoped_sql_broker_only"
    assert result["directProtectedBranchWrite"] is False
    assert len(result["previewHash"]) == 64


def test_scoped_sql_pr_preview_rejects_workflow_or_unrelated_app_changes(tmp_path: Path) -> None:
    head = "b" * 40
    client = _github(
        tmp_path,
        [
            {
                "number": 18,
                "state": "open",
                "draft": False,
                "mergeable_state": "clean",
                "changed_files": 2,
                "head": {"ref": "codex/sql-tool", "sha": head},
                "base": {"ref": "main"},
            },
            [
                {"filename": "tools/scoped-operations-mcp/src/scoped_operations_mcp/nova_sql_new_tool.py"},
                {"filename": ".github/workflows/deploy.yml"},
            ],
        ],
    )

    with pytest.raises(ValueError, match="outside the guarded path"):
        client.preview_scoped_sql_pull_request(
            "dariusmakesstuff/codex-slack-bridge",
            18,
            head,
        )


def test_scoped_sql_merge_replays_verified_result_without_reopening_closed_pr(tmp_path: Path) -> None:
    head = "d" * 40
    preview_hash = "e" * 64
    client = _github(tmp_path)
    result = {
        "ok": True,
        "status": "merged",
        "repository": "dariusmakesstuff/codex-slack-bridge",
        "pullNumber": 19,
        "headSha": head,
        "mergeCommitSha": "f" * 40,
        "previewHash": preview_hash,
        "idempotencyKey": "sql-merge-19",
        "replay": False,
    }
    client.settings.journal_path.write_text(
        json.dumps(
            {
                "status": "verified",
                "idempotencyKey": "sql-merge-19",
                "repository": "dariusmakesstuff/codex-slack-bridge",
                "operation": "merge_scoped_sql_pull_request",
                "evidence": result,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    replay = client.merge_scoped_sql_pull_request(
        "dariusmakesstuff/codex-slack-bridge",
        19,
        head,
        preview_hash,
        "sql-merge-19",
    )

    assert replay["replay"] is True
    assert replay["mergeCommitSha"] == "f" * 40
    assert client._session.calls == []


def test_agent_runtime_release_preview_requires_successful_build_and_fixed_instance(
    monkeypatch,
) -> None:
    commit = "c" * 40
    active = "d" * 40
    client, session = _gcp(
        [
            {
                "status": "RUNNING",
                "metadata": {
                    "fingerprint": "metadata-v1",
                    "items": [
                        {"key": "nova-source-bucket", "value": "nova-agent-runtime-source-63366976264"},
                        {"key": "nova-source-commit", "value": active},
                    ],
                },
            },
            {
                "generation": "12",
                "size": "4096",
                "metadata": {
                    "source-commit": commit,
                    "source-repository": "codex-slack-bridge",
                },
            },
            {
                "builds": [
                    {
                        "id": "build-1",
                        "status": "SUCCESS",
                        "finishTime": "2026-07-23T20:00:00Z",
                        "substitutions": {
                            "COMMIT_SHA": commit,
                            "BRANCH_NAME": "main",
                            "REPO_NAME": "codex-slack-bridge",
                        },
                    },
                    {
                        "id": "active-build",
                        "status": "SUCCESS",
                        "finishTime": "2026-07-23T19:00:00Z",
                        "substitutions": {
                            "COMMIT_SHA": active,
                            "BRANCH_NAME": "main",
                            "REPO_NAME": "codex-slack-bridge",
                        },
                    }
                ]
            },
        ]
    )
    monkeypatch.setattr(client, "_active_release_commit", lambda: active)

    result = client.agent_runtime_release_preview(commit)

    assert result["candidateCommit"] == commit
    assert result["instance"] == "nova-agent-runtime-staging"
    assert result["sourceObject"] == f"releases/{commit}.tar.gz"
    assert result["genericGcpMutationExposed"] is False
    assert result["candidateNewerThanActive"] is True
    assert [call[0] for call in session.calls] == ["GET", "GET", "GET"]


def test_agent_runtime_release_preview_blocks_when_active_runtime_is_unverified() -> None:
    commit = "c" * 40
    client, _session = _gcp(
        [
            {
                "status": "RUNNING",
                "metadata": {
                    "fingerprint": "metadata-v1",
                    "items": [
                        {
                            "key": "nova-source-bucket",
                            "value": "nova-agent-runtime-source-63366976264",
                        },
                        {"key": "nova-source-commit", "value": "d" * 40},
                    ],
                },
            },
            {
                "generation": "12",
                "size": "4096",
                "metadata": {
                    "source-commit": commit,
                    "source-repository": "codex-slack-bridge",
                },
            },
            {
                "builds": [
                    {
                        "id": "build-1",
                        "status": "SUCCESS",
                        "finishTime": "2026-07-23T20:00:00Z",
                        "substitutions": {
                            "COMMIT_SHA": commit,
                            "BRANCH_NAME": "main",
                            "REPO_NAME": "codex-slack-bridge",
                        },
                    }
                ]
            },
        ]
    )

    with pytest.raises(RuntimeError, match="could not be independently verified"):
        client.agent_runtime_release_preview(commit)


def test_gcp_capabilities_exposes_monotonic_release_boundary() -> None:
    client, _session = _gcp([])

    capabilities = client.capabilities()

    assert capabilities["releaseOrderPolicy"] == "newer_immutable_main_build_only"
    assert capabilities["activeReleaseVerificationRequired"] is True
    assert capabilities["rollbackExposed"] is False


def test_agent_runtime_release_preview_rejects_older_build_than_active_release(
    monkeypatch,
) -> None:
    candidate = "c" * 40
    active = "d" * 40
    client, _session = _gcp(
        [
            {
                "status": "RUNNING",
                "metadata": {
                    "fingerprint": "metadata-v2",
                    "items": [
                        {
                            "key": "nova-source-bucket",
                            "value": "nova-agent-runtime-source-63366976264",
                        },
                        {"key": "nova-source-commit", "value": active},
                    ],
                },
            },
            {
                "generation": "13",
                "size": "4096",
                "metadata": {
                    "source-commit": candidate,
                    "source-repository": "codex-slack-bridge",
                },
            },
            {
                "builds": [
                    {
                        "id": "candidate-old",
                        "status": "SUCCESS",
                        "finishTime": "2026-08-03T23:45:00Z",
                        "substitutions": {
                            "COMMIT_SHA": candidate,
                            "BRANCH_NAME": "main",
                            "REPO_NAME": "codex-slack-bridge",
                        },
                    },
                    {
                        "id": "active-new",
                        "status": "SUCCESS",
                        "finishTime": "2026-08-03T23:53:30Z",
                        "substitutions": {
                            "COMMIT_SHA": active,
                            "BRANCH_NAME": "main",
                            "REPO_NAME": "codex-slack-bridge",
                        },
                    },
                ]
            },
        ]
    )
    monkeypatch.setattr(client, "_active_release_commit", lambda: active)

    with pytest.raises(ValueError, match="older than the active production release"):
        client.agent_runtime_release_preview(candidate)


def test_agent_runtime_release_preview_allows_only_newer_build_order(
    monkeypatch,
) -> None:
    candidate = "e" * 40
    active = "d" * 40
    client, _session = _gcp(
        [
            {
                "status": "RUNNING",
                "metadata": {
                    "fingerprint": "metadata-v3",
                    "items": [
                        {
                            "key": "nova-source-bucket",
                            "value": "nova-agent-runtime-source-63366976264",
                        },
                        {"key": "nova-source-commit", "value": active},
                    ],
                },
            },
            {
                "generation": "14",
                "size": "4096",
                "metadata": {
                    "source-commit": candidate,
                    "source-repository": "codex-slack-bridge",
                },
            },
            {
                "builds": [
                    {
                        "id": "candidate-new",
                        "status": "SUCCESS",
                        "finishTime": "2026-08-03T23:59:00Z",
                        "substitutions": {
                            "COMMIT_SHA": candidate,
                            "BRANCH_NAME": "main",
                            "REPO_NAME": "codex-slack-bridge",
                        },
                    },
                    {
                        "id": "active-old",
                        "status": "SUCCESS",
                        "finishTime": "2026-08-03T23:53:30Z",
                        "substitutions": {
                            "COMMIT_SHA": active,
                            "BRANCH_NAME": "main",
                            "REPO_NAME": "codex-slack-bridge",
                        },
                    },
                ]
            },
        ]
    )
    monkeypatch.setattr(client, "_active_release_commit", lambda: active)

    preview = client.agent_runtime_release_preview(candidate)

    assert preview["candidateNewerThanActive"] is True
    assert preview["releaseOrderPolicy"] == "newer_immutable_main_build_only"
    assert preview["rollbackExposed"] is False
    assert preview["activeBuildId"] == "active-old"


@pytest.mark.parametrize("interpreter", ["sh", "bash"])
def test_release_archive_accepts_cloud_build_dot_prefixed_startup_script(
    interpreter: str,
) -> None:
    body = (
        f"#!/bin/{interpreter}\nsystemctl start nova-agent-preflight.service\n"
    ).encode("utf-8")
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode="w:gz") as archive:
        member = tarfile.TarInfo("./deploy/gcp/agent-runtime/bootstrap-private-runtime.sh")
        member.size = len(body)
        archive.addfile(member, io.BytesIO(body))

    assert _startup_script_from_archive(payload.getvalue()) == body.decode("utf-8")


def test_cloud_mcp_rejects_unknown_agent_lanes(tmp_path: Path) -> None:
    gcp, _ = _gcp([])
    with pytest.raises(RuntimeError, match="lane is invalid"):
        build_mcp(gcp, _github(tmp_path), lane="tickets_agent")
