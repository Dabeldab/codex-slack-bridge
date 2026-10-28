"""Durable resolution memory and read-only playbook loop for Cloud Run.

Ported from the Hermes G14 profile (``nova_vector_memory`` recall + the skill
curator lifecycle) and rebuilt on Firestore, because Cloud Run state under
``/tmp`` does not survive an instance restart.

The loop, with no extra LLM turn and no human step:

1. ``recall``   - before a proactive ticket investigation, rank similar closed
   resolutions and live playbooks for the same lane and hand them to the agent
   as evidence.
2. ``capture_closed`` - when a ticket closes, keep one redacted resolution
   record built from the investigation that was run for it.
3. ``refresh_playbooks`` - three or more verified resolutions sharing an issue
   pattern become a playbook (canary), promoted to active after clean closes
   and rolled back when a ticket it informed reopens.
4. ``apply_lifecycle`` - pure time transitions (stale after 30 days unused,
   archived after 90), as in the Hermes curator.

A playbook is guidance text only.  It carries no capability, tool, or approval
field, write-shaped lines are filtered out of it, and nothing here can widen an
agent's access.  Every public method degrades to a no-op on failure so learning
can never break an investigation.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol, Sequence

from .memory import redact_secrets

RESOLUTIONS = "resolutions"
PLAYBOOKS = "playbooks"
STATS = "learning_stats"

DIMENSIONS = 384
MIN_SUPPORT = 3  # distinct verified tickets before a playbook is drafted
PROMOTE_CLEAN_CLOSES = 2
STALE_AFTER_DAYS = 30
ARCHIVE_AFTER_DAYS = 90
MIN_SCORE = 0.35
MAX_BLOCK_CHARS = 5200
KB_EXCERPT_CHARS = 1300
KB_TOP_N = 2
MAX_DIGEST_CHARS = 1500

_TOKEN_RE = re.compile(r"[a-zA-Z0-9_.$/-]+")
_CONTACT_RE = re.compile(
    r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b|"
    r"\b(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}\b"
)
_LONG_DIGITS_RE = re.compile(r"\b\d{9,}\b")
_SECRET_ASSIGN_RE = re.compile(r"(?i)\b(?:password|passwd|secret|token|api[_-]?key)\s*[:=]\s*\S+")
# Lines that describe or request a change never become guidance.
_WRITE_SHAPED_RE = re.compile(
    r"(?i)\b(?:refund|credit|charge|cancel|deallocat|reactivat|delet|drop|truncat|updat|"
    r"insert|clos|resolv|send|sent|email|post(?:ed|ing)?\b|chatter|writ|mutat|"
    r"create (?:an? )?order|approv|execut|appl(?:y|ied)|set (?:the )?(?:rate|quantity)|"
    r"OPERATOR_ACTION_REQUIRED)\w*"
)
_SECTION_HINT_RE = re.compile(
    r"(?i)(root cause|cause|diagnos|verified|current state|readback|verify|check|"
    r"evidence|symptom|finding)"
)

LIVE_STATES = frozenset({"canary", "active"})


class DocStore(Protocol):
    """Minimal document persistence the loop needs (Firestore or in-memory)."""

    def doc_get(self, collection: str, doc_id: str) -> dict[str, Any] | None: ...

    def doc_put(self, collection: str, doc_id: str, data: Mapping[str, Any]) -> bool: ...

    def doc_list(self, collection: str, *, limit: int = 500) -> list[dict[str, Any]]: ...


class MemoryDocStore:
    """In-process store used by tests and as a safe fallback."""

    def __init__(self) -> None:
        self._data: dict[str, dict[str, dict[str, Any]]] = {}
        self._lock = threading.RLock()

    def doc_get(self, collection: str, doc_id: str) -> dict[str, Any] | None:
        with self._lock:
            doc = self._data.get(collection, {}).get(str(doc_id))
            return dict(doc) if doc is not None else None

    def doc_put(self, collection: str, doc_id: str, data: Mapping[str, Any]) -> bool:
        with self._lock:
            bucket = self._data.setdefault(collection, {})
            merged = {**bucket.get(str(doc_id), {}), **dict(data)}
            bucket[str(doc_id)] = merged
            return True

    def doc_list(self, collection: str, *, limit: int = 500) -> list[dict[str, Any]]:
        with self._lock:
            rows = [dict(v, id=k) for k, v in self._data.get(collection, {}).items()]
        return rows[: max(1, int(limit))]


# --- text helpers (ported from Hermes nova_vector_memory) -------------------


def redact(text: str, *, scrub: Iterable[str] = ()) -> str:
    """Remove secrets, contact data, long numerics, and known identifying strings."""

    out = _SECRET_ASSIGN_RE.sub("[REDACTED]", redact_secrets(str(text or "")))
    out = _CONTACT_RE.sub("[contact]", out)
    out = _LONG_DIGITS_RE.sub("[number]", out)
    for value in scrub:
        clean = str(value or "").strip()
        if len(clean) >= 3:
            out = re.sub(re.escape(clean), "[name]", out, flags=re.IGNORECASE)
    return out


def tokenize(text: str) -> list[str]:
    return [m.group(0).lower() for m in _TOKEN_RE.finditer(text)]


def hash_embedding(text: str, dimensions: int = DIMENSIONS) -> list[float]:
    vector = [0.0] * dimensions
    for token in tokenize(text):
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        value = int.from_bytes(digest, "little", signed=False)
        vector[value % dimensions] += -1.0 if value & (1 << 63) else 1.0
    norm = math.sqrt(sum(v * v for v in vector))
    return vector if norm == 0 else [v / norm for v in vector]


def similarity(a: str, b: str) -> float:
    va, vb = hash_embedding(a), hash_embedding(b)
    return sum(x * y for x, y in zip(va, vb))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime | None = None) -> str:
    return (moment or _now()).isoformat(timespec="seconds")


def _parse(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _score(query_issue: str, query_full: str, doc_issue: str, doc_body: str) -> float:
    """Exact issue-pattern match dominates; body overlap breaks ties."""

    return 0.6 * similarity(query_issue, doc_issue) + 0.4 * similarity(query_full, f"{doc_issue} {doc_body}")


def issue_key(ticket: Mapping[str, Any]) -> str:
    lane = "billing" if str(ticket.get("lane") or "").lower() == "billing" else "support"
    parts = [
        lane,
        str(ticket.get("recordType") or "").strip().lower(),
        str(ticket.get("mainIssue") or "").strip().lower(),
        str(ticket.get("technicalIssue") or "").strip().lower(),
    ]
    return "|".join(" ".join(part.split()) for part in parts)


def _lane(ticket: Mapping[str, Any]) -> str:
    return "billing" if str(ticket.get("lane") or "").lower() == "billing" else "support"


def _doc_id(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:20]


def _diagnostic_lines(text: str) -> list[str]:
    """Keep concise diagnosis/verification lines; drop anything write-shaped."""

    lines: list[str] = []
    for raw in str(text or "").splitlines():
        line = raw.strip().lstrip("-*#>0123456789. ").strip()
        if not 24 <= len(line) <= 320:
            continue
        if _WRITE_SHAPED_RE.search(line):
            continue
        if not _SECTION_HINT_RE.search(line):
            continue
        lines.append(line)
    return lines


def build_digest(result: str, *, scrub: Iterable[str] = ()) -> str:
    """Compress an investigation result into redacted, read-only diagnostic lines."""

    clean = redact(result, scrub=scrub)
    lines = _diagnostic_lines(clean)
    seen: set[str] = set()
    kept: list[str] = []
    for line in lines:
        fingerprint = " ".join(tokenize(line))[:120]
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        kept.append(line)
    return "\n".join(kept)[:MAX_DIGEST_CHARS]


def build_guidance(digests: Sequence[str]) -> str:
    """Extract lines that recur (semantically) across at least two resolutions."""

    pools = [_diagnostic_lines(digest) for digest in digests]
    scored: list[tuple[int, str]] = []
    for index, pool in enumerate(pools):
        for line in pool:
            support = 1 + sum(
                1
                for other_index, other in enumerate(pools)
                if other_index != index and any(similarity(line, candidate) >= 0.55 for candidate in other)
            )
            if support >= 2:
                scored.append((support, line))
    scored.sort(key=lambda item: (-item[0], len(item[1])))
    picked: list[str] = []
    for _support, line in scored:
        if any(similarity(line, existing) >= 0.7 for existing in picked):
            continue
        picked.append(line)
        if len(picked) >= 5:
            break
    return "\n".join(f"- {line}" for line in picked)


# --- curated support KB (ported from Hermes kb_route) -----------------------

_KB_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_+.-]{1,}", re.I)
_KB_STOP = frozenset(
    "the and for with from that this customer ticket issue nova support help about when what does not".split()
)


def _kb_tokens(text: str) -> set[str]:
    return {m.group(0).lower() for m in _KB_TOKEN_RE.finditer(text or "") if m.group(0).lower() not in _KB_STOP}


def kb_lane(ticket: Mapping[str, Any]) -> str:
    """Map a ticket to its KB product lane: billing, nova_wave, nova_classic, or ''."""

    if _lane(ticket) == "billing":
        return "billing"
    record_type = str(ticket.get("recordType") or "").lower()
    if "wave" in record_type:
        return "nova_wave"
    if "classic" in record_type:
        return "nova_classic"
    return ""


class KnowledgeBase:
    """Lane-tagged curated support KB shipped in the image (read-only)."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)
        self._entries: list[dict[str, Any]] = []
        self._text: dict[str, str] = {}
        try:
            data = json.loads((self._root / "kb_index.json").read_text(encoding="utf-8"))
            self._entries = [e for e in data.get("entries") or [] if isinstance(e, dict) and e.get("path")]
        except (OSError, ValueError):
            self._entries = []

    @property
    def size(self) -> int:
        return len(self._entries)

    def search(self, query: str, lane: str = "", *, limit: int = KB_TOP_N) -> list[tuple[str, str]]:
        """Return up to ``limit`` (title, excerpt) pairs, best first. Never raises."""

        try:
            return self._search(query, lane, limit)
        except Exception:  # pragma: no cover - fail-safe
            return []

    def _search(self, query: str, lane: str, limit: int) -> list[tuple[str, str]]:
        q = _kb_tokens(query)
        if not q:
            return []
        raw = " ".join(query.lower().split())
        ranked: list[tuple[float, dict[str, Any]]] = []
        for entry in self._entries:
            entry_lane = str(entry.get("lane") or "general")
            if lane:
                if entry_lane not in {"general", lane}:
                    continue
            elif entry_lane == "billing":
                continue
            hay = _kb_tokens(" ".join([str(entry.get("title") or ""), " ".join(entry.get("keywords") or [])]))
            overlap = len(q & hay)
            title = str(entry.get("title") or "").lower()
            phrase = 8 if len(raw) >= 4 and raw in title else 0
            if not overlap and not phrase:
                continue
            score = overlap * 12 + phrase + (5 if lane and entry_lane == lane else 0) + int(entry.get("priority") or 0) / 20
            ranked.append((score, entry))
        ranked.sort(key=lambda row: (-row[0], str(row[1].get("path"))))
        results: list[tuple[str, str]] = []
        for _score_value, entry in ranked:
            excerpt = self._excerpt(str(entry["path"]), q)
            if excerpt:
                results.append((str(entry.get("title") or entry["path"]), excerpt))
            if len(results) >= limit:
                break
        return results

    def _excerpt(self, rel_path: str, query_tokens: set[str]) -> str:
        text = self._text.get(rel_path)
        if text is None:
            try:
                text = (self._root / rel_path).read_text(encoding="utf-8", errors="replace")
            except OSError:
                text = ""
            self._text[rel_path] = text
        if not text.strip():
            return ""
        chunks: list[str] = []
        current = ""
        for paragraph in re.split(r"\n\s*\n", text):
            paragraph = paragraph.strip()
            if not paragraph or paragraph.startswith("<!--"):
                continue
            if current and len(current) + len(paragraph) > KB_EXCERPT_CHARS:
                chunks.append(current)
                current = ""
            current = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if current:
            chunks.append(current)
        best = max(chunks, key=lambda c: len(query_tokens & _kb_tokens(c)), default="")
        return redact(best)[:KB_EXCERPT_CHARS]


