from __future__ import annotations

# AgentChat/direct_codex 2026-07-15T03:27:38-04:00: fail closed when runtime lane config drifts from the capability contract.

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from .config import require_active_agent


def resolve_capability_contract_path(value: str) -> Path:
    expanded = Path(os.path.expandvars(os.path.expanduser(str(value or "").strip())))
    if expanded.is_absolute():
        return expanded

    # Installed wheels live below site-packages, so deriving the repository root
    # from ``__file__`` points at the virtualenv instead of the deployed release.
    # Resolve relative policy resources from the active bridge config first. This
    # keeps source checkouts, immutable GCP releases, and packaged installs on the
    # same fail-closed contract without broadening any lane capability.
    configured = os.getenv("BRIDGE_CONFIG", "").strip()
    if configured:
        config_path = Path(os.path.expandvars(os.path.expanduser(configured)))
        if not config_path.is_absolute():
            config_path = Path.cwd() / config_path
        config_path = config_path.resolve()
        bridge_root = (
            config_path.parent.parent
            if config_path.parent.name.lower() == "config"
            else config_path.parent
        )
        return (bridge_root / expanded).resolve()

    working_tree_path = (Path.cwd() / expanded).resolve()
    if working_tree_path.is_file():
        return working_tree_path
    return (Path(__file__).resolve().parents[2] / expanded).resolve()


@lru_cache(maxsize=8)
def load_capability_contract(path_value: str) -> dict[str, Any]:
    path = resolve_capability_contract_path(path_value)
    if not path.is_file():
        raise RuntimeError(f"Agent capability contract is missing: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise RuntimeError(f"Agent capability contract cannot be read: {path}") from exc
    if raw.get("schema_version") != 2 or not isinstance(raw.get("lanes"), dict):
        raise RuntimeError(f"Agent capability contract has an unsupported schema: {path}")
    global_policy = raw.get("global") or {}
    if global_policy.get("agent_may_change_access") != "operator_only":
        raise RuntimeError("Agent capability contract must restrict access changes to the operator-only lane")
    if global_policy.get("delegation_rule") != "reduce_only":
        raise RuntimeError("Agent capability contract must enforce reduce-only delegation")
    for name, lane in raw["lanes"].items():
        if not isinstance(lane, dict) or not isinstance(lane.get("operations"), list):
            raise RuntimeError(f"Agent capability contract operations are invalid for {name}")
        allowed_providers = lane.get("allowed_providers")
        if allowed_providers is not None:
            if not isinstance(allowed_providers, list) or not allowed_providers:
                raise RuntimeError(f"Agent capability contract providers are invalid for {name}")
            if str(lane.get("provider") or "").strip() not in {
                str(item).strip() for item in allowed_providers
            }:
                raise RuntimeError(f"Agent capability contract primary provider is not allowed for {name}")
        limitations = set(lane.get("limitations") or [])
        operations = set(lane.get("operations") or [])
        if name == "direct_codex":
            if "agent.capability.change_authorized" not in operations:
                raise RuntimeError("Operator lane must expose explicit capability administration")
            if not {
                "operator_authorized_capability_changes_only",
                "no_delegated_capability_changes",
            }.issubset(limitations):
                raise RuntimeError("Operator capability administration guardrails are incomplete")
        elif name == "coding_agent":
            required_operations = {
                "nova_sql.tool_promotion.preview_guarded",
                "nova_sql.tool_promotion.merge_guarded",
                "nova_sql.runtime_release.preview_pinned",
                "nova_sql.runtime_release.apply_successful_build",
            }
            required_limitations = {
                "no_arbitrary_capability_changes",
                "no_credential_or_lane_scope_changes",
                "operator_request_required_for_release",
                "guarded_sql_tool_promotion_only",
            }
            if not required_operations.issubset(operations) or not required_limitations.issubset(
                limitations
            ):
                raise RuntimeError("Taylor guarded SQL tool-promotion guardrails are incomplete")
        elif "no_capability_changes" not in limitations:
            raise RuntimeError(f"Agent capability contract must deny access changes for {name}")
    return raw


def validate_runtime_agent_policy(agent_name: str, agent: dict[str, Any]) -> dict[str, Any] | None:
    require_active_agent(agent_name, agent)
    path_value = str(agent.get("agent_capability_contract_path") or "").strip()
    if not path_value:
        return None
    contract = load_capability_contract(path_value)
    lane = contract["lanes"].get(agent_name)
    if not isinstance(lane, dict):
        raise PermissionError(f"Agent lane is absent from the capability contract: {agent_name}")

    expected_provider = str(lane.get("provider") or "").strip()
    allowed_providers = {
        str(item).strip()
        for item in (lane.get("allowed_providers") or [expected_provider])
        if str(item).strip()
    }
    actual_provider = str(agent.get("provider") or "").strip()
    if actual_provider not in allowed_providers:
        raise PermissionError(
            f"Agent provider drifted from the capability contract for {agent_name}: "
            f"expected one of {sorted(allowed_providers)!r}, got {actual_provider!r}"
        )

    expected_mcp = {str(item).strip() for item in (lane.get("mcp_allowlist") or [])}
    actual_mcp = {str(item).strip() for item in (agent.get("mcp_allowlist") or [])}
    unexpected_mcp = actual_mcp - expected_mcp
    if unexpected_mcp:
        raise PermissionError(
            f"Agent MCP policy drifted from the capability contract for {agent_name}."
        )

    required_secret_mode = str((contract.get("global") or {}).get("child_secret_mode") or "").strip()
    actual_secret_mode = str(agent.get("agent_trusted_child_env_secret_mode") or "").strip()
    if required_secret_mode and required_secret_mode != actual_secret_mode:
        raise PermissionError(f"Agent secret policy drifted from the capability contract for {agent_name}.")

    if lane.get("break_glass_required") and not agent.get("break_glass_required"):
        raise PermissionError(f"Break-glass enforcement is missing for {agent_name}.")
    if lane.get("ephemeral_required") and not agent.get("ephemeral"):
        raise PermissionError(f"Break-glass agent must be ephemeral: {agent_name}")
    return _without_disabled_surfaces(lane, agent.get("disabled_capability_surfaces"))


def _without_disabled_surfaces(lane: dict[str, Any], disabled: Any) -> dict[str, Any]:
    """Drop surfaces a deployment has retired (for example Gmail) from a lane.

    Only the agent-visible description narrows; guardrails, providers, and MCP
    allowlists are untouched, so this can never widen access.
    """

    names = {str(item).strip() for item in (disabled or []) if str(item).strip()}
    if not names:
        return lane
    narrowed = dict(lane)
    for key in ("read_surfaces", "write_surfaces"):
        if isinstance(lane.get(key), list):
            narrowed[key] = [item for item in lane[key] if str(item) not in names]
    if isinstance(lane.get("operations"), list):
        narrowed["operations"] = [
            item for item in lane["operations"] if str(item).split(".", 1)[0] not in names
        ]
    return narrowed


def capability_summary(lane: dict[str, Any]) -> dict[str, tuple[str, ...]]:
    """Return immutable agent-visible operation and limitation names."""

    return {
        "operations": tuple(str(item) for item in lane.get("operations") or []),
        "limitations": tuple(str(item) for item in lane.get("limitations") or []),
    }
