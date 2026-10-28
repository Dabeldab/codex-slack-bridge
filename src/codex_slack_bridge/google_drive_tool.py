from __future__ import annotations

# AgentChat/coding_agent 2026-07-08T16:12:51Z: read-only Google Drive CLI for bridge agents.

import argparse
import json
import mimetypes
import os
import re
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials


DRIVE_API = "https://www.googleapis.com/drive/v3"
ADC_SCOPES = [
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/documents.readonly",
    "https://www.googleapis.com/auth/spreadsheets.readonly",
]
DEFAULT_FIELDS = (
    "nextPageToken,files("
    "id,name,mimeType,modifiedTime,webViewLink,parents,driveId,trashed,size,"
    "owners(displayName,emailAddress)"
    ")"
)
GOOGLE_EXPORTS: dict[str, dict[str, tuple[str, str]]] = {
    "application/vnd.google-apps.document": {
        "txt": ("text/plain", ".txt"),
        "docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".docx"),
        "pdf": ("application/pdf", ".pdf"),
        "html": ("text/html", ".html"),
    },
    "application/vnd.google-apps.spreadsheet": {
        "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".xlsx"),
        "csv": ("text/csv", ".csv"),
        "pdf": ("application/pdf", ".pdf"),
    },
    "application/vnd.google-apps.presentation": {
        "pptx": ("application/vnd.openxmlformats-officedocument.presentationml.presentation", ".pptx"),
        "pdf": ("application/pdf", ".pdf"),
        "txt": ("text/plain", ".txt"),
    },
    "application/vnd.google-apps.drawing": {
        "png": ("image/png", ".png"),
        "svg": ("image/svg+xml", ".svg"),
        "pdf": ("application/pdf", ".pdf"),
    },
}


class DriveToolError(RuntimeError):
    pass


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "auth-command":
            return cmd_auth_command(args)
        if args.command == "status":
            return cmd_status(args)
        if args.command == "search":
            return cmd_search(args)
        if args.command == "list-folder":
            return cmd_list_folder(args)
        if args.command == "metadata":
            return cmd_metadata(args)
        if args.command == "export":
            return cmd_export(args)
        parser.print_help()
        return 2
    except DriveToolError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read-only Google Drive helper for local Agent Chat and Slack agents."
    )
    parser.add_argument("--json-indent", type=int, default=2)
    sub = parser.add_subparsers(dest="command")

    auth = sub.add_parser("auth-command", help="Print the local gcloud ADC auth command for Drive read-only access.")
    auth.add_argument(
        "--client-id-file",
        default=os.getenv("GOOGLE_DRIVE_OAUTH_CLIENT_PATH", ""),
        help="Approved Desktop OAuth client JSON. Required when Workspace blocks gcloud's shared OAuth client.",
    )

    status = sub.add_parser("status", help="Check local Application Default Credentials and Drive API access.")
    status.add_argument("--no-api-check", action="store_true", help="Only inspect local ADC file presence.")

    search = sub.add_parser("search", help="Search Drive metadata and full text.")
    search.add_argument("terms", nargs="*", help="Search words. Used against name and fullText.")
    search.add_argument("--q", help="Raw Drive query. Combined with trashed filter.")
    search.add_argument("--folder-id", help="Restrict results to this folder id.")
    search.add_argument("--mime-type", help="Restrict results to this MIME type.")
    search.add_argument("--limit", type=int, default=10)
    search.add_argument("--include-trashed", action="store_true")

    folder = sub.add_parser("list-folder", help="List files directly in a Drive folder.")
    folder.add_argument("folder_id")
    folder.add_argument("--limit", type=int, default=25)
    folder.add_argument("--include-trashed", action="store_true")

    metadata = sub.add_parser("metadata", help="Read file metadata.")
    metadata.add_argument("file_id")

    export = sub.add_parser("export", help="Export or download one Drive file to a local path.")
    export.add_argument("file_id")
    export.add_argument("--output", required=True, help="Local output path. Use an agent sandbox or handoff path.")
    export.add_argument(
        "--format",
        choices=["txt", "docx", "pdf", "html", "xlsx", "csv", "pptx", "png", "svg", "raw"],
        default="txt",
        help="Export format for Google-native files. raw downloads non-native files.",
    )
    export.add_argument("--max-mb", type=int, default=100)
    return parser


