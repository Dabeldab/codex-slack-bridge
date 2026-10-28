from __future__ import annotations

import argparse
import base64
import html
import json
import os
import re
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

from .desktop_knowledge_ingest import ingest_source


DEFAULT_BASE_URL = "https://api.zoom.us/v2"
LANE_ENV = {
    "nova_wave": "ZOOM_KB_NOVA_WAVE_IDS",
    "nova_classic": "ZOOM_KB_NOVA_CLASSIC_IDS",
    "general": "ZOOM_KB_GENERAL_IDS",
    "billing": "ZOOM_KB_BILLING_IDS",
}
LANE_LABELS = {
    "nova_wave": "Nova Wave",
    "nova_classic": "Nova Classic",
    "general": "General",
    "billing": "Billing",
}


def main() -> None:
    args = parse_args()
    load_env_files([Path("config/ops.env"), Path(".env")])
    if args.exchange_oauth_code:
        payload = exchange_zoom_oauth_code(args.exchange_oauth_code, args.oauth_redirect_uri)
        if not payload.get("refresh_token"):
            raise SystemExit("Zoom OAuth code exchange did not return a refresh token.")
        persist_env_value(Path("config/ops.env"), "ZOOM_OAUTH_REFRESH_TOKEN", str(payload["refresh_token"]))
        print(json.dumps({"oauth": "refresh_token_saved", "env_file": str(Path("config/ops.env").resolve())}, indent=2))
        return

    kb_map = configured_kbs()
    if not any(kb_map.values()):
        raise SystemExit("No Zoom KB IDs configured. Set ZOOM_KB_NOVA_WAVE_IDS, ZOOM_KB_NOVA_CLASSIC_IDS, ZOOM_KB_GENERAL_IDS, or ZOOM_KB_BILLING_IDS.")

    token = get_zoom_token()
    cache_summary = sync_zoom_kbs(token, kb_map, Path(args.output), include_samples=args.include_samples)
    index_summary = ingest_source(
        source=Path(args.output),
        memory_path=Path(args.memory),
        agent=args.agent,
        collection=args.collection,
        tags=[tag.strip() for tag in args.tags.split(",") if tag.strip()],
        importance=args.importance,
        chunk_words=args.chunk_words,
        overlap_words=args.overlap_words,
        replace=True,
    )
    print(json.dumps({"zoom_sync": cache_summary, "desktop_vector_memory": index_summary}, indent=2, ensure_ascii=False))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pull Zoom AI Studio / Virtual Agent KB articles and index them into Agent Chat desktop vector memory.")
    parser.add_argument("--output", default="knowledge_sources/zoom_kb")
    parser.add_argument("--memory", default="data/desktop_chat/memory_vectors.json")
    parser.add_argument("--agent", default="global")
    parser.add_argument("--collection", default="zoom_kb")
    parser.add_argument("--tags", default="nova,zoom,kb")
    parser.add_argument("--importance", type=float, default=2.0)
    parser.add_argument("--chunk-words", type=int, default=700)
    parser.add_argument("--overlap-words", type=int, default=120)
    parser.add_argument("--include-samples", action="store_true", help="Include IDs listed in ZOOM_KB_SAMPLE_IDS when syncing General KB.")
    parser.add_argument("--exchange-oauth-code", default="", help="Exchange a one-time General OAuth code and save ZOOM_OAUTH_REFRESH_TOKEN.")
    parser.add_argument("--oauth-redirect-uri", default="", help="Redirect URI used for --exchange-oauth-code. Defaults to ZOOM_OAUTH_REDIRECT_URI.")
    return parser.parse_args()


def load_env_files(paths: list[Path]) -> None:
    for path in paths:
        if not path.exists():
            continue
        for raw_line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def configured_kbs() -> dict[str, list[str]]:
    by_lane = {lane: csv_ids(os.getenv(env_name, "")) for lane, env_name in LANE_ENV.items()}
    sample_ids = csv_ids(os.getenv("ZOOM_KB_SAMPLE_IDS", ""))
    if sample_ids:
        by_lane.setdefault("sample", sample_ids)
    return by_lane


def csv_ids(value: str) -> list[str]:
    return [item.strip() for item in re.split(r"[,;\s]+", value or "") if item.strip()]


_ZOOM_REFRESH_THREAD_LOCK = threading.Lock()


def get_zoom_token() -> str:
    state_path = _zoom_oauth_state_path()
    refresh_token = _read_env_value(state_path, "ZOOM_OAUTH_REFRESH_TOKEN")
    if not refresh_token:
        refresh_token = os.getenv("ZOOM_OAUTH_REFRESH_TOKEN", "").strip()
    if refresh_token:
        return token_from_payload(get_zoom_oauth_payload())
    return get_zoom_s2s_token()