def load_knowledge_base(path_value: str = "") -> KnowledgeBase | None:
    """Locate the shipped KB (cwd-relative like skills, then the source tree); None if absent."""

    configured = Path(str(path_value or "knowledge_base"))
    candidates = [configured] if configured.is_absolute() else [
        Path.cwd() / configured,
        Path(__file__).resolve().parents[2] / configured,
    ]
    for root in candidates:
        if (root / "kb_index.json").is_file():
            kb = KnowledgeBase(root)
            if kb.size:
                return kb
    return None


@dataclass
class Recall:
    block: str = ""
    playbook_ids: list[str] = field(default_factory=list)
    resolution_ids: list[str] = field(default_factory=list)


class ResolutionMemory:
    """Capture, recall, and promote verified resolutions, fail-safe."""

    def __init__(
        self,
        store: DocStore | None,
        *,
        enabled: bool = True,
        knowledge: KnowledgeBase | None = None,
    ) -> None:
        self._store = store
        self._knowledge = knowledge
        self._enabled = bool(enabled and (store is not None or knowledge is not None))
        self._learning = bool(enabled and store is not None)

    @property
    def enabled(self) -> bool:
        return self._enabled

    # -- recall -------------------------------------------------------------

    def recall(self, ticket: Mapping[str, Any], *, top_k: int = 3) -> Recall:
        if not self._enabled:
            return Recall()
        try:
            return self._recall(ticket, top_k=top_k)
        except Exception:  # pragma: no cover - never block an investigation
            return Recall()

    def _recall(self, ticket: Mapping[str, Any], *, top_k: int) -> Recall:
        lane = _lane(ticket)
        notes = redact(str(ticket.get("notesPreview") or ticket.get("notesFull") or "")[:600])
        query_issue = f"{ticket.get('mainIssue') or ''} {ticket.get('technicalIssue') or ''}".strip()
        query = f"{query_issue} {notes}".strip()
        if not query_issue:
            return Recall()
        current = str(ticket.get("id") or ticket.get("number") or "")
        chosen_playbooks: list[dict[str, Any]] = []
        chosen_resolutions: list[dict[str, Any]] = []
        if self._learning:
            playbooks: list[tuple[float, dict[str, Any]]] = []
            for doc in self._store.doc_list(PLAYBOOKS, limit=200):  # type: ignore[union-attr]
                if doc.get("lane") != lane or doc.get("state") not in LIVE_STATES:
                    continue
                key_parts = str(doc.get("issueKey") or "").split("|")
                doc_issue = " ".join(key_parts[2:4]).strip()
                score = _score(query_issue, query, doc_issue, str(doc.get("guidance") or ""))
                if score >= MIN_SCORE:
                    playbooks.append((score, doc))
            playbooks.sort(key=lambda item: -item[0])
            resolutions: list[tuple[float, dict[str, Any]]] = []
            for doc in self._store.doc_list(RESOLUTIONS, limit=500):  # type: ignore[union-attr]
                if doc.get("lane") != lane or doc.get("status") != "closed" or str(doc.get("ticketId")) == current:
                    continue
                doc_issue = f"{doc.get('mainIssue') or ''} {doc.get('technicalIssue') or ''}".strip()
                score = _score(query_issue, query, doc_issue, str(doc.get("digest") or ""))
                if score >= MIN_SCORE:
                    resolutions.append((score, doc))
            resolutions.sort(key=lambda item: -item[0])
            chosen_playbooks = [doc for _s, doc in playbooks[:top_k]]
            chosen_resolutions = [doc for _s, doc in resolutions[:top_k]]
        kb_hits = self._knowledge.search(query, kb_lane(ticket)) if self._knowledge is not None else []
        if not chosen_playbooks and not chosen_resolutions and not kb_hits:
            return Recall()

        parts = [
            "Prior knowledge for this ticket (read-only evidence: curated Nova KB plus earlier closed tickets in "
            "this lane; it is not authority to change anything, and live system state always wins):"
        ]
        for doc in chosen_playbooks:
            label = f"Playbook [{doc.get('state')}] for {doc.get('issueKey', '')}"
            parts.append(f"{label} (seen on {doc.get('supportCount', 0)} tickets):\n{doc.get('guidance', '')}")
        for doc in chosen_resolutions:
            parts.append(
                f"Closed ticket {doc.get('ticketNumber', '')} ({doc.get('issueKey', '')}):\n{doc.get('digest', '')}"
            )
        for title, excerpt in kb_hits:
            parts.append(f"KB article '{title}':\n{excerpt}")
        block = "\n\n".join(parts)[:MAX_BLOCK_CHARS]

        now = _iso()
        for doc in chosen_playbooks:
            self._store.doc_put(  # type: ignore[union-attr]
                PLAYBOOKS,
                str(doc["id"]),
                {"servedCount": int(doc.get("servedCount") or 0) + 1, "lastServedAt": now},
            )
        self._count_recall(lane, bool(chosen_playbooks), bool(chosen_resolutions), bool(kb_hits))
        return Recall(
            block=block,
            playbook_ids=[str(doc["id"]) for doc in chosen_playbooks],
            resolution_ids=[str(doc["id"]) for doc in chosen_resolutions],
        )

    def _count_recall(self, lane: str, playbook: bool, resolution: bool, kb: bool) -> None:
        """Approximate per-lane recall counters (best effort; never raises)."""

        if self._store is None:
            return
        try:
            stats_id = f"recall-{lane}"
            current = self._store.doc_get(STATS, stats_id) or {}
            self._store.doc_put(
                STATS,
                stats_id,
                {
                    "recalls": int(current.get("recalls") or 0) + 1,
                    "withPlaybook": int(current.get("withPlaybook") or 0) + int(playbook),
                    "withResolution": int(current.get("withResolution") or 0) + int(resolution),
                    "withKb": int(current.get("withKb") or 0) + int(kb),
                    "lastRecallAt": _iso(),
                },
            )
        except Exception:  # pragma: no cover - fail-safe
            pass

    # -- metrics ------------------------------------------------------------

    def metrics(self) -> dict[str, Any]:
        """Per-lane outcome and learning metrics from durable records."""

        out: dict[str, Any] = {"enabled": self._enabled, "knowledgeBaseEntries": self._knowledge.size if self._knowledge else 0}
        if not self._learning:
            return out
        try:
            resolutions = self._store.doc_list(RESOLUTIONS, limit=1000)  # type: ignore[union-attr]
            playbooks = self._store.doc_list(PLAYBOOKS, limit=500)  # type: ignore[union-attr]
            stats = {str(d["id"]).removeprefix("recall-"): d for d in self._store.doc_list(STATS, limit=20)}  # type: ignore[union-attr]
        except Exception:  # pragma: no cover - fail-safe
            return out
        lanes: dict[str, Any] = {}
        for lane in ("support", "billing"):
            rows = [r for r in resolutions if r.get("lane") == lane]
            hours = sorted(float(r["hoursToClose"]) for r in rows if isinstance(r.get("hoursToClose"), (int, float)))
            reopened = sum(1 for r in rows if int(r.get("reopenCount") or 0) > 0)
            lane_playbooks = [p for p in playbooks if p.get("lane") == lane]
            served = sum(int(p.get("servedCount") or 0) for p in lane_playbooks)
            recall = stats.get(lane) or {}
            lanes[lane] = {
                "resolutionsCaptured": len(rows),
                "reopened": reopened,
                "reopenRate": round(reopened / len(rows), 3) if rows else None,
                "medianHoursToClose": hours[len(hours) // 2] if hours else None,
                "playbooks": {
                    state: sum(1 for p in lane_playbooks if p.get("state") == state)
                    for state in ("canary", "active", "rolled_back", "stale", "archived")
                },
                "playbookServes": served,
                "recalls": int(recall.get("recalls") or 0),
                "recallsWithKb": int(recall.get("withKb") or 0),
                "recallsWithPlaybook": int(recall.get("withPlaybook") or 0),
                "recallsWithResolution": int(recall.get("withResolution") or 0),
            }
        out["lanes"] = lanes
        return out

    # -- capture ------------------------------------------------------------

    def capture_closed(self, ticket_docs: Iterable[Mapping[str, Any]]) -> int:
        """Persist one resolution per newly closed ticket that was investigated."""

        if not self._learning:
            return 0
        captured = 0
        for doc in ticket_docs:
            try:
                captured += 1 if self._capture_one(doc) else 0
            except Exception:  # pragma: no cover - fail-safe
                continue
        return captured

    def _capture_one(self, doc: Mapping[str, Any]) -> bool:
        ticket_id = str(doc.get("id") or doc.get("number") or "").strip()
        result = str(doc.get("reconResult") or "").strip()
        state = str(doc.get("reconState") or "").strip().lower()
        if not ticket_id or not result or state not in {"completed", "needs_attention"}:
            return False
        existing = self._store.doc_get(RESOLUTIONS, ticket_id)  # type: ignore[union-attr]
        fingerprint = str(doc.get("reconFingerprint") or "")
        if existing and existing.get("fingerprint") == fingerprint and existing.get("status") == "closed":
            return False
        scrub = [doc.get("account"), doc.get("accountName"), doc.get("contact"), doc.get("openedBy"), doc.get("owner")]
        digest = build_digest(result, scrub=[str(v) for v in scrub if v])
        if not digest:
            return False
        playbook_ids = [str(v) for v in (doc.get("reconPlaybookIds") or []) if str(v)]
        reopen_count = int((existing or {}).get("reopenCount") or 0)
        closed_at = str(doc.get("closedAt") or doc.get("closed_at") or _iso())
        opened = _parse(doc.get("createdAt"))
        closed = _parse(closed_at)
        hours_to_close = (
            round((closed - opened).total_seconds() / 3600, 1) if opened and closed and closed >= opened else None
        )
        self._store.doc_put(  # type: ignore[union-attr]
            RESOLUTIONS,
            ticket_id,
            {
                "ticketId": ticket_id,
                "ticketNumber": str(doc.get("number") or ticket_id),
                "lane": _lane(doc),
                "recordType": str(doc.get("recordType") or ""),
                "issueKey": issue_key(doc),
                "mainIssue": redact(str(doc.get("mainIssue") or ""))[:160],
                "technicalIssue": redact(str(doc.get("technicalIssue") or ""))[:160],
                "digest": digest,
                "fingerprint": fingerprint,
                "playbookIds": playbook_ids,
                "status": "closed",
                "reopenCount": reopen_count,
                "closedAt": closed_at,
                "hoursToClose": hours_to_close,
                "capturedAt": _iso(),
            },
        )
        for playbook_id in playbook_ids:
            playbook = self._store.doc_get(PLAYBOOKS, playbook_id)  # type: ignore[union-attr]
            if playbook:
                self._store.doc_put(  # type: ignore[union-attr]
                    PLAYBOOKS,
                    playbook_id,
                    {"cleanCloses": int(playbook.get("cleanCloses") or 0) + 1},
                )
        return True

    # -- reopen -> rollback -------------------------------------------------

    def note_reopened(self, open_ticket_ids: Iterable[str]) -> int:
        """A previously captured ticket is open again: unverify it and strike its playbooks."""

        if not self._learning:
            return 0
        reopened = 0
        for ticket_id in {str(v).strip() for v in open_ticket_ids if str(v or "").strip()}:
            try:
                record = self._store.doc_get(RESOLUTIONS, ticket_id)  # type: ignore[union-attr]
                if not record or record.get("status") != "closed":
                    continue
                self._store.doc_put(  # type: ignore[union-attr]
                    RESOLUTIONS,
                    ticket_id,
                    {
                        "status": "reopened",
                        "reopenCount": int(record.get("reopenCount") or 0) + 1,
                        "reopenedAt": _iso(),
                    },
                )
                reopened += 1
                for playbook_id in record.get("playbookIds") or []:
                    self._strike(str(playbook_id))
            except Exception:  # pragma: no cover - fail-safe
                continue
        return reopened

    def _strike(self, playbook_id: str) -> None:
        playbook = self._store.doc_get(PLAYBOOKS, playbook_id)  # type: ignore[union-attr]
        if not playbook:
            return
        strikes = int(playbook.get("strikes") or 0) + 1
        state = str(playbook.get("state") or "")
        threshold = 1 if state == "canary" else 2
        update: dict[str, Any] = {"strikes": strikes}
        if state in LIVE_STATES and strikes >= threshold:
            update.update(
                {
                    "state": "rolled_back",
                    "rolledBackAt": _iso(),
                    "rolledBackSupport": int(playbook.get("supportCount") or 0),
                }
            )
        self._store.doc_put(PLAYBOOKS, playbook_id, update)  # type: ignore[union-attr]

    # -- playbooks ----------------------------------------------------------

    def refresh_playbooks(self) -> dict[str, int]:
        """Draft, update, and promote playbooks from verified resolutions."""

        summary = {"drafted": 0, "updated": 0, "promoted": 0}
        if not self._learning:
            return summary
        try:
            return self._refresh_playbooks(summary)
        except Exception:  # pragma: no cover - fail-safe
            return summary

    def _refresh_playbooks(self, summary: dict[str, int]) -> dict[str, int]:
        clusters: dict[str, list[dict[str, Any]]] = {}
        for doc in self._store.doc_list(RESOLUTIONS, limit=1000):  # type: ignore[union-attr]
            if doc.get("status") == "closed" and doc.get("issueKey"):
                clusters.setdefault(str(doc["issueKey"]), []).append(doc)
        for key, members in clusters.items():
            if len({str(m.get("ticketId")) for m in members}) < MIN_SUPPORT:
                continue
            guidance = build_guidance([str(m.get("digest") or "") for m in members])
            if not guidance:
                continue
            playbook_id = _doc_id(key)
            support = len(members)
            existing = self._store.doc_get(PLAYBOOKS, playbook_id)  # type: ignore[union-attr]
            if not existing:
                self._store.doc_put(  # type: ignore[union-attr]
                    PLAYBOOKS,
                    playbook_id,
                    {
                        "issueKey": key,
                        "lane": key.split("|", 1)[0],
                        "guidance": guidance,
                        "state": "canary",
                        "readOnly": True,
                        "supportCount": support,
                        "servedCount": 0,
                        "cleanCloses": 0,
                        "strikes": 0,
                        "createdAt": _iso(),
                        "updatedAt": _iso(),
                    },
                )
                summary["drafted"] += 1
                continue
            state = str(existing.get("state") or "")
            update: dict[str, Any] = {"supportCount": support, "updatedAt": _iso(), "readOnly": True}
            if state == "rolled_back":
                # Rolled-back guidance returns only after real new evidence.
                if support >= int(existing.get("rolledBackSupport") or 0) + MIN_SUPPORT:
                    update.update({"guidance": guidance, "state": "canary", "strikes": 0, "cleanCloses": 0})
                    summary["updated"] += 1
                else:
                    continue
            elif state in {"stale", "archived"}:
                if support > int(existing.get("supportCount") or 0):
                    update.update({"guidance": guidance, "state": "canary", "lastServedAt": ""})
                    summary["updated"] += 1
                else:
                    continue
            else:
                if guidance != existing.get("guidance"):
                    update["guidance"] = guidance
                    summary["updated"] += 1
                if (
                    state == "canary"
                    and int(existing.get("cleanCloses") or 0) >= PROMOTE_CLEAN_CLOSES
                    and int(existing.get("strikes") or 0) == 0
                ):
                    update["state"] = "active"
                    update["promotedAt"] = _iso()
                    summary["promoted"] += 1
            self._store.doc_put(PLAYBOOKS, playbook_id, update)  # type: ignore[union-attr]
        return summary

    def apply_lifecycle(self, *, now: datetime | None = None) -> dict[str, int]:
        """Curator-style pure time transitions: live -> stale (30d) -> archived (90d)."""

        summary = {"stale": 0, "archived": 0}
        if not self._learning:
            return summary
        moment = now or _now()
        try:
            for doc in self._store.doc_list(PLAYBOOKS, limit=500):  # type: ignore[union-attr]
                state = str(doc.get("state") or "")
                if state not in LIVE_STATES and state != "stale":
                    continue
                anchor = _parse(doc.get("lastServedAt")) or _parse(doc.get("updatedAt")) or _parse(doc.get("createdAt"))
                if anchor is None:
                    continue
                idle = moment - anchor
                if idle > timedelta(days=ARCHIVE_AFTER_DAYS) and state in LIVE_STATES | {"stale"}:
                    self._store.doc_put(PLAYBOOKS, str(doc["id"]), {"state": "archived"})  # type: ignore[union-attr]
                    summary["archived"] += 1
                elif idle > timedelta(days=STALE_AFTER_DAYS) and state in LIVE_STATES:
                    self._store.doc_put(PLAYBOOKS, str(doc["id"]), {"state": "stale"})  # type: ignore[union-attr]
                    summary["stale"] += 1
        except Exception:  # pragma: no cover - fail-safe
            pass
        return summary