def cmd_auth_command(args: argparse.Namespace) -> int:
    command = [
        gcloud_binary(),
        "auth",
        "application-default",
        "login",
    ]
    client_id_file = str(args.client_id_file or "").strip()
    if client_id_file:
        client_path = Path(client_id_file).expanduser().resolve()
        if not client_path.is_file():
            raise DriveToolError(f"Approved Desktop OAuth client JSON was not found: {client_path}")
        command.append(f"--client-id-file={client_path}")
    command.append(f"--scopes={','.join(ADC_SCOPES)}")
    print_json(
        {
            "ok": True,
            "command": command,
            "approved_client": bool(client_id_file),
            "note": (
                "Run this once locally. It stores ADC under the user gcloud config, not in this repo."
                if client_id_file
                else "Workspace-managed accounts may block gcloud's shared OAuth client. Pass --client-id-file with an approved Desktop OAuth client JSON if that happens."
            ),
        },
        args,
    )
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    adc = adc_path()
    info = adc_summary(adc)
    result: dict[str, Any] = {
        "ok": False,
        "gcloud": gcloud_binary(),
        "adc_path": str(adc),
        "adc_exists": adc.exists(),
        "adc": info,
    }
    if not adc.exists():
        result["next_step"] = "Run auth-command, then run the printed gcloud ADC login command."
        print_json(result, args)
        return 1
    if args.no_api_check:
        result["ok"] = True
        print_json(result, args)
        return 0
    about = drive_get_json(
        "/about",
        {
            "fields": "user(displayName,emailAddress),storageQuota(limit,usage)",
        },
    )
    result["ok"] = True
    result["drive_user"] = about.get("user") or {}
    result["storage_quota"] = about.get("storageQuota") or {}
    print_json(result, args)
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    limit = max(1, min(int(args.limit), 100))
    query = build_query(
        terms=" ".join(args.terms).strip(),
        raw_q=args.q,
        folder_id=args.folder_id,
        mime_type=args.mime_type,
        include_trashed=args.include_trashed,
    )
    data = drive_get_json(
        "/files",
        {
            "q": query,
            "pageSize": str(limit),
            "fields": DEFAULT_FIELDS,
            "orderBy": "modifiedTime desc",
            "includeItemsFromAllDrives": "true",
            "supportsAllDrives": "true",
        },
    )
    print_json({"ok": True, "query": query, "files": data.get("files", [])}, args)
    return 0


def cmd_list_folder(args: argparse.Namespace) -> int:
    limit = max(1, min(int(args.limit), 100))
    query = build_query(
        terms="",
        raw_q=None,
        folder_id=args.folder_id,
        mime_type=None,
        include_trashed=args.include_trashed,
    )
    data = drive_get_json(
        "/files",
        {
            "q": query,
            "pageSize": str(limit),
            "fields": DEFAULT_FIELDS,
            "orderBy": "folder,name",
            "includeItemsFromAllDrives": "true",
            "supportsAllDrives": "true",
        },
    )
    print_json({"ok": True, "query": query, "files": data.get("files", [])}, args)
    return 0


def cmd_metadata(args: argparse.Namespace) -> int:
    metadata = file_metadata(args.file_id)
    print_json({"ok": True, "file": metadata}, args)
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    metadata = file_metadata(args.file_id)
    mime_type = str(metadata.get("mimeType") or "")
    output_path = Path(args.output).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if mime_type == "application/vnd.google-apps.folder":
        raise DriveToolError("Folders cannot be exported. Use list-folder with this file id.")

    if mime_type.startswith("application/vnd.google-apps."):
        export_map = GOOGLE_EXPORTS.get(mime_type)
        if not export_map:
            raise DriveToolError(f"Unsupported Google-native MIME type for export: {mime_type}")
        requested = "txt" if args.format == "raw" else args.format
        if requested not in export_map:
            supported = ", ".join(sorted(export_map))
            raise DriveToolError(f"Format {requested!r} is not supported for {mime_type}. Supported: {supported}")
        export_mime, default_ext = export_map[requested]
        if output_path.suffix == "":
            output_path = output_path.with_suffix(default_ext)
        url = f"{DRIVE_API}/files/{urllib.parse.quote(args.file_id, safe='')}/export"
        content = request_bytes(url, {"mimeType": export_mime}, max_mb=args.max_mb)
    else:
        if output_path.suffix == "":
            output_path = output_path.with_suffix(extension_for(mime_type))
        url = f"{DRIVE_API}/files/{urllib.parse.quote(args.file_id, safe='')}"
        content = request_bytes(
            url,
            {"alt": "media", "supportsAllDrives": "true"},
            max_mb=args.max_mb,
        )

    output_path.write_bytes(content)
    print_json(
        {
            "ok": True,
            "file": {
                "id": metadata.get("id"),
                "name": metadata.get("name"),
                "mimeType": mime_type,
                "webViewLink": metadata.get("webViewLink"),
            },
            "output": str(output_path.resolve()),
            "bytes": len(content),
        },
        args,
    )
    return 0


def file_metadata(file_id: str) -> dict[str, Any]:
    return drive_get_json(
        f"/files/{urllib.parse.quote(file_id, safe='')}",
        {
            "fields": "id,name,mimeType,modifiedTime,webViewLink,parents,driveId,trashed,size,owners(displayName,emailAddress)",
            "supportsAllDrives": "true",
        },
    )


