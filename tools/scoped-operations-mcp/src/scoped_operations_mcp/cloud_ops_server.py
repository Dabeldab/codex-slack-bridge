from __future__ import annotations

import os
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .gcp_client import GcpSettings, ScopedGcpClient
from .github_app_client import GitHubAppClient, GitHubAppSettings


READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=True)


def build_mcp(
    gcp: ScopedGcpClient,
    github: GitHubAppClient,
    *,
    lane: str = "direct_codex",
) -> FastMCP:
    clean_lane = str(lane or "").strip()
    if clean_lane not in {"direct_codex", "raw_codex", "coding_agent"}:
        raise RuntimeError("cloud operations lane is invalid")
    actor = "Taylor" if clean_lane == "coding_agent" else "Rory"
    authoring = (
        " Taylor may implement and test new typed SQL broker operations in her isolated workspace, then publish "
        "the selected files to a guarded codex/ branch and open a pull request. When the authenticated operator "
        "explicitly authorizes implementation and release, Taylor may preview and merge only a tested scoped-SQL "
        "pull request into main, wait for its immutable successful Cloud Build, then preview and promote only that "
        "artifact to the pinned private agent VM. Promotion is monotonic: the broker independently verifies the "
        "active release and rejects a candidate whose successful main-branch build is older. It exposes no rollback. "
        "The broker never permits a direct protected-branch write, workflow "
        "edit, generic repository administration, arbitrary GCP mutation, IAM change, or deployment of an unbuilt "
        "commit."
        if clean_lane == "coding_agent"
        else ""
    )
    mcp = FastMCP(
        f"{actor} Scoped GCloud and GitHub Operations",
        instructions=(
            "Use Google Cloud tools for read-only project discovery, service/resource inventory, bounded logs, "
            "Cloud Run, Cloud Build, and Secret Manager metadata. No Google Cloud mutation tool exists. Future "
            "services become visible through Service Usage and Cloud Asset Inventory without granting admin access. "
            "GitHub uses a repository-scoped GitHub App. It may publish a new rory/ or codex/ branch and open a PR "
            "only after an exact verified request, with an idempotency key and readback. It cannot push protected "
            "branches, edit workflow files, administer repositories, or read GitHub secrets. Branch files "
            "may be selected from the configured workspace or supplied explicitly as bounded content_text/content_base64 "
            "payloads; inline payloads let Taylor publish selected files without granting the broker access to browse "
            "her private workspace."
            + authoring
        ),
        json_response=True,
        stateless_http=True,
    )

    @mcp.tool(annotations=READ)
    def gcp_capabilities() -> dict[str, Any]:
        """Report Rory's fixed Google Cloud boundary and project."""
        return gcp.capabilities()

    @mcp.tool(annotations=READ)
    def gcp_project_status() -> dict[str, Any]:
        """Read the configured project's identity and lifecycle state."""
        return gcp.project_status()

    @mcp.tool(annotations=READ)
    def gcp_list_enabled_services(max_rows: int = 200) -> dict[str, Any]:
        """List enabled Google APIs so newly added services become discoverable."""
        return gcp.list_enabled_services(max_rows=max_rows)

    @mcp.tool(annotations=READ)
    def gcp_search_resources(query: str = "", max_rows: int = 100) -> dict[str, Any]:
        """Search bounded Cloud Asset Inventory metadata across current and future services."""
        return gcp.search_resources(query, max_rows=max_rows)

    @mcp.tool(annotations=READ)
    def gcp_list_cloud_run_services(region: str = "", max_rows: int = 100) -> dict[str, Any]:
        """List bounded Cloud Run service readiness metadata in one region."""
        return gcp.list_cloud_run_services(region, max_rows=max_rows)

    @mcp.tool(annotations=READ)
    def gcp_list_cloud_builds(region: str = "global", max_rows: int = 50) -> dict[str, Any]:
        """List bounded Cloud Build execution metadata and status."""
        return gcp.list_cloud_builds(region, max_rows=max_rows)

    @mcp.tool(annotations=READ)
    def gcp_list_secret_metadata(max_rows: int = 100) -> dict[str, Any]:
        """List Secret Manager names and timestamps; secret payload access is impossible."""
        return gcp.list_secret_metadata(max_rows=max_rows)

    @mcp.tool(annotations=READ)
    def gcp_read_recent_logs(
        resource_type: str,
        resource_name: str = "",
        severity: str = "WARNING",
        minutes: int = 60,
        max_rows: int = 50,
    ) -> dict[str, Any]:
        """Read redacted recent logs for one exact resource type and optional Cloud Run service."""
        return gcp.read_recent_logs(resource_type, resource_name, severity, minutes, max_rows)

    @mcp.tool(annotations=READ)
    def github_capabilities() -> dict[str, Any]:
        """Report GitHub App repositories and guarded write limits."""
        return github.capabilities()

    @mcp.tool(annotations=READ)
    def github_list_repositories(max_rows: int = 100) -> dict[str, Any]:
        """List repositories installed for Rory's GitHub App."""
        return github.list_repositories(max_rows=max_rows)

    @mcp.tool(annotations=READ)
    def github_repository(repository: str) -> dict[str, Any]:
        """Read one allowlisted repository's metadata."""
        return github.repository(repository)

    @mcp.tool(annotations=READ)
    def github_list_pull_requests(repository: str, state: str = "open", max_rows: int = 50) -> dict[str, Any]:
        """List bounded pull-request metadata for one allowlisted repository."""
        return github.list_pull_requests(repository, state, max_rows=max_rows)

    @mcp.tool(annotations=READ)
    def github_list_workflow_runs(repository: str, max_rows: int = 30) -> dict[str, Any]:
        """List bounded GitHub Actions run status without reading repository secrets."""
        return github.list_workflow_runs(repository, max_rows=max_rows)

    @mcp.tool(annotations=WRITE)
    def github_publish_branch(
        repository: str,
        branch: str,
        commit_message: str,
        files: list[dict[str, str]],
        idempotency_key: str,
        base_branch: str = "",
    ) -> dict[str, Any]:
        """Publish selected workspace or bounded inline files to a new rory/ or codex/ branch with readback."""
        return github.publish_branch(
            repository,
            branch,
            commit_message,
            files,
            idempotency_key,
            base_branch,
        )

    @mcp.tool(annotations=WRITE)
    def github_open_pull_request(
        repository: str,
        branch: str,
        title: str,
        body: str,
        idempotency_key: str,
        base_branch: str = "",
    ) -> dict[str, Any]:
        """Open one PR from an existing guarded branch; never merge it."""
        return github.open_pull_request(
            repository,
            branch,
            title,
            body,
            idempotency_key,
            base_branch,
        )

    if clean_lane == "coding_agent":

        @mcp.tool(annotations=READ)
        def github_scoped_sql_pull_request_preview(
            repository: str,
            pull_number: int,
            expected_head_sha: str,
        ) -> dict[str, Any]:
            """Validate one codex/* SQL-broker PR, its bounded paths, focused tests, checks, and immutable head."""
            return github.preview_scoped_sql_pull_request(
                repository,
                pull_number,
                expected_head_sha,
            )

        @mcp.tool(annotations=WRITE)
        def github_scoped_sql_pull_request_merge(
            repository: str,
            pull_number: int,
            expected_head_sha: str,
            preview_hash: str,
            idempotency_key: str,
        ) -> dict[str, Any]:
            """Squash-merge only the byte-identical scoped SQL PR preview; never push main directly."""
            return github.merge_scoped_sql_pull_request(
                repository,
                pull_number,
                expected_head_sha,
                preview_hash,
                idempotency_key,
            )

        @mcp.tool(annotations=READ)
        def gcp_agent_runtime_release_preview(commit_sha: str) -> dict[str, Any]:
            """Preview only a newer successful immutable Cloud Build for the pinned private agent VM."""
            return gcp.agent_runtime_release_preview(commit_sha)

        @mcp.tool(annotations=WRITE)
        def gcp_agent_runtime_release_apply(
            commit_sha: str,
            preview_hash: str,
            idempotency_key: str,
        ) -> dict[str, Any]:
            """Promote only the byte-identical built release to the pinned VM and request its preflight-gated reset."""
            return gcp.agent_runtime_release_apply(
                commit_sha,
                preview_hash,
                idempotency_key,
            )

        @mcp.tool(annotations=READ)
        def gcp_agent_runtime_release_status(commit_sha: str = "") -> dict[str, Any]:
            """Read metadata and active-release state for the pinned agent VM after promotion."""
            return gcp.agent_runtime_release_status(commit_sha)

    return mcp


def main() -> None:
    lane = os.getenv("SCOPED_AGENT_LANE", "").strip()
    if lane not in {"direct_codex", "raw_codex", "coding_agent"}:
        raise RuntimeError("cloud operations require the direct, raw, or coding lane")
    build_mcp(
        ScopedGcpClient(GcpSettings.from_environment()),
        GitHubAppClient(GitHubAppSettings.from_environment()),
        lane=lane,
    ).run(transport="stdio")


if __name__ == "__main__":
    main()
