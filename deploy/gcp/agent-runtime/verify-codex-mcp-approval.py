from __future__ import annotations

import argparse
import json
import os
import pwd
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

from codex_slack_bridge.agent_runtime import extract_codex_session_id


IDENTITIES = {
    "alex": ("nova-alex", "/home/nova-alex"),
    "rory": ("nova-rory", "/home/nova-rory"),
}


def _extract_session_id(stderr: str, stdout: str) -> str:
    session_id = extract_codex_session_id(stderr, stdout)
    if session_id:
        return session_id
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        for key in ("thread_id", "session_id"):
            candidate = str(event.get(key) or "").strip().lower()
            if candidate:
                return candidate
    return ""


def _command(
    *,
    identity: str,
    workspace: Path,
    output_path: Path,
    session_id: str = "",
) -> list[str]:
    runtime_user, runtime_home = IDENTITIES[identity]
    config = [
        "-c",
        'mcp_servers.unattended_approval_probe.command="/opt/nova/venv/bin/python"',
        "-c",
        'mcp_servers.unattended_approval_probe.args=["-m","scoped_operations_mcp.approval_probe_server"]',
        "-c",
        'mcp_servers.unattended_approval_probe.default_tools_approval_mode="approve"',
    ]
    if session_id:
        return [
            "/usr/sbin/runuser",
            "-u",
            runtime_user,
            "--",
            "/usr/bin/env",
            f"HOME={runtime_home}",
            "/usr/local/bin/codex",
            "exec",
            "resume",
            "--json",
            "--skip-git-repo-check",
            "--output-last-message",
            str(output_path),
            *config,
            session_id,
            "-",
        ]
    return [
        "/usr/sbin/runuser",
        "-u",
        runtime_user,
        "--",
        "/usr/bin/env",
        f"HOME={runtime_home}",
        "/usr/local/bin/codex",
        "exec",
        "--json",
        "--cd",
        str(workspace),
        "--sandbox",
        "danger-full-access",
        "--skip-git-repo-check",
        "--output-last-message",
        str(output_path),
        *config,
        "-",
    ]


def _run(command: list[str], prompt: str, *, timeout: int) -> tuple[str, str, str]:
    completed = subprocess.run(
        command,
        input=prompt,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"Codex approval probe exited {completed.returncode}")
    stdout = str(completed.stdout or "")
    stderr = str(completed.stderr or "")
    session_id = _extract_session_id(stderr, stdout)
    return stdout, stderr, session_id


def _restore_config(path: Path, payload: bytes, *, uid: int, gid: int, mode: int) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.approval-probe-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
            os.fchmod(handle.fileno(), mode)
            os.fchown(handle.fileno(), uid, gid)
        descriptor = -1
        os.replace(temporary_name, path)
        temporary_name = ""
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify unattended MCP approval in fresh and resumed agent sessions."
    )
    parser.add_argument("--identity", choices=sorted(IDENTITIES), default="alex")
    parser.add_argument("--timeout", type=int, default=240)
    args = parser.parse_args()
    runtime_user, runtime_home = IDENTITIES[args.identity]
    account = pwd.getpwnam(runtime_user)
    config_path = Path(runtime_home) / ".codex" / "config.toml"
    config_before = config_path.read_bytes()
    config_stat = config_path.stat()
    workspace = Path(tempfile.mkdtemp(prefix="nova-approval-probe-", dir="/tmp"))
    os.chown(workspace, account.pw_uid, account.pw_gid)
    workspace.chmod(0o700)
    output_path = workspace / "last-message.txt"
    output_path.touch(mode=0o600)
    os.chown(output_path, account.pw_uid, account.pw_gid)
    run_id = uuid.uuid4().hex
    try:
        fresh_nonce = f"{run_id}-fresh"
        fresh_prompt = (
            "Authorized deployment regression only. Call the approval_probe tool from the "
            f"unattended_approval_probe server exactly once with nonce {fresh_nonce}. "
            "The probe has no external mutation. After the tool succeeds, answer PROBE_OK."
        )
        fresh_stdout, fresh_stderr, session_id = _run(
            _command(identity=args.identity, workspace=workspace, output_path=output_path),
            fresh_prompt,
            timeout=args.timeout,
        )
        if not session_id:
            raise RuntimeError("Fresh approval probe did not expose a resumable session id")
        fresh_ok = (
            fresh_nonce in fresh_stdout
            and "probeExecuted" in fresh_stdout
            and "user cancelled MCP tool call" not in fresh_stdout
        )

        output_path.write_text("", encoding="utf-8")
        resume_nonce = f"{run_id}-resume"
        resume_prompt = (
            "Authorized resumed-session regression only. Call the approval_probe tool from the "
            f"unattended_approval_probe server exactly once with nonce {resume_nonce}. "
            "The probe has no external mutation. After the tool succeeds, answer PROBE_OK."
        )
        resume_stdout, _resume_stderr, resumed_session_id = _run(
            _command(
                identity=args.identity,
                workspace=workspace,
                output_path=output_path,
                session_id=session_id,
            ),
            resume_prompt,
            timeout=args.timeout,
        )
        resume_ok = (
            resume_nonce in resume_stdout
            and "probeExecuted" in resume_stdout
            and "user cancelled MCP tool call" not in resume_stdout
            and (not resumed_session_id or resumed_session_id == session_id)
        )
        result = {
            "ok": bool(fresh_ok and resume_ok),
            "freshSessionApproved": bool(fresh_ok),
            "resumedSessionApproved": bool(resume_ok),
            "externalMutation": False,
            "identity": args.identity,
        }
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        raise SystemExit(0 if result["ok"] else 1)
    finally:
        _restore_config(
            config_path,
            config_before,
            uid=config_stat.st_uid,
            gid=config_stat.st_gid,
            mode=config_stat.st_mode & 0o777,
        )
        shutil.rmtree(workspace, ignore_errors=True)


if __name__ == "__main__":
    main()
