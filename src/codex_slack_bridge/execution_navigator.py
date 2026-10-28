# AgentChat/direct_codex 2026-07-29T20:35:00-04:00
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path
import re
from typing import Any, Iterable


_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "be",
    "for",
    "from",
    "i",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "please",
    "the",
    "this",
    "to",
    "we",
    "with",
}
_WRITE_RE = re.compile(
    r"\b(?:apply|cancel|change|charge|clos(?:e|ing|ure)|collect(?:ion)?|commit|create|credit|delete|deploy|"
    r"edit|forward|install|merge|patch|post|push|refund|remove|reply|restart|send|"
    r"submit|update|upload|write)\b",
    re.IGNORECASE,
)
_HIGH_RISK_RE = re.compile(
    r"\b(?:account\s+clos|allocation|billing|chargify|credential|customer|email|gmail|"
    r"location|maxio|payment|production|refund|salesforce|security|sql|subscription)\b",
    re.IGNORECASE,
)
_COMPLEX_RE = re.compile(
    r"\b(?:architect|build|debug|diagnos|end[-\s]?to[-\s]?end|implement|migrate|"
    r"multi[-\s]?system|race\s+condition|reconcile|redesign|refactor|repair|root\s+cause)\b",
    re.IGNORECASE,
)
_ROUTINE_RE = re.compile(
    r"\b(?:check|find|inspect|list|look\s+up|report|review|run|scan|status|summarize)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class NavigatorMatch:
    key: str
    display_name: str
    score: float
    primary_agents: tuple[str, ...] = ()
    required_tools: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExecutionPlan:
    confidence: str
    demand: str
    pipelines: tuple[NavigatorMatch, ...]
    tools: tuple[NavigatorMatch, ...]
    discovery_fallback: bool

    @property
    def recommended_model_class(self) -> str:
        return "fast" if self.demand in {"simple", "routine"} and not self.discovery_fallback else "quality"


class ExecutionNavigator:
    """Rank existing playbooks and tools without changing capability access."""

    def __init__(self, pipeline_registry_path: str | Path, tool_registry_path: str | Path) -> None:
        self.pipeline_registry_path = Path(pipeline_registry_path)
        self.tool_registry_path = Path(tool_registry_path)

    def plan(
        self,
        query: str,
        *,
        agent_name: str = "",
        excluded_tools: Iterable[str] = (),
        max_pipelines: int = 2,
        max_tools: int = 4,
    ) -> ExecutionPlan:
        text = " ".join(str(query or "").lower().split())
        excluded = {str(item).strip().lower() for item in excluded_tools if str(item).strip()}
        pipeline_registry = _read_json(self.pipeline_registry_path)
        tool_registry = _read_json(self.tool_registry_path)
        raw_pipelines = (
            pipeline_registry.get("pipelines")
            if isinstance(pipeline_registry.get("pipelines"), dict)
            else {}
        )
        raw_tools = tool_registry.get("tools") if isinstance(tool_registry.get("tools"), dict) else {}

        pipeline_matches: list[NavigatorMatch] = []
        for key, raw in raw_pipelines.items():
            if not isinstance(raw, dict) or str(key) == "route_and_scope":
                continue
            required_tools = tuple(str(item).strip() for item in raw.get("requires_tools") or [] if str(item).strip())
            if any(item.lower() in excluded for item in required_tools):
                continue
            aliases = [
                str(key),
                str(raw.get("display_name") or ""),
                *(str(item) for item in raw.get("aliases") or []),
                str(raw.get("use_when") or ""),
            ]
            score = _match_score(text, aliases)
            primary_agents = tuple(str(item) for item in raw.get("primary_agents") or [])
            if score <= 0:
                continue
            if agent_name and agent_name in primary_agents:
                score += 2.0
            pipeline_matches.append(
                NavigatorMatch(
                    key=str(key),
                    display_name=str(raw.get("display_name") or key),
                    score=score,
                    primary_agents=primary_agents,
                    required_tools=required_tools,
                )
            )
        pipeline_matches.sort(key=lambda item: (-item.score, item.key))
        selected_pipelines = tuple(pipeline_matches[: max(0, min(int(max_pipelines), 4))])

        dependency_scores: dict[str, float] = {}
        for match in selected_pipelines:
            for key in match.required_tools:
                dependency_scores[key] = max(dependency_scores.get(key, 0.0), match.score + 4.0)

        tool_matches: list[NavigatorMatch] = []
        for key, raw in raw_tools.items():
            if not isinstance(raw, dict) or str(key).lower() in excluded:
                continue
            aliases = [
                str(key),
                str(raw.get("display_name") or ""),
                *(str(item) for item in raw.get("aliases") or []),
            ]
            score = max(_match_score(text, aliases), dependency_scores.get(str(key), 0.0))
            primary_agents = tuple(str(item) for item in raw.get("primary_agents") or [])
            if score <= 0:
                continue
            if agent_name and agent_name in primary_agents:
                score += 1.0
            tool_matches.append(
                NavigatorMatch(
                    key=str(key),
                    display_name=str(raw.get("display_name") or key),
                    score=score,
                    primary_agents=primary_agents,
                )
            )
        tool_matches.sort(key=lambda item: (-item.score, item.key))
        selected_tools = tuple(tool_matches[: max(0, min(int(max_tools), 6))])

        top_score = max(
            [item.score for item in selected_pipelines] + [item.score for item in selected_tools] + [0.0]
        )
        confidence = "high" if top_score >= 12.0 else "medium" if top_score >= 6.0 else "low"
        demand = _classify_demand(
            text,
            confidence=confidence,
            selected_pipelines=selected_pipelines,
            selected_tools=selected_tools,
        )
        discovery_fallback = confidence == "low" and demand != "simple"
        return ExecutionPlan(
            confidence=confidence,
            demand=demand,
            pipelines=selected_pipelines,
            tools=selected_tools,
            discovery_fallback=discovery_fallback,
        )


def _classify_demand(
    text: str,
    *,
    confidence: str,
    selected_pipelines: tuple[NavigatorMatch, ...],
    selected_tools: tuple[NavigatorMatch, ...],
) -> str:
    if _WRITE_RE.search(text) and _HIGH_RISK_RE.search(text):
        return "high_risk"
    if _COMPLEX_RE.search(text):
        return "complex"
    required_tool_count = len({tool for match in selected_pipelines for tool in match.required_tools})
    if required_tool_count >= 2 or len(selected_tools) >= 3:
        return "complex"
    if _WRITE_RE.search(text):
        return "high_risk"
    if confidence == "high" and (selected_pipelines or _ROUTINE_RE.search(text)):
        return "routine"
    if _looks_like_simple_question(text):
        return "simple"
    return "standard"


def _match_score(query: str, aliases: Iterable[str]) -> float:
    best = 0.0
    query_tokens = _tokens(query)
    for raw_alias in aliases:
        alias = " ".join(str(raw_alias or "").lower().split())
        if not alias:
            continue
        if re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", query):
            best = max(best, 12.0 + min(len(alias), 30) / 30)
            continue
        alias_tokens = _tokens(alias)
        if not alias_tokens:
            continue
        overlap = len(query_tokens & alias_tokens)
        ratio = overlap / len(alias_tokens)
        if overlap >= 2 and ratio >= 0.5:
            best = max(best, 4.0 + 6.0 * ratio + min(overlap, 4) * 0.5)
    return best


def _tokens(value: str) -> set[str]:
    return {token for token in _TOKEN_RE.findall(str(value or "").lower()) if token not in _STOP_WORDS}


def _looks_like_simple_question(text: str) -> bool:
    normalized = " ".join(str(text or "").lower().split())
    return len(normalized) <= 500 and (
        normalized.endswith("?")
        or normalized.startswith(("what is ", "what are ", "why ", "how does ", "is ", "are ", "does ", "do "))
    )


@lru_cache(maxsize=16)
def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}
