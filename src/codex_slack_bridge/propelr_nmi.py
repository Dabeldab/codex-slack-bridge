# AgentChat/coding_agent 2026-07-10T11:34:00-04:00: classify Propelr NMI setup emails without exposing keys.
# AgentChat/coding_agent 2026-07-10T12:05:00-04:00: pin Propelr NMI ticket classification defaults.
# AgentChat/coding_agent 2026-07-10T12:31:00-04:00: parse unlabeled Propelr NMI security keys.
from __future__ import annotations

from dataclasses import dataclass, field
from email.utils import getaddresses
import hashlib
import re
from typing import Any


PROPELR_NMI_TRUSTED_SENDERS = {"rfinley@propelrpay.com"}
PROPELR_NMI_TICKET_CLASSIFICATION = {
    "recordType": "1. NOVA Classic",
    "mainIssue": "Gateway Setup",
    "technicalIssue": "Integrated CC Device",
}
_EMAIL_ADDRESS_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)

_INTENT_RE = re.compile(
    r"\b(?:nmi|api\s*keys?|tokenization\s*keys?|security\s*keys?|setup)\b",
    re.IGNORECASE,
)
_SECRET_FIELD_RE = re.compile(
    r"^\s*(?P<label>(?:nmi\s+)?(?:api\s*key|tokenization\s*key|security\s*key|securitykey|gateway\s*key))\s*[:=-]\s*(?P<value>\S.{4,})\s*$",
    re.IGNORECASE,
)
_BARE_SECRET_RE = re.compile(r"^\s*(?P<value>[A-Za-z0-9_-]{24,})\s*$")
_ACCOUNT_SUBJECT_PATTERNS = (
    re.compile(r"\bnmi\s+setup\s*[-:]\s*(?P<name>.+)$", re.IGNORECASE),
    re.compile(r"^(?P<name>.+?)\s*[-:]\s*\d+\s+locations?\s*[-:]\s*api\s+keys?\b", re.IGNORECASE),
)
_ACCOUNT_BODY_RE = re.compile(
    r"^\s*(?:account|merchant|business|company|legal\s+name)\s*[:=-]\s*(?P<name>.+?)\s*$",
    re.IGNORECASE,
)
_DBA_RE = re.compile(r"\bdba\s+(?P<name>[^&,\r\n;]+)", re.IGNORECASE)
_NOISE_HEADING_RE = re.compile(
    r"\b(?:api|key|token|tokenization|security|nmi|credential|credentials|setup|please|thanks|team|hello|hi|below|merchant|account|device|terminal)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CredentialField:
    label: str
    value: str = field(repr=False)

    def to_redacted_dict(self) -> dict[str, str]:
        return {"label": self.label, "value": redact_secret(self.value)}


@dataclass(frozen=True)
class LocationCredentialBlock:
    location_name: str
    credentials: tuple[CredentialField, ...]

    def to_redacted_dict(self) -> dict[str, Any]:
        return {
            "locationName": self.location_name,
            "credentials": [credential.to_redacted_dict() for credential in self.credentials],
        }


@dataclass(frozen=True)
class PropelrNmiEmail:
    message_id: str
    thread_id: str
    sender: str
    subject: str
    account_candidates: tuple[str, ...]
    location_blocks: tuple[LocationCredentialBlock, ...]

    @property
    def has_credentials(self) -> bool:
        return any(block.credentials for block in self.location_blocks)

    def to_redacted_dict(self) -> dict[str, Any]:
        return {
            "messageId": self.message_id,
            "threadId": self.thread_id,
            "from": self.sender,
            "subject": self.subject,
            "accountCandidates": list(self.account_candidates),
            "locationBlocks": [block.to_redacted_dict() for block in self.location_blocks],
            "idempotencyKey": propelr_nmi_message_key(self.message_id, self.thread_id),
        }


def is_trusted_propelr_sender(sender: str) -> bool:
    parsed = {
        address.lower()
        for _name, address in getaddresses([sender or ""])
        if address and _EMAIL_ADDRESS_RE.fullmatch(address)
    }
    parsed.update(address.lower() for address in _EMAIL_ADDRESS_RE.findall(sender or ""))
    return len(parsed) == 1 and next(iter(parsed)) in PROPELR_NMI_TRUSTED_SENDERS


def is_propelr_nmi_candidate(sender: str, subject: str, body: str) -> bool:
    if not is_trusted_propelr_sender(sender):
        return False
    text = f"{subject}\n{body}"
    if not _INTENT_RE.search(text):
        return False
    parsed = parse_propelr_nmi_email(sender=sender, subject=subject, body=body)
    return parsed.has_credentials and bool(parsed.account_candidates or parsed.location_blocks)


def parse_propelr_nmi_email(
    *,
    sender: str,
    subject: str,
    body: str,
    message_id: str = "",
    thread_id: str = "",
) -> PropelrNmiEmail:
    lines = str(body or "").splitlines()
    account_candidates = _dedupe_preserving_order(
        [*_subject_account_candidates(subject), *_body_account_candidates(subject, body)]
    )
    blocks: dict[str, list[CredentialField]] = {}
    for index, line in enumerate(lines):
        match = _SECRET_FIELD_RE.match(line)
        if match:
            label = _clean_label(match.group("label"))
            value = match.group("value").strip()
        else:
            bare_match = _BARE_SECRET_RE.match(line)
            if not bare_match or not _has_nearby_key_context(lines, index):
                continue
            label = "Security Key"
            value = bare_match.group("value").strip()
        if not value:
            continue
        location_name = _nearest_location_heading(lines, index)
        blocks.setdefault(location_name or "Unassigned location", []).append(
            CredentialField(
                label=label,
                value=value,
            )
        )

    location_blocks = tuple(
        LocationCredentialBlock(location_name=name, credentials=tuple(credentials))
        for name, credentials in blocks.items()
    )
    return PropelrNmiEmail(
        message_id=str(message_id or "").strip(),
        thread_id=str(thread_id or "").strip(),
        sender=str(sender or "").strip(),
        subject=str(subject or "").strip(),
        account_candidates=tuple(account_candidates),
        location_blocks=location_blocks,
    )


def propelr_nmi_message_key(message_id: str, thread_id: str = "", location_name: str = "") -> str:
    message_id = str(message_id or "").strip().lower()
    thread_id = str(thread_id or "").strip().lower()
    location_name = _clean_candidate(location_name).lower()
    target = message_id or thread_id or "message"
    digest = hashlib.sha256("|".join(["propelr-nmi", message_id, thread_id, location_name]).encode("utf-8")).hexdigest()[:20]
    return f"propelr-nmi:{_safe_key_part(target)[:80]}:{digest}"


def redact_secret(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return "[REDACTED]"
    return f"[REDACTED:{len(text)} chars]"


def _subject_account_candidates(subject: str) -> list[str]:
    subject = str(subject or "").strip()
    candidates: list[str] = []
    for pattern in _ACCOUNT_SUBJECT_PATTERNS:
        match = pattern.search(subject)
        if match:
            candidates.append(_clean_candidate(match.group("name")))
    return [candidate for candidate in candidates if candidate]


def _body_account_candidates(subject: str, body: str) -> list[str]:
    candidates = [_clean_candidate(match.group("name")) for match in _ACCOUNT_BODY_RE.finditer(str(body or ""))]
    candidates.extend(_clean_candidate(match.group("name")) for match in _DBA_RE.finditer(f"{subject}\n{body}"))
    return [candidate for candidate in candidates if candidate]


def _nearest_location_heading(lines: list[str], secret_line_index: int) -> str:
    for offset in range(1, 8):
        candidate_index = secret_line_index - offset
        if candidate_index < 0:
            break
        candidate = _clean_candidate(lines[candidate_index])
        if _is_location_heading(candidate):
            return candidate
    return ""


def _has_nearby_key_context(lines: list[str], secret_line_index: int) -> bool:
    start = max(0, secret_line_index - 8)
    context = "\n".join(lines[start:secret_line_index]).lower()
    if any(term in context for term in ("key", "keys", "nmi", "credential", "credentials")):
        return True
    return bool(_nearest_location_heading(lines, secret_line_index))


def _is_location_heading(candidate: str) -> bool:
    if not candidate or len(candidate) > 120:
        return False
    lowered = candidate.lower()
    if "@" in candidate or lowered.startswith(("http://", "https://")):
        return False
    if _SECRET_FIELD_RE.match(candidate) or _NOISE_HEADING_RE.search(candidate):
        return False
    return True


def _clean_label(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().title()


def _clean_candidate(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip(" \t\r\n-:;")
    text = re.sub(r"^(?:location|store|dba|business|company|account)\s*[:=-]\s*", "", text, flags=re.IGNORECASE)
    return text.strip(" \t\r\n-:;")


def _dedupe_preserving_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _safe_key_part(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "-", str(value or "").strip()).strip("-") or "message"
