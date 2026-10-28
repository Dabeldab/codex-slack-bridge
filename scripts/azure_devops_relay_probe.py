from __future__ import annotations

import argparse
import json
import os
import urllib.parse
import urllib.request


def _get_json(url: str, token: str) -> dict:
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("Azure DevOps returned an unexpected payload")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--organization", required=True)
    parser.add_argument("--project", default="")
    args = parser.parse_args()
    token = os.getenv("AZURE_DEVOPS_ACCESS_TOKEN", "").strip()
    if not token:
        raise RuntimeError("AZURE_DEVOPS_ACCESS_TOKEN is required")
    organization = urllib.parse.quote(args.organization.strip(), safe="")
    if args.project.strip():
        project = urllib.parse.quote(args.project.strip(), safe="")
        payload = _get_json(f"https://dev.azure.com/{organization}/_apis/projects/{project}?api-version=7.1", token)
        print(json.dumps({"ok": True, "project": payload.get("name"), "projectId": payload.get("id")}, separators=(",", ":")))
    else:
        payload = _get_json(f"https://dev.azure.com/{organization}/_apis/projects?api-version=7.1&$top=1", token)
        print(json.dumps({"ok": True, "visibleProjects": int(payload.get("count") or 0)}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
