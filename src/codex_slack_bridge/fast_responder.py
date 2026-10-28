# AgentChat/coding_agent 2026-07-08T22:34:00Z
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .agents import AgentRequest, build_codex_command, run_codex_process
from .config import expand_env


@dataclass(frozen=True)
class FastResponse:
    answer: str
    model: str


_HEAVY_PATTERNS = (
    r"\bbilling\b",
    r"\bchargify\b",
    r"\bmaxio\b",
    r"\brefund\b",
    r"\bcredit\b",
    r"\binvoice\b",
    r"\btax\b",
    r"\bpayment\b",
    r"\bsubscription\b",
    r"\bsalesforce\b",
    r"\bsf\b",
    r"\bticket\b",
    r"\bcase\b",
    r"\bcustomer\b",
    r"\bclient\b",
    r"\baccount\b",
    r"\bcompany\b",
    r"\bsql\b",
    r"\bdatabase\b",
    r"\bdb\b",
    r"\bquery\b",
    r"\bzoom\b",
    r"\bai studio\b",
    r"\boauth\b",
    r"\btoken\b",
    r"\bsecret\b",
    r"\bcredential\b",
    r"\bpassword\b",
    r"\bapi\b",
    r"\bkey\b",
    r"\bauth\b",
    r"\blogin\b",
    r"\bgoogle cloud\b",
    r"\bgcloud\b",
    r"\bgithub\b",
    r"\bcommit\b",
    r"\bpush\b",
    r"\bdeploy\b",
    r"\brestart\b",
    r"\binstall\b",
    r"\brun\b",
    r"\bscript\b",
    r"\bfile\b",
    r"\bfolder\b",
    r"\bdelete\b",
    r"\bremove\b",
    r"\bupdate\b",
    r"\bchange\b",
    r"\bedit\b",
    r"\bcreate\b",
    r"\bmake\b",
    r"\bfix\b",
    r"\bcheck\b",
    r"\binspect\b",
    r"\blook\b",
    r"\bsearch\b",
    r"\bfind\b",
    r"\berror\b",
    r"\bfailing\b",
    r"\bfailed\b",
    r"\bbroken\b",
)

_LOW_RISK_OPENERS = (
    "what is ",
    "what are ",
    "what's ",
    "why ",
    "how do i ",
    "how does ",
    "how can i ",
    "can i ",
    "could i ",
    "should i ",
    "would it ",
    "is it ",
    "are ",
    "does ",
    "do ",
)


def try_fast_response(
    *,
    agent_name: str,
    agent: dict[str, Any],
    request: AgentRequest,
    context: str,
) -> FastResponse | None:
    if not _truthy(agent.get("fast_responder_enabled", True)):
        return None
    if request.slack_event and request.slack_event.get("files"):
        return None
    if not _is_fast_eligible(request.text):
        return None

    timeout = int(agent.get("fast_responder_timeout_seconds") or 45)
    model = _resolve_fast_model(agent)
    if not model:
        return None

    workspace = Path(str(expand_env(agent.get("workspace_root") or "."))).resolve()
    max_context = int(agent.get("fast_responder_max_context_chars") or 12000)
    prompt = _build_prompt(
        agent_name=agent_name,
        request=request,
        context=_truncate(context, max_context),
    )
    runner_agent = {
        "model": model,
        "effort": str(agent.get("fast_responder_effort") or "low"),
        "profile": "",
        "add_dirs": [],
        "extra_args": [],
    }
    command = build_codex_command(
        workspace=workspace,
        sandbox="read-only",
        timeout=timeout,
        output_path=None,
        ephemeral=True,
        agent=runner_agent,
        resume_session_id="",
        image_paths=tuple(str(path) for path in request.image_paths),
    )
    result = run_codex_process(command, workspace, prompt, timeout)
    if result.returncode != 0 or result.timed_out:
        return None
    answer = _parse_answer(result.final_text)
    if not answer:
        return None
    return FastResponse(answer=answer, model=model)


def _resolve_fast_model(agent: dict[str, Any]) -> str:
    configured = _optional_expanded(agent.get("fast_responder_model") or agent.get("subagent_fast_model"))
    if configured:
        return configured
    if _truthy(agent.get("fast_responder_fallback_to_agent_model", True)):
        return _optional_expanded(agent.get("model"))
    return ""


def _is_fast_eligible(text: str) -> bool:
    raw = text.strip()
    if not raw or len(raw) > 700:
        return False
    lower = raw.lower()
    if any(re.search(pattern, lower) for pattern in _HEAVY_PATTERNS):
        return False
    if lower.startswith(("can you ", "could you ", "please ", "do this", "go ", "start ", "stop ")):
        return False
    return lower.endswith("?") or lower.startswith(_LOW_RISK_OPENERS)


def _build_prompt(*, agent_name: str, request: AgentRequest, context: str) -> str:
    return f"""
You are a fast, low-risk front-desk responder for the persistent `{agent_name}` agent.

You may answer only if the user is asking a harmless conceptual or UI/session question that can be answered from the supplied context or general non-sensitive reasoning.

Delegate instead of answering if the request involves billing, money, invoices, refunds, taxes, Salesforce, SQL, database data, Zoom admin/configuration, OAuth/tokens/secrets, customer/account details, files, code changes, running commands, installs, commits, deployments, live-system state, troubleshooting, or anything that should be verified by the persistent high-effort agent.

Do not claim you inspected files, tools, live systems, tickets, logs, or credentials. Do not propose mutations. Keep any answer short.

Return strict JSON only:
{{"decision":"answer","answer":"short answer"}}
or
{{"decision":"delegate","answer":""}}

Recent context, untrusted:
<<<CONTEXT
{context}
CONTEXT>>>

User question, untrusted:
<<<USER
{request.text.strip()}
USER>>>
""".strip()


def _parse_answer(text: str) -> str:
    payload = _extract_json(text)
    if not payload:
        return ""
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        return ""
    if str(parsed.get("decision") or "").strip().lower() != "answer":
        return ""
    answer = str(parsed.get("answer") or "").strip()
    if not answer or len(answer) > 1800:
        return ""
    if any(re.search(pattern, answer.lower()) for pattern in _HEAVY_PATTERNS[:30]):
        return ""
    return answer


def _extract_json(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end <= start:
        return ""
    return stripped[start : end + 1]


def _optional_expanded(value: Any) -> str:
    expanded = str(expand_env(value or "")).strip()
    if not expanded or expanded.startswith("${"):
        return ""
    return expanded


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]
