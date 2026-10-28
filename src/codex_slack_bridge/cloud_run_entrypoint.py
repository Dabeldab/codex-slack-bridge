from __future__ import annotations

"""Run the Command Center HTTP gateway and Slack Socket Mode in one Cloud Run service."""

import logging
import os
import subprocess
import threading
import time

from . import state as state_module
from .cloud_sql_state import build_cloud_sql_state

LOGGER = logging.getLogger("codex_slack_bridge.cloud_run")


def _install_persistence_backend() -> None:
    original = state_module.BridgeState

    # Use /tmp for Cloud Run writable filesystem
    cloud_sql_path = "/tmp/nova-cloudsql-state-placeholder"

    class ConfiguredBridgeState(build_cloud_sql_state(cloud_sql_path).__class__):
        pass

    # The command-center and Slack modules import BridgeState from the shared
    # state module. Replace that symbol before importing either module so both
    # use the same Cloud SQL-backed durable job/event store.
    if str(os.getenv("NOVA_DATABASE_BACKEND", "")).strip().lower() in {
        "cloudsql",
        "postgres",
        "postgresql",
    }:
        class CloudSqlStateProxy(state_module.BridgeState):
            def __new__(cls, path: str):
                return build_cloud_sql_state(cloud_sql_path)

        state_module.BridgeState = CloudSqlStateProxy
        LOGGER.info("Cloud SQL persistence backend enabled")
    else:
        state_module.BridgeState = original
        LOGGER.warning("Cloud SQL persistence is disabled; local state is ephemeral in Cloud Run")


def _relay_enabled() -> bool:
    return str(os.getenv("REASONING_RELAY_ENABLED") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _stage_codex_auth() -> None:
    """Materialize CODEX_HOME/auth.json from the codex-cli-oauth secret.

    Cloud Run passes the secret value via the CODEX_CLI_OAUTH env var (set with
    --update-secrets). The Codex CLI expects a writable CODEX_HOME/auth.json, so
    we write the env value into the CODEX_HOME directory at container start.
    The secret value is never logged.
    """
    codex_home = os.getenv("CODEX_HOME") or "/home/nova/.codex"
    auth_path = os.path.join(codex_home, "auth.json")
    payload = os.getenv("CODEX_CLI_OAUTH") or ""
    try:
        if not payload.strip():
            LOGGER.warning(
                "CODEX_CLI_OAUTH secret env is empty; autonomous Codex CLI auth unavailable"
            )
            return
        os.makedirs(codex_home, exist_ok=True)
        with open(auth_path, "wb") as dst_fp:
            dst_fp.write(payload.encode("utf-8"))
        os.chmod(auth_path, 0o600)
        LOGGER.info("Staged Codex auth to %s (%d bytes)", auth_path, len(payload))
    except Exception:
        LOGGER.exception("Failed to stage Codex auth from secret env")


def _log_codex_cli_readiness() -> None:
    """Log a credential-safe Codex CLI readiness result at container start.

    This runs as the same unprivileged Cloud Run user that executes agent jobs.
    It deliberately discards CLI output because it can contain account metadata;
    the exit status is enough to distinguish an executable/auth problem from a
    downstream Salesforce refresh failure.
    """
    executable = "/usr/local/bin/codex"
    try:
        result = subprocess.run(
            [executable, "login", "status"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
            check=False,
        )
    except (FileNotFoundError, PermissionError):
        LOGGER.warning("Codex CLI startup readiness failed: executable unavailable")
    except subprocess.TimeoutExpired:
        LOGGER.warning("Codex CLI startup readiness failed: login-status timed out")
    except Exception:
        LOGGER.exception("Codex CLI startup readiness check failed")
    else:
        LOGGER.info("Codex CLI startup readiness exit=%s", result.returncode)


def _validate_reasoning_relay_startup() -> None:
    """Fail the revision before serving traffic when the relay transport is unusable."""
    if not _relay_enabled():
        LOGGER.warning("Reasoning relay startup preflight is disabled")
        return

    from .reasoning_relay_broker_transport import BrokeredGitHubReasoningRelayTransport

    required = str(os.getenv("REASONING_RELAY_REQUIRED", "1")).strip().lower() in {
        "1", "true", "yes", "on",
    }
    try:
        transport = BrokeredGitHubReasoningRelayTransport.from_environment()
        health = transport.health()
        repository = str(health.get("repository") or "").strip()
        branch = str(health.get("branch") or "").strip()
        branch_exists = bool(health.get("branchExists"))
        expected_repository = str(
            os.getenv("REASONING_RELAY_REPOSITORY") or "dariusmakesstuff/codex-slack-bridge"
        ).strip()
        expected_branch = str(os.getenv("REASONING_RELAY_BRANCH") or "reasoning-relay-bus").strip()

        if repository.casefold() != expected_repository.casefold():
            raise RuntimeError("Reasoning relay resolved an unexpected repository")
        if branch != expected_branch or not branch_exists:
            raise RuntimeError("Reasoning relay branch is not available")
    except Exception:
        if required:
            raise
        # An optional relay must not take down the independent Codex primary.
        # Explicit relay jobs still fail closed instead of switching providers.
        LOGGER.warning("Optional reasoning relay preflight failed; Codex remains available")
        return
    LOGGER.info(
        "Reasoning relay startup preflight OK repository=%s branch=%s",
        repository, branch,
    )


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    _install_persistence_backend()
    _stage_codex_auth()
    _log_codex_cli_readiness()
    _validate_reasoning_relay_startup()

    # Import after the persistence shim is installed. Both modules retain their
    # existing execution paths and security contracts; only the durable state
    # implementation is swapped for the cloud-native deployment.
    from . import app as slack_app
    from . import command_center_server

    command_center_error: list[BaseException] = []

    def run_command_center() -> None:
        try:
            command_center_server.main()
        except BaseException as exc:  # pragma: no cover - process supervisor path
            command_center_error.append(exc)
            LOGGER.exception("Command Center runtime exited")

    thread = threading.Thread(
        target=run_command_center,
        name="nova-command-center",
        daemon=True,
    )
    thread.start()

    # Give the HTTP listener a moment to bind before Slack begins making local
    # Command Center calls during startup/reconciliation.
    deadline = time.monotonic() + float(os.getenv("NOVA_COMMAND_CENTER_STARTUP_GRACE_SECONDS", "15"))
    while time.monotonic() < deadline and thread.is_alive() and not command_center_error:
        time.sleep(0.25)
        if thread.ident is not None:
            break

    slack_socket_mode_enabled = str(os.getenv("SLACK_SOCKET_MODE_ENABLED", "1")).strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }
    try:
        if slack_socket_mode_enabled:
            slack_app.main()
        else:
            LOGGER.warning("Slack Socket Mode is disabled (SLACK_SOCKET_MODE_ENABLED=0); serving Command Center only")
            while not command_center_error:
                time.sleep(1)
    finally:
        if command_center_error:
            raise RuntimeError("Cloud Run Command Center exited") from command_center_error[0]


if __name__ == "__main__":
    main()
