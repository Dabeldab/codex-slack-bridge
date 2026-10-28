from __future__ import annotations

import argparse
import grp
import os
import pwd
import re
import tempfile
from pathlib import Path

import google.auth
from google.auth import impersonated_credentials
from google.auth.transport.requests import Request


SERVICE_ACCOUNT_RE = re.compile(r"^[a-z][a-z0-9-]{2,28}@[a-z][a-z0-9-]{4,61}[a-z0-9]\.iam\.gserviceaccount\.com$")


def mint_token(*, target_principal: str, output: Path, owner: str, group: str) -> None:
    if not SERVICE_ACCOUNT_RE.fullmatch(target_principal):
        raise ValueError("target service account is invalid")
    resolved_parent = output.parent.resolve()
    if resolved_parent != Path("/run/nova-cloud-identity"):
        raise ValueError("token output must stay in the private cloud identity runtime directory")

    source, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    delegated = impersonated_credentials.Credentials(
        source_credentials=source,
        target_principal=target_principal,
        target_scopes=["https://www.googleapis.com/auth/cloud-platform"],
        lifetime=3600,
    )
    delegated.refresh(Request())
    token = str(delegated.token or "").strip()
    if not token or len(token) > 16_384:
        raise RuntimeError("Google Cloud did not return a valid delegated token")

    uid = pwd.getpwnam(owner).pw_uid
    gid = grp.getgrnam(group).gr_gid
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o710)
    os.chown(output.parent, 0, gid)
    os.chmod(output.parent, 0o710)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".access-token-", dir=output.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(token)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chown(temporary, uid, gid)
        os.chmod(temporary, 0o400)
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Mint Rory's short-lived Google Cloud operator token.")
    parser.add_argument("--target-principal", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--owner", default="nova-cloud-broker")
    parser.add_argument("--group", default="nova-cloud-broker")
    args = parser.parse_args()
    mint_token(
        target_principal=args.target_principal,
        output=args.output,
        owner=args.owner,
        group=args.group,
    )


if __name__ == "__main__":
    main()
