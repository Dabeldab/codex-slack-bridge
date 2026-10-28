from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any

from .agents import AgentRequest, _select_subagents, _select_task_skills, should_run_subagents
from .capabilities import CapabilityRouter
from .config import load_config


@dataclass(frozen=True)
class EvaluationResult:
    name: str
    passed: bool
    failures: tuple[str, ...]
    skills: tuple[str, ...]
    capabilities: tuple[str, ...]
    subagents: tuple[str, ...]


def run_evaluations(config_path: str | Path, cases_path: str | Path) -> dict[str, Any]:
    config_path = Path(config_path).resolve()
    config = load_config(config_path)
    cases = json.loads(Path(cases_path).read_text(encoding="utf-8"))
    registry_path = (config_path.parent.parent / str(config.defaults.get("tool_fast_paths_path") or "config/tool-fast-paths.json")).resolve()
    router = CapabilityRouter(registry_path)
    results: list[EvaluationResult] = []
    for case in cases:
        agent_name = str(case["agent"])
        agent = dict(config.defaults)
        agent.update(config.agents[agent_name])
        agent["name"] = agent_name
        task = str(case["task"])
        skills = _select_task_skills(agent, task)
        capabilities = [route.key for route in router.select(task, agent_name=agent_name)]
        request = AgentRequest(task, "eval", "eval", "eval", task_text=task)
        selected_subagents = (
            _select_subagents(agent.get("subagents") or [], int(agent.get("max_subagents") or 3), request)
            if should_run_subagents(agent, request)
            else []
        )
        subagent_names = [str(item.get("name") or "subagent") for item in selected_subagents]
        failures: list[str] = []
        for expected in case.get("expected_skills") or []:
            if expected not in skills:
                failures.append(f"missing skill {expected}")
        for forbidden in case.get("forbidden_skills") or []:
            if forbidden in skills:
                failures.append(f"forbidden skill {forbidden}")
        for expected in case.get("expected_capabilities") or []:
            if expected not in capabilities:
                failures.append(f"missing capability {expected}")
        for forbidden in case.get("forbidden_capabilities") or []:
            if forbidden in capabilities:
                failures.append(f"forbidden capability {forbidden}")
        if len(subagent_names) > int(case.get("max_subagents", 99)):
            failures.append(f"too many subagents: {len(subagent_names)}")
        results.append(
            EvaluationResult(
                name=str(case["name"]),
                passed=not failures,
                failures=tuple(failures),
                skills=tuple(skills),
                capabilities=tuple(capabilities),
                subagents=tuple(subagent_names),
            )
        )
    return {
        "ok": all(item.passed for item in results),
        "passed": sum(1 for item in results if item.passed),
        "failed": sum(1 for item in results if not item.passed),
        "results": [asdict(item) for item in results],
    }


def append_feedback(path: str | Path, *, case_name: str, category: str, note: str = "") -> None:
    allowed = {"helpful", "wrong_tool", "too_slow", "noisy", "inaccurate", "stale_memory"}
    if category not in allowed:
        raise ValueError(f"Unsupported feedback category: {category}")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"case": case_name, "category": category, "note": note[:1000]}) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run deterministic agent routing evaluations.")
    parser.add_argument("--config", default="config/agents.yaml")
    parser.add_argument("--cases", default="evals/agent_quality.json")
    args = parser.parse_args()
    result = run_evaluations(args.config, args.cases)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