def get_zoom_oauth_payload() -> dict[str, Any]:
    """Refresh General OAuth under one cross-process state lock.

    Zoom rotates refresh tokens. Every cloud consumer must therefore read and
    persist the same state file while holding the same lock.
    """

    state_path = _zoom_oauth_state_path()
    refresh_token = _read_env_value(state_path, "ZOOM_OAUTH_REFRESH_TOKEN")
    if not refresh_token:
        refresh_token = os.getenv("ZOOM_OAUTH_REFRESH_TOKEN", "").strip()
    if not refresh_token:
        raise RuntimeError("Zoom OAuth refresh token is not configured.")
    with _zoom_oauth_refresh_lock(state_path):
        # Re-read after acquiring the cross-process lock. A concurrent process
        # may have already rotated and persisted a newer refresh token.
        current = _read_env_value(state_path, "ZOOM_OAUTH_REFRESH_TOKEN") or refresh_token
        try:
            return refresh_zoom_oauth_payload(current)
        except RuntimeError as exc:
            # A deliberate OAuth reauthorization replaces the token pinned in
            # Secret Manager, but the durable shared state can still contain
            # the now-invalid token from the prior grant. Fall back exactly
            # once only for Zoom's invalid-refresh response and only when the
            # pinned token is different. A successful retry rotates and
            # persists the new shared state for every broker consumer.
            pinned = os.getenv("ZOOM_OAUTH_REFRESH_TOKEN", "").strip()
            if (
                str(exc) != "Zoom OAuth token request failed with HTTP 400"
                or not pinned
                or pinned == current
            ):
                raise
            payload = refresh_zoom_oauth_payload(pinned)
            latest = str(payload.get("refresh_token") or pinned).strip()
            if latest:
                persist_env_value(state_path, "ZOOM_OAUTH_REFRESH_TOKEN", latest)
            return payload


def get_zoom_s2s_token() -> str:
    account_id = os.getenv("ZOOM_ACCOUNT_ID", "").strip()
    client_id = os.getenv("ZOOM_CLIENT_ID", "").strip()
    client_secret = os.getenv("ZOOM_CLIENT_SECRET", "").strip()
    if not account_id or not client_id or not client_secret:
        raise RuntimeError(
            "Zoom OAuth is not configured. Set ZOOM_OAUTH_CLIENT_ID, "
            "ZOOM_OAUTH_CLIENT_SECRET, and ZOOM_OAUTH_REFRESH_TOKEN for a General "
            "OAuth app, or set ZOOM_ACCOUNT_ID, ZOOM_CLIENT_ID, and "
            "ZOOM_CLIENT_SECRET for Server-to-Server OAuth."
        )

    payload = zoom_token_request(
        {"grant_type": "account_credentials", "account_id": account_id},
        client_id=client_id,
        client_secret=client_secret,
    )
    return token_from_payload(payload)


def refresh_zoom_oauth_token(refresh_token: str) -> str:
    return token_from_payload(refresh_zoom_oauth_payload(refresh_token))


def refresh_zoom_oauth_payload(refresh_token: str) -> dict[str, Any]:
    client_id, client_secret = zoom_oauth_client_credentials()
    payload = zoom_token_request(
        {"grant_type": "refresh_token", "refresh_token": refresh_token},
        client_id=client_id,
        client_secret=client_secret,
    )
    new_refresh_token = str(payload.get("refresh_token") or "").strip()
    if new_refresh_token and new_refresh_token != refresh_token:
        persist_env_value(_zoom_oauth_state_path(), "ZOOM_OAUTH_REFRESH_TOKEN", new_refresh_token)
    return payload


def exchange_zoom_oauth_code(code: str, redirect_uri: str = "") -> dict[str, Any]:
    client_id, client_secret = zoom_oauth_client_credentials()
    resolved_redirect_uri = (redirect_uri or os.getenv("ZOOM_OAUTH_REDIRECT_URI", "")).strip()
    if not resolved_redirect_uri:
        raise RuntimeError("Set ZOOM_OAUTH_REDIRECT_URI or pass --oauth-redirect-uri before exchanging a Zoom OAuth code.")
    return zoom_token_request(
        {
            "grant_type": "authorization_code",
            "code": code.strip(),
            "redirect_uri": resolved_redirect_uri,
        },
        client_id=client_id,
        client_secret=client_secret,
    )


def zoom_oauth_client_credentials() -> tuple[str, str]:
    client_id = (os.getenv("ZOOM_OAUTH_CLIENT_ID") or os.getenv("ZOOM_CLIENT_ID") or "").strip()
    client_secret = (os.getenv("ZOOM_OAUTH_CLIENT_SECRET") or os.getenv("ZOOM_CLIENT_SECRET") or "").strip()
    if not client_id or not client_secret:
        raise RuntimeError("Set ZOOM_OAUTH_CLIENT_ID and ZOOM_OAUTH_CLIENT_SECRET in config/ops.env or .env.")
    return client_id, client_secret


