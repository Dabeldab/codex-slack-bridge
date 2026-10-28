from __future__ import annotations

import os
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class ChannelRoute:
    channel_id: str
    agent_name: str
    listen: str


@dataclass(frozen=True)
class BridgeConfig:
    defaults: dict[str, Any]
    channels: dict[str, ChannelRoute]
    agents: dict[str, dict[str, Any]]


def configured_active_agents(defaults: dict[str, Any]) -> tuple[str, ...] | None:
    """Optional deployment roster; absent means preserve legacy configuration."""
    if "active_agents" not in defaults:
        return None
    names = defaults["active_agents"]
    if not isinstance(names, list) or not names:
        raise ValueError("active_agents must be a non-empty list of unique agent names")
    if any(not isinstance(name, str) or not name or name != name.strip() for name in names):
        raise ValueError("active_agents contains an invalid agent name")
    if len(names) != len(set(names)):
        raise ValueError("active_agents must not contain duplicates")
    return tuple(names)


def require_active_agent(agent_name: str, agent: dict[str, Any]) -> None:
    """Reject retired lanes before any provider, tool process, or policy load."""
    active = configured_active_agents(agent)
    if active is not None and agent_name not in active:
        raise PermissionError(f"Agent is disabled in this deployment: {agent_name}")
    if str(agent.get("provider") or "").strip().lower() == "disabled":
        raise PermissionError(f"Agent provider is disabled: {agent_name}")


def load_config(path: str | os.PathLike[str]) -> BridgeConfig:
    config_path = Path(path).resolve()
    if not config_path.exists():
        raise FileNotFoundError(f"Bridge config not found: {config_path}")
    raw = _load_config_mapping(config_path, stack=())
    defaults = raw.get("defaults") or {}
    all_agents = raw.get("agents") or {}
    channels_raw = raw.get("channels") or {}
    if not isinstance(defaults, dict):
        raise ValueError("Config defaults must be a map")
    if not isinstance(all_agents, dict):
        raise ValueError("Config agents must be a map")
    if not isinstance(channels_raw, dict):
        raise ValueError("Config channels must be a map")
    active = configured_active_agents(defaults)
    if active is None:
        agents = all_agents
    else:
        missing = set(active) - set(all_agents)
        if missing:
            raise ValueError(f"active_agents references unknown agents: {sorted(missing)}")
        agents = {name: all_agents[name] for name in active}
        for name, settings in agents.items():
            if not isinstance(settings, dict):
                raise ValueError(f"Agent config must be a map: {name}")
            require_active_agent(name, {**defaults, **settings})
        # A retired quality agent must never acquire a scheduled watcher.
        if "claude_agent" not in agents:
            defaults = {**defaults, "ops_weekly_support_quality_enabled": False}
    disabled_skills = {
        str(item).strip() for item in (defaults.get("disabled_skills") or []) if str(item).strip()
    }
    if disabled_skills:
        agents = {
            name: (
                {**settings, "skills": [s for s in settings["skills"] if str(s) not in disabled_skills]}
                if isinstance(settings, dict) and isinstance(settings.get("skills"), list)
                else settings
            )
            for name, settings in agents.items()
        }
    channels: dict[str, ChannelRoute] = {}
    for channel_id, route in channels_raw.items():
        if not isinstance(route, dict):
            raise ValueError(f"Channel route must be a map: {channel_id}")
        agent_name = route.get("agent")
        if not agent_name:
            raise ValueError(f"Channel route missing agent: {channel_id}")
        if agent_name not in all_agents:
            raise ValueError(f"Channel {channel_id} references unknown agent: {agent_name}")
        if agent_name not in agents:
            continue
        listen = route.get("listen", "mention")
        if listen not in {"all_messages", "mention"}:
            raise ValueError(f"Channel {channel_id} has invalid listen mode: {listen}")
        channels[channel_id] = ChannelRoute(channel_id, agent_name, listen)
    return BridgeConfig(defaults=defaults, channels=channels, agents=agents)


def _load_config_mapping(config_path: Path, *, stack: tuple[Path, ...]) -> dict[str, Any]:
    """Load one config with an optional local base file and deterministic deep overrides."""

    resolved = config_path.resolve()
    if resolved in stack:
        chain = " -> ".join(str(item) for item in (*stack, resolved))
        raise ValueError(f"Bridge config extends cycle: {chain}")
    if len(stack) >= 8:
        raise ValueError("Bridge config extends depth exceeds 8 files")
    if not resolved.is_file():
        raise FileNotFoundError(f"Bridge config not found: {resolved}")

    loaded = yaml.safe_load(resolved.read_text(encoding="utf-8")) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"Bridge config must be a map: {resolved}")

    extends = loaded.pop("extends", None)
    if extends is None:
        return loaded
    if not isinstance(extends, str) or not extends.strip():
        raise ValueError(f"Bridge config extends must be one non-empty path: {resolved}")

    base_path = Path(os.path.expandvars(os.path.expanduser(extends.strip())))
    if not base_path.is_absolute():
        base_path = resolved.parent / base_path
    base = _load_config_mapping(base_path, stack=(*stack, resolved))
    return _deep_merge(base, loaded)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Merge maps recursively; scalars and lists are replaced by the overlay."""

    merged = deepcopy(base)
    for key, value in override.items():
        prior = merged.get(key)
        if isinstance(prior, dict) and isinstance(value, dict):
            merged[key] = _deep_merge(prior, value)
        else:
            merged[key] = deepcopy(value)
    return merged


def expand_env(value: Any) -> Any:
    if isinstance(value, str):
        return os.path.expandvars(value)
    return value
