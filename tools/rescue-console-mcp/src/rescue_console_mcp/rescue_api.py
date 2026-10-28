from __future__ import annotations

import csv
import io
import os
from pathlib import Path
from typing import Any

from dotenv import dotenv_values
import requests


DEFAULT_RESCUE_BASE = "https://secure.logmeinrescue.com/API"


class _ReadOnlyRescueClient:
    """Minimal portable Rescue client containing only authenticated GET surfaces."""

    def __init__(self, email: str, password: str, *, base: str, verify_ssl: bool = True) -> None:
        self.email = email
        self.password = password
        self.base = base.rstrip("/")
        self.session = requests.Session()
        self.session.verify = verify_ssl

    def login(self) -> None:
        response = self.session.post(
            f"{self.base}/login.aspx",
            data={"email": self.email, "pwd": self.password},
            timeout=15,
        )
        response.raise_for_status()
        if not str(response.text or "").strip().upper().startswith("OK"):
            raise RuntimeError("Rescue login failed")

    def list_sessions(self, node: str, node_ref: str) -> str:
        response = self.session.get(
            f"{self.base}/getSession_v3.aspx",
            params={"node": node, "noderef": node_ref},
            timeout=30,
        )
        response.raise_for_status()
        return str(response.text or "").strip()

    def read_chat(self, session_id: str) -> str:
        response = self.session.get(
            f"{self.base}/getChat.aspx",
            params={"session": session_id},
            timeout=30,
        )
        response.raise_for_status()
        return str(response.text or "").strip()


class RescueApi:
    def __init__(self, connector_root: Path, env_file: Path) -> None:
        self.connector_root = connector_root
        self.env_file = env_file

    def configuration(self) -> dict[str, Any]:
        config = self._configuration_values()
        return {
            "portableClient": True,
            "envFileExists": self.env_file.exists(),
            "credentialsConfigured": bool(config.get("RESCUE_USER") or config.get("RESCUE_EMAIL"))
            and bool(config.get("RESCUE_PASS") or config.get("RESCUE_PWD")),
            "nodeConfigured": bool(config.get("RESCUE_NODE_ID") or config.get("RESCUE_GROUP_NODE_ID")),
            "nodeRef": config.get("RESCUE_NODE_REF") or "CHANNEL",
            "baseConfigured": bool(config.get("RESCUE_BASE")),
        }

    def _configuration_values(self) -> dict[str, str]:
        file_values = dotenv_values(self.env_file) if self.env_file.exists() else {}
        keys = {
            "RESCUE_USER",
            "RESCUE_EMAIL",
            "RESCUE_PASS",
            "RESCUE_PWD",
            "RESCUE_BASE",
            "RESCUE_NODE_ID",
            "RESCUE_GROUP_NODE_ID",
            "RESCUE_NODE_REF",
            "RESCUE_VERIFY_SSL",
        }
        return {
            key: str(os.getenv(key) or file_values.get(key) or "").strip()
            for key in keys
        }

    def _client(self) -> tuple[Any, dict[str, str]]:
        config = self._configuration_values()
        user = config.get("RESCUE_EMAIL") or config.get("RESCUE_USER") or ""
        password = config.get("RESCUE_PWD") or config.get("RESCUE_PASS") or ""
        if not user or not password:
            raise RuntimeError("Rescue credentials are not configured")
        base = config.get("RESCUE_BASE") or DEFAULT_RESCUE_BASE
        verify_ssl = config.get("RESCUE_VERIFY_SSL", "1").casefold() not in {
            "0",
            "false",
            "no",
            "off",
        }
        client = _ReadOnlyRescueClient(user, password, base=base, verify_ssl=verify_ssl)
        client.login()
        return client, config

    def list_sessions(self) -> dict[str, Any]:
        client, config = self._client()
        node = config.get("RESCUE_NODE_ID") or config.get("RESCUE_GROUP_NODE_ID") or ""
        if not node:
            raise RuntimeError("Rescue node ID is not configured")
        node_ref = config.get("RESCUE_NODE_REF") or "CHANNEL"
        raw = client.list_sessions(node, node_ref)
        return {
            "nodeRef": node_ref,
            "sessions": parse_sessions_v3(raw),
        }

    def read_chat(self, session_id: str) -> dict[str, Any]:
        clean_id = str(session_id or "").strip()
        if not clean_id.isdigit():
            raise ValueError("session_id must be the numeric Rescue session ID")
        client, _config = self._client()
        raw = str(client.read_chat(clean_id) or "").strip()
        normalized = raw.replace("\r\n", "\n")
        body = normalized
        if body.upper().startswith("OK"):
            body = body[2:].lstrip("\n :")
        if body.upper().startswith("CHATLOG:"):
            body = body[len("CHATLOG:") :].lstrip()
        return {
            "sessionId": clean_id,
            "available": bool(body),
            "minimal": not bool(body),
            "chat": body[:50000],
        }


def parse_sessions_v3(raw: str) -> list[dict[str, Any]]:
    text = str(raw or "").strip()
    if not text or text.upper() in {"OK", "ERROR", "NOTLOGGEDIN"}:
        return []
    if text.upper().startswith("OK"):
        text = text[2:].lstrip("\r\n :")
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return []
    delimiter = "|" if "|" in lines[0] else ","
    rows = list(csv.reader(io.StringIO("\n".join(lines)), delimiter=delimiter))
    if not rows:
        return []
    headers = [cell.strip() for cell in rows[0]]
    lowered = [header.casefold().replace(" ", "") for header in headers]
    if not any(value in {"id", "sessionid"} for value in lowered):
        return []
    sessions: list[dict[str, Any]] = []
    for values in rows[1:]:
        row = {
            headers[index]: values[index].strip() if index < len(values) else ""
            for index in range(len(headers))
            if headers[index]
        }
        session_id = _first(row, "ID", "Session ID")
        if not session_id.isdigit():
            continue
        sessions.append(
            {
                "sessionId": session_id,
                "status": _first(row, "Status"),
                "entry": _first(row, "Entry", "Channel Name"),
                "technician": _first(row, "Technician", "Technician Name", "Technician ID"),
                "contactName": _first(row, "Custom Field 0", "sCustomField0", "Your Name"),
                "phone": _first(row, "Custom Field 1", "sCustomField1", "Your Phone #"),
                "company": _first(row, "Custom Field 2", "sCustomField2", "Company name"),
                "location": _first(
                    row,
                    "Custom Field 3",
                    "Custom Field 4",
                    "Custom Field 5",
                    "sCustomField3",
                    "Location Name",
                ),
            }
        )
    return sessions


def _first(row: dict[str, str], *names: str) -> str:
    normalized = {key.casefold().replace(" ", ""): value for key, value in row.items()}
    for name in names:
        value = normalized.get(name.casefold().replace(" ", ""), "").strip()
        if value:
            return value
    return ""
