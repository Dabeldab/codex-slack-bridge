from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import time
from typing import Any, Iterable


@dataclass(frozen=True)
class CapabilityRoute:
    key: str
    display_name: str
    score: float
    auth_ready: bool
    missing_credential_groups: tuple[tuple[str, ...], ...]
    circuit_open: bool
    last_success_utc: str = ""
    last_error: str = ""


class CapabilityRouter:
    """Select relevant tool capabilities and retain lightweight health state."""

    def __init__(self, registry_path: str | Path, state_path: str | Path | None = None) -> None:
        self.registry_path = Path(registry_path)
        self.state_path = Path(state_path) if state_path else self.registry_path.parent / "capability-state.json"

    def select(
        self,
        query: str,
        *,
        agent_name: str = "",
        available_names: Iterable[str] = (),
        max_routes: int = 3,
    ) -> list[CapabilityRoute]:
        registry = self._read_json(self.registry_path)
        tools = registry.get("tools") if isinstance(registry.get("tools"), dict) else {}
        state = self._read_json(self.state_path).get("capabilities") or {}
        known_names = {str(name) for name in available_names} | set(os.environ)
        normalized_query = str(query or "").lower()
        routes: list[CapabilityRoute] = []
        for key, raw in tools.items():
            if not isinstance(raw, dict):
                continue
            aliases = [str(key)] + [str(value) for value in raw.get("aliases") or []]
            score = _alias_score(normalized_query, aliases)
            if score <= 0:
                continue
            if agent_name and agent_name in {str(value) for value in raw.get("primary_agents") or []}:
                score += 1.0
            missing = _missing_credential_groups(raw, known_names)
            item_state = state.get(str(key)) if isinstance(state, dict) else {}
            item_state = item_state if isinstance(item_state, dict) else {}
            open_until = float(item_state.get("circuitOpenUntil") or 0)
            routes.append(
                CapabilityRoute(
                    key=str(key),
                    display_name=str(raw.get("display_name") or key),
                    score=score,
                    auth_ready=not missing,
                    missing_credential_groups=tuple(missing),
                    circuit_open=open_until > time.time(),
                    last_success_utc=str(item_state.get("lastSuccessUtc") or ""),
                    last_error=str(item_state.get("lastError") or ""),
                )
            )
        routes.sort(key=lambda item: (-item.score, item.key))
        return routes[: max(0, min(int(max_routes), 6))]

    def record_success(self, key: str, *, latency_ms: float | None = None) -> None:
        updates: dict[str, Any] = {
            "failures": 0,
            "circuitOpenUntil": 0,
            "lastSuccessUtc": _utc_now(),
            "lastError": "",
        }
        if latency_ms is not None:
            updates["lastLatencyMs"] = max(0.0, float(latency_ms))
        self._update_state(
            key,
            updates,
        )

    def record_failure(self, key: str, error: str, *, threshold: int = 3, cooldown_seconds: int = 300) -> None:
        payload = self._read_json(self.state_path)
        capabilities = payload.setdefault("capabilities", {})
        current = capabilities.get(key) if isinstance(capabilities.get(key), dict) else {}
        failures = int(current.get("failures") or 0) + 1
        current.update(
            {
                "failures": failures,
                "lastFailureUtc": _utc_now(),
                "lastError": str(error or "")[:500],
                "circuitOpenUntil": time.time() + max(30, cooldown_seconds) if failures >= max(1, threshold) else 0,
            }
        )
        capabilities[key] = current
        self._write_json(payload)

    def _update_state(self, key: str, updates: dict[str, Any]) -> None:
        payload = self._read_json(self.state_path)
        capabilities = payload.setdefault("capabilities", {})
        current = capabilities.get(key) if isinstance(capabilities.get(key), dict) else {}
        current.update(updates)
        capabilities[key] = current
        self._write_json(payload)

    def _write_json(self, payload: dict[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        temp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        temp.replace(self.state_path)

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        try:
            parsed = json.loads(path.read_text(encoding="utf-8"))
            return parsed if isinstance(parsed, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}


def _alias_score(query: str, aliases: list[str]) -> float:
    best = 0.0
    for alias in aliases:
        normalized = alias.strip().lower()
        if not normalized:
            continue
        if re.search(rf"(?<![a-z0-9]){re.escape(normalized)}(?![a-z0-9])", query):
            best = max(best, 10.0 + min(len(normalized), 20) / 20)
        elif len(normalized) >= 5 and normalized in query:
            best = max(best, 5.0)
    return best


def _missing_credential_groups(tool: dict[str, Any], known_names: set[str]) -> list[tuple[str, ...]]:
    credentials = tool.get("credentials") if isinstance(tool.get("credentials"), dict) else {}
    groups = credentials.get("required_any") or []
    missing: list[tuple[str, ...]] = []
    for group in groups:
        names = tuple(str(name) for name in (group if isinstance(group, list) else [group]) if str(name))
        if names and not any(name in known_names for name in names):
            missing.append(names)
    return missing


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
