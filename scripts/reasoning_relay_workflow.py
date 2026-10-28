from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


REQUEST_MARKER = "<!-- nova-reasoning-relay:v1:request -->"
RESPONSE_MARKER = "<!-- nova-reasoning-relay:v1:response -->"
RELAY_BRANCH = os.getenv("REASONING_RELAY_BRANCH", "reasoning-relay-bus")
OUTBOUND_PREFIX = "relay/runtime/outbound/"
INBOUND_PREFIX = "relay/runtime/inbound/"
FENCED_JSON_RE = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)


def _api(method: str, url: str, *, token: str, payload: Any = None) -> Any:
    data = None if payload is None else json.dumps(payload, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "nova-reasoning-relay-workflow/1.0",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", errors="replace").strip()
        except Exception:
            detail = ""
        accepted = str(exc.headers.get("X-Accepted-GitHub-Permissions") or "").strip()
        suffix = ""
        if accepted:
            suffix += f"; accepted_permissions={accepted}"
        if detail:
            suffix += f"; response={detail[:1000]}"
        raise RuntimeError(f"GitHub API {exc.code} {exc.reason}{suffix}") from exc
    return json.loads(body) if body else {}


def _changed_paths(before: str, after: str) -> list[str]:
    zero = "0" * 40
    if not before or before == zero:
        command = ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", after]
    else:
        command = ["git", "diff", "--name-only", before, after]
    output = subprocess.check_output(command, text=True, encoding="utf-8")
    return [line.strip() for line in output.splitlines() if line.strip()]


def _find_relay_pr(repo: str, token: str) -> int:
    owner = repo.split("/", 1)[0]
    query = urllib.parse.urlencode({"state": "open", "head": f"{owner}:{RELAY_BRANCH}", "per_page": 20})
    rows = _api("GET", f"https://api.github.com/repos/{repo}/pulls?{query}", token=token)
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("The long-lived reasoning relay pull request is not open")
    number = int(rows[0].get("number") or 0)
    if number < 1:
        raise RuntimeError("Reasoning relay pull request number is invalid")
    return number


def publish_request_comments(repo: str, before: str, after: str, token: str) -> int:
    pr_number = _find_relay_pr(repo, token)
    count = 0
    for path in _changed_paths(before, after):
        normalized = path.replace("\\", "/")
        if not normalized.startswith(OUTBOUND_PREFIX) or not normalized.endswith(".json"):
            continue
        request_path = Path(normalized)
        if not request_path.is_file():
            continue
        raw = json.loads(request_path.read_text(encoding="utf-8"))
        if raw.get("protocol_version") != 1 or raw.get("direction") != "to_chatgpt":
            raise ValueError(f"Invalid relay request: {normalized}")
        pointer = {
            "protocol_version": 1,
            "request_id": str(raw.get("message_id") or ""),
            "lane": str(raw.get("lane") or ""),
            "kind": str(raw.get("kind") or ""),
            "branch": RELAY_BRANCH,
            "path": normalized,
        }
        body = REQUEST_MARKER + "\n```json\n" + json.dumps(pointer, ensure_ascii=False, indent=2) + "\n```"
        _api("POST", f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments", token=token, payload={"body": body})
        count += 1
    return count


def _parse_response(body: str) -> dict[str, Any] | None:
    if RESPONSE_MARKER not in body:
        return None
    match = FENCED_JSON_RE.search(body)
    if not match:
        raise ValueError("Relay response comment is missing a fenced JSON object")
    raw = json.loads(match.group(1))
    if not isinstance(raw, dict):
        raise ValueError("Relay response comment must contain an object")
    if raw.get("protocol_version") != 1 or raw.get("direction") != "to_runtime":
        raise ValueError("Relay response envelope is invalid")
    reply_to = str(raw.get("in_reply_to") or "")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{7,199}", reply_to):
        raise ValueError("Relay response in_reply_to is invalid")
    if str(raw.get("kind") or "") not in {"tool_request", "final_response"}:
        raise ValueError("Relay response kind is invalid")
    return raw


def consume_response_comment(repo: str, event_path: str, token: str, allowed_actor: str) -> str:
    event = json.loads(Path(event_path).read_text(encoding="utf-8"))
    issue = event.get("issue") if isinstance(event.get("issue"), dict) else {}
    comment = event.get("comment") if isinstance(event.get("comment"), dict) else {}
    if not issue.get("pull_request"):
        return ""
    actor = str((comment.get("user") or {}).get("login") or "")
    allowed = {item.strip().casefold() for item in allowed_actor.split(",") if item.strip()}
    if allowed and actor.casefold() not in allowed:
        return ""
    raw = _parse_response(str(comment.get("body") or ""))
    if raw is None:
        return ""
    pr_number = int(issue.get("number") or 0)
    pr = _api("GET", f"https://api.github.com/repos/{repo}/pulls/{pr_number}", token=token)
    head = pr.get("head") if isinstance(pr.get("head"), dict) else {}
    if str(head.get("ref") or "") != RELAY_BRANCH:
        return ""
    reply_to = str(raw["in_reply_to"])
    path = Path(f"{INBOUND_PREFIX}{reply_to}.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(raw, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != content:
            raise RuntimeError("Relay response attempted to overwrite a different response")
        return ""
    path.write_text(content, encoding="utf-8")
    return path.as_posix()


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    publish = sub.add_parser("publish-request-comments")
    publish.add_argument("--repo", required=True)
    publish.add_argument("--before", required=True)
    publish.add_argument("--after", required=True)
    consume = sub.add_parser("consume-response-comment")
    consume.add_argument("--repo", required=True)
    consume.add_argument("--event-path", required=True)
    consume.add_argument("--allowed-actor", required=True)
    args = parser.parse_args()
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if not token:
        raise RuntimeError("GITHUB_TOKEN is required")
    if args.command == "publish-request-comments":
        print(publish_request_comments(args.repo, args.before, args.after, token))
        return 0
    path = consume_response_comment(args.repo, args.event_path, token, args.allowed_actor)
    if path:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