def build_query(
    *,
    terms: str,
    raw_q: str | None,
    folder_id: str | None,
    mime_type: str | None,
    include_trashed: bool,
) -> str:
    clauses: list[str] = []
    if not include_trashed:
        clauses.append("trashed = false")
    if raw_q:
        clauses.append(f"({raw_q})")
    if terms:
        escaped = drive_quote(terms)
        clauses.append(f"(name contains '{escaped}' or fullText contains '{escaped}')")
    if folder_id:
        clauses.append(f"'{drive_quote(folder_id)}' in parents")
    if mime_type:
        clauses.append(f"mimeType = '{drive_quote(mime_type)}'")
    return " and ".join(clauses) if clauses else "trashed = false"


def drive_get_json(path: str, params: dict[str, str]) -> dict[str, Any]:
    url = DRIVE_API + path
    body = request_bytes(url, params, max_mb=20)
    try:
        return json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise DriveToolError(f"Drive API returned invalid JSON: {exc}") from exc


def request_bytes(url: str, params: dict[str, str], *, max_mb: int) -> bytes:
    token = access_token()
    query = urllib.parse.urlencode(params)
    final_url = url + ("?" + query if query else "")
    request = urllib.request.Request(
        final_url,
        headers={"Authorization": f"Bearer {token}", "Accept": "*/*"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            length = response.headers.get("Content-Length")
            if length and int(length) > max_mb * 1024 * 1024:
                raise DriveToolError(f"Download refused: Content-Length exceeds {max_mb} MB")
            data = response.read(max_mb * 1024 * 1024 + 1)
    except urllib.error.HTTPError as exc:
        detail = exc.read(2000).decode("utf-8", errors="replace")
        raise DriveToolError(f"Drive API HTTP {exc.code}: {sanitize(detail)}") from exc
    except urllib.error.URLError as exc:
        raise DriveToolError(f"Drive API request failed: {sanitize(str(exc))}") from exc
    if len(data) > max_mb * 1024 * 1024:
        raise DriveToolError(f"Download refused: response exceeds {max_mb} MB")
    return data


def access_token() -> str:
    path = adc_path()
    if not path.is_file():
        raise DriveToolError(f"Application Default Credentials were not found: {path}")
    try:
        credentials = Credentials.from_authorized_user_file(str(path), ADC_SCOPES)
        if not credentials.valid:
            if not credentials.refresh_token:
                raise DriveToolError("Application Default Credentials cannot be refreshed.")
            credentials.refresh(Request())
    except DriveToolError:
        raise
    except (GoogleAuthError, OSError, ValueError) as exc:
        raise DriveToolError(
            "Could not refresh the local Application Default Credentials. "
            f"Run auth-command first. Google authentication said: {sanitize(str(exc))}"
        ) from exc
    token = str(credentials.token or "").strip()
    if not token or len(token) < 20:
        raise DriveToolError("Google authentication returned an empty or invalid ADC access token.")
    return token


def gcloud_binary() -> str:
    override = os.getenv("GCLOUD_CMD", "").strip()
    if override:
        return override
    candidates = ["gcloud.cmd", "gcloud.exe", "gcloud"] if os.name == "nt" else ["gcloud"]
    for candidate in candidates:
        found = shutil.which(candidate)
        if found:
            return found
    raise DriveToolError("gcloud was not found on PATH.")


def adc_path() -> Path:
    if os.name == "nt":
        appdata = os.getenv("APPDATA")
        if appdata:
            return Path(appdata) / "gcloud" / "application_default_credentials.json"
    return Path.home() / ".config" / "gcloud" / "application_default_credentials.json"


def adc_summary(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"readable": False}
    return {
        "readable": True,
        "type": raw.get("type"),
        "quota_project_id": raw.get("quota_project_id"),
        "client_id_present": bool(raw.get("client_id")),
        "scopes": raw.get("scopes") or raw.get("scope"),
    }


def print_json(value: dict[str, Any], args: argparse.Namespace) -> None:
    print(json.dumps(value, indent=args.json_indent, ensure_ascii=False))


def drive_quote(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def sanitize(text: str) -> str:
    redacted = re.sub(r"ya29\.[A-Za-z0-9._-]+", "[redacted-token]", text)
    redacted = re.sub(r"(?i)(access_token|refresh_token|authorization)[^,\n\r}]+", r"\1=[redacted]", redacted)
    return redacted[:2000]


def extension_for(mime_type: str) -> str:
    if mime_type:
        guessed = mimetypes.guess_extension(mime_type)
        if guessed:
            return guessed
    return ".bin"


if __name__ == "__main__":
    raise SystemExit(main())