def zoom_token_request(form: dict[str, str], *, client_id: str, client_secret: str) -> dict[str, Any]:
    auth = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
    request = urllib.request.Request(
        "https://zoom.us/oauth/token",
        data=urllib.parse.urlencode(form).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Basic {auth}",
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # OAuth error bodies may echo credential material. The status code is
        # sufficient for the operator while keeping tokens out of agent output.
        raise RuntimeError(f"Zoom OAuth token request failed with HTTP {exc.code}") from exc
    return payload if isinstance(payload, dict) else {}


def token_from_payload(payload: dict[str, Any]) -> str:
    token = payload.get("access_token")
    if not token:
        raise RuntimeError("Zoom token response did not include access_token.")
    return str(token)


def persist_env_value(path: Path, key: str, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines() if path.exists() else []
    replacement = f"{key}={value}"
    for index, line in enumerate(lines):
        if line.strip().startswith(f"{key}="):
            lines[index] = replacement
            break
    else:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(replacement)
    payload = "\n".join(lines) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(prefix=".zoom-oauth-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_name, 0o660 if _zoom_oauth_state_is_shared() else 0o600)
        os.replace(temporary_name, path)
        temporary_name = ""
    finally:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)


def _zoom_oauth_state_path() -> Path:
    configured = os.getenv("ZOOM_OAUTH_STATE_PATH", "").strip()
    return Path(configured).expanduser().resolve() if configured else Path("config/ops.env").resolve()


class _zoom_oauth_refresh_lock:
    def __init__(self, state_path: Path) -> None:
        self.path = state_path.with_suffix(state_path.suffix + ".lock")
        self.descriptor = -1

    def __enter__(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        _ZOOM_REFRESH_THREAD_LOCK.acquire()
        try:
            mode = 0o660 if _zoom_oauth_state_is_shared() else 0o600
            self.descriptor = os.open(self.path, os.O_CREAT | os.O_RDWR, mode)
            try:
                os.chmod(self.path, mode)
            except PermissionError:
                # A different broker identity can own a correctly migrated
                # group-writable shared lock. Group members may open and flock
                # it but cannot chmod it; accept only when this process still
                # has the read/write access the lock requires.
                if not (os.access(self.path, os.R_OK) and os.access(self.path, os.W_OK)):
                    raise
            if os.name == "posix":
                import fcntl

                fcntl.flock(self.descriptor, fcntl.LOCK_EX)
        except Exception:
            _ZOOM_REFRESH_THREAD_LOCK.release()
            raise

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        try:
            if self.descriptor >= 0:
                if os.name == "posix":
                    import fcntl

                    fcntl.flock(self.descriptor, fcntl.LOCK_UN)
                os.close(self.descriptor)
                self.descriptor = -1
        finally:
            _ZOOM_REFRESH_THREAD_LOCK.release()


def _zoom_oauth_state_is_shared() -> bool:
    return os.getenv("ZOOM_OAUTH_SHARED_STATE", "").strip().lower() in {"1", "true", "yes", "on"}


def _read_env_value(path: Path, key: str) -> str:
    if not path.exists():
        return ""
    for raw_line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#") or "=" not in raw_line:
            continue
        name, value = raw_line.split("=", 1)
        if name.strip() != key:
            continue
        clean = value.strip()
        if len(clean) >= 2 and clean[0] == clean[-1] and clean[0] in {'"', "'"}:
            clean = clean[1:-1]
        return clean
    return ""


def sync_zoom_kbs(token: str, kb_map: dict[str, list[str]], output_root: Path, *, include_samples: bool = False) -> dict[str, Any]:
    output_root.mkdir(parents=True, exist_ok=True)
    fetched = 0
    errors: list[dict[str, str]] = []
    lanes: Counter[str] = Counter()
    for lane, kb_ids in kb_map.items():
        if lane == "sample" and not include_samples:
            continue
        target_lane = "general" if lane == "sample" else lane
        lane_dir = output_root / target_lane
        lane_dir.mkdir(parents=True, exist_ok=True)
        for kb_id in kb_ids:
            try:
                kb_articles = fetch_kb_articles(token, kb_id)
            except Exception as exc:
                errors.append({"kb_id": kb_id, "lane": target_lane, "error": safe_error(exc)})
                continue
            for article in kb_articles:
                article_id = article_id_from(article)
                if article_id:
                    try:
                        detail = zoom_get(token, f"/km/kbs/{kb_id}/articles/{article_id}")
                        article = merge_article(article, detail)
                    except Exception as exc:
                        errors.append({"kb_id": kb_id, "article_id": article_id, "lane": target_lane, "error": safe_error(exc)})
                title = article_title(article, fallback=article_id or kb_id)
                body = article_body(article)
                if len(re.findall(r"[A-Za-z0-9]+", body)) < 4:
                    continue
                file_path = lane_dir / f"{slug(title)}__{article_id or slug(kb_id)}.md"
                file_path.write_text(render_markdown(kb_id, article_id, title, target_lane, article, body), encoding="utf-8")
                fetched += 1
                lanes[target_lane] += 1
    return {
        "output": str(output_root.resolve()),
        "articles_cached": fetched,
        "lanes": {lane: lanes.get(lane, 0) for lane in ("nova_wave", "nova_classic", "general", "billing")},
        "errors": errors[:20],
    }


def fetch_kb_articles(token: str, kb_id: str) -> list[dict[str, Any]]:
    articles: list[dict[str, Any]] = []
    next_page_token = ""
    while True:
        params = {"page_size": "100", "include_contents": "true"}
        if next_page_token:
            params["next_page_token"] = next_page_token
        payload = zoom_get(token, f"/km/kbs/{kb_id}/articles", params)
        rows = extract_rows(payload)
        articles.extend(row for row in rows if isinstance(row, dict))
        next_page_token = str(payload.get("next_page_token") or payload.get("nextPageToken") or "").strip()
        if not next_page_token:
            break
    return articles


def zoom_get(token: str, path: str, params: dict[str, str] | None = None) -> dict[str, Any]:
    base = os.getenv("ZOOM_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    url = base + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            data = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        raise RuntimeError(f"Zoom API {path} failed with HTTP {exc.code}: {detail}") from exc
    if not data.strip():
        return {}
    payload = json.loads(data)
    return payload if isinstance(payload, dict) else {"data": payload}


def extract_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("articles", "items", "results", "data", "records"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            nested = extract_rows(value)
            if nested:
                return nested
    return []


def merge_article(summary: dict[str, Any], detail: dict[str, Any]) -> dict[str, Any]:
    merged = dict(summary)
    for key, value in detail.items():
        if key not in merged or not merged.get(key):
            merged[key] = value
    return merged


def article_id_from(article: dict[str, Any]) -> str:
    for key in ("article_id", "articleId", "id", "uuid"):
        value = article.get(key)
        if value:
            return str(value)
    return ""


def article_title(article: dict[str, Any], *, fallback: str) -> str:
    for key in ("title", "name", "question", "heading"):
        value = article.get(key)
        if isinstance(value, str) and value.strip():
            return clean(value)
    return fallback


def article_body(article: dict[str, Any]) -> str:
    preferred: list[str] = []
    for key in ("body", "content", "answer", "text", "plain_text", "html", "markdown", "description"):
        value = article.get(key)
        if isinstance(value, str) and value.strip():
            preferred.append(clean(value))
    if preferred:
        return "\n\n".join(preferred)
    pieces: list[str] = []
    flatten(article, pieces, prefix="")
    return clean("\n".join(pieces))


def flatten(value: Any, pieces: list[str], *, prefix: str) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key.lower() in {"id", "uuid", "article_id", "articleid", "created_at", "updated_at"}:
                continue
            flatten(child, pieces, prefix=f"{prefix}{key}: " if len(prefix) < 80 else prefix)
    elif isinstance(value, list):
        for item in value:
            flatten(item, pieces, prefix=prefix)
    elif isinstance(value, (str, int, float)) and str(value).strip():
        pieces.append(f"{prefix}{value}")


def render_markdown(kb_id: str, article_id: str, title: str, lane: str, article: dict[str, Any], body: str) -> str:
    return (
        f"# {title}\n\n"
        f"Source: Zoom Knowledge Library\n"
        f"KB ID: {kb_id}\n"
        f"Article ID: {article_id or '(unknown)'}\n"
        f"Product lane: {LANE_LABELS.get(lane, 'General')}\n"
        f"Source URL: https://novapointofsale.zoom.us/ai-studio/kb/kbs/{kb_id}\n"
        f"Updated: {article.get('updated_at') or article.get('updatedAt') or article.get('modified_at') or ''}\n\n"
        f"{body.strip()}\n"
    )


def clean(value: Any) -> str:
    text = html.unescape(str(value or "")).replace("\xa0", " ")
    text = re.sub(r"(?is)<script.*?</script>|<style.*?</style>", " ", text)
    text = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</h[1-6]>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:90] or "article"


def safe_error(exc: Exception) -> str:
    return re.sub(r"(?i)(access_token|client_secret|authorization)[^\s,;]+", "[redacted]", str(exc))[:500]


if __name__ == "__main__":
    main()
