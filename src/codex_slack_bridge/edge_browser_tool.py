from __future__ import annotations

# AgentChat/coding_agent 2026-07-09T11:45:00-04:00: make Edge CDP browser control non-disruptive by default.

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_PORT = 9223
DEFAULT_PROFILE = Path("data") / "edge_agent_profile"
DEFAULT_PROFILE_MODE = "main"
DEFAULT_PROFILE_DISPLAY_NAME = "Profile 1"
DEFAULT_PROFILE_DIRECTORY = ""
DEFAULT_URL = "https://novapointofsale.zoom.us/ai-studio/virtual-agent"


class EdgeToolError(RuntimeError):
    pass


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "start":
            return cmd_start(args)
        if args.command == "doctor":
            return cmd_doctor(args)
        if args.command == "status":
            return cmd_status(args)
        if args.command == "tabs":
            return cmd_tabs(args)
        if args.command == "open":
            return cmd_open(args)
        if args.command == "snapshot":
            return cmd_snapshot(args)
        if args.command == "screenshot":
            return cmd_screenshot(args)
        if args.command == "click":
            return cmd_click(args)
        if args.command == "fill":
            return cmd_fill(args)
        if args.command == "press":
            return cmd_press(args)
        parser.print_help()
        return 2
    except EdgeToolError as exc:
        print_json({"ok": False, "error": str(exc)}, args)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Control a reusable Microsoft Edge CDP session.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--profile-mode",
        choices=("main", "agent"),
        default=os.getenv("EDGE_PROFILE_MODE", DEFAULT_PROFILE_MODE),
        help="Use the real Edge profile for logged-in admin work, or an isolated agent profile.",
    )
    parser.add_argument(
        "--profile-display-name",
        default=os.getenv("EDGE_PROFILE_DISPLAY_NAME", DEFAULT_PROFILE_DISPLAY_NAME),
        help="Displayed Edge profile name to use when --profile-mode main is selected.",
    )
    parser.add_argument(
        "--profile-directory",
        default=os.getenv("EDGE_PROFILE_DIRECTORY", DEFAULT_PROFILE_DIRECTORY),
        help="Optional internal Edge profile directory override. Leave unset so Agent Chat resolves displayed Profile 1 safely.",
    )
    parser.add_argument(
        "--profile-dir",
        default=str(DEFAULT_PROFILE),
        help="Isolated profile path used only when --profile-mode agent is selected.",
    )
    parser.add_argument("--json-indent", type=int, default=2)
    sub = parser.add_subparsers(dest="command")

    start = sub.add_parser("start", help="Launch Edge with remote debugging if it is not already running.")
    start.add_argument("--url", default=DEFAULT_URL)
    start.add_argument(
        "--force-restart",
        action="store_true",
        help="Close running Edge processes before launching. Use only after explicit user approval.",
    )
    start.add_argument(
        "--confirm-close-browser",
        action="store_true",
        help="Required with --force-restart unless AGENTCHAT_ALLOW_BROWSER_FORCE_RESTART=1 is set.",
    )

    sub.add_parser("doctor", help="Explain whether Edge can be controlled or needs user-approved restart.")
    sub.add_parser("status", help="Check whether the Edge CDP endpoint is reachable.")
    tabs = sub.add_parser("tabs", help="List open tabs in the Edge CDP session.")
    tabs.add_argument("--all", action="store_true", help="Include iframes, service workers, and background pages.")

    open_page = sub.add_parser("open", help="Open a URL in a new tab by default.")
    open_page.add_argument("url")
    open_page.add_argument("--new-tab", action="store_true", help="Deprecated compatibility flag; new tab is already the default.")
    open_page.add_argument("--same-tab", action="store_true", help="Navigate an existing matched tab instead of opening a new tab. Avoid unless explicitly requested.")
    open_page.add_argument("--match", help="Existing tab title or URL fragment to use with --same-tab.")

    snapshot = sub.add_parser("snapshot", help="Return page title/url/text and clickable/input candidates.")
    snapshot.add_argument("--match", help="Use the first tab whose title or URL contains this text.")
    snapshot.add_argument("--max-text", type=int, default=2500)
    snapshot.add_argument("--max-elements", type=int, default=60)

    screenshot = sub.add_parser("screenshot", help="Save a screenshot of a tab.")
    screenshot.add_argument("--match", help="Use the first tab whose title or URL contains this text.")
    screenshot.add_argument("--output", required=True)
    screenshot.add_argument("--full-page", action="store_true")

    click = sub.add_parser("click", help="Click by CSS selector or visible text.")
    click.add_argument("--match", help="Use the first tab whose title or URL contains this text.")
    click.add_argument("--selector")
    click.add_argument("--text")
    click.add_argument("--timeout-ms", type=int, default=8000)

    fill = sub.add_parser("fill", help="Fill an input by CSS selector or label.")
    fill.add_argument("--match", help="Use the first tab whose title or URL contains this text.")
    fill.add_argument("--selector")
    fill.add_argument("--label")
    fill.add_argument("--value", required=True)
    fill.add_argument("--timeout-ms", type=int, default=8000)

    press = sub.add_parser("press", help="Press a keyboard key in a tab.")
    press.add_argument("--match", help="Use the first tab whose title or URL contains this text.")
    press.add_argument("--key", required=True)
    press.add_argument("--timeout-ms", type=int, default=8000)
    return parser


def cmd_start(args: argparse.Namespace) -> int:
    closed_processes = 0
    if args.force_restart:
        ensure_restart_approved(args)
        closed_processes = stop_edge_processes()
        time.sleep(1)
    started = start_edge_if_needed(args, args.url)
    print_json(
        {
            "ok": True,
            "started": started,
            "closed_processes": closed_processes,
            "cdp": f"http://127.0.0.1:{args.port}",
            "profile": edge_profile_description(args),
            "note": edge_start_note(args),
        },
        args,
    )
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    cdp_reachable = port_open(args.port)
    edge_running = edge_process_count()
    profile: dict[str, str] | dict[str, Any]
    try:
        profile = edge_profile_description(args)
    except EdgeToolError as exc:
        profile = {"error": str(exc)}

    if cdp_reachable:
        recommendation = "CDP is reachable. Continue with tabs, snapshot, screenshot, click, fill, or press."
        approval_required = False
    elif str(args.profile_mode).lower() == "main" and edge_running > 0:
        recommendation = (
            "Displayed Profile 1 appears to be running without CDP. Do not close or restart the user's browser. "
            "Use a configured browser connector/already-debuggable session if available, or ask the user before any restart. "
            "A force restart requires --confirm-close-browser or AGENTCHAT_ALLOW_BROWSER_FORCE_RESTART=1."
        )
        approval_required = True
    elif str(args.profile_mode).lower() == "main":
        recommendation = "Edge is not running on this port. Run start with displayed Profile 1."
        approval_required = False
    else:
        recommendation = "Use the isolated agent profile for non-auth browser work. Run start with --profile-mode agent."
        approval_required = False

    print_json(
        {
            "ok": True,
            "cdp_reachable": cdp_reachable,
            "edge_processes": edge_running,
            "cdp": f"http://127.0.0.1:{args.port}",
            "profile": profile,
            "approval_required": approval_required,
            "recommendation": recommendation,
        },
        args,
    )
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    if not port_open(args.port):
        print_json({"ok": False, "reachable": False, "cdp": f"http://127.0.0.1:{args.port}"}, args)
        return 1
    data = cdp_json(args.port, "/json/version")
    print_json({"ok": True, "reachable": True, "cdp": f"http://127.0.0.1:{args.port}", "version": data}, args)
    return 0


def cmd_tabs(args: argparse.Namespace) -> int:
    ensure_edge(args)
    tabs = cdp_json(args.port, "/json/list")
    if not args.all:
        tabs = [tab for tab in tabs if tab.get("type") == "page"]
    print_json({"ok": True, "tabs": tabs}, args)
    return 0


def cmd_open(args: argparse.Namespace) -> int:
    ensure_edge(args)
    use_same_tab = bool(getattr(args, "same_tab", False))
    with connected_page(args, match=(args.match if use_same_tab else None), new_tab=(not use_same_tab)) as page:
        page.goto(args.url, wait_until="domcontentloaded", timeout=45000)
        print_json({"ok": True, "title": page.title(), "url": page.url, "opened_new_tab": not use_same_tab}, args)
    return 0


def cmd_snapshot(args: argparse.Namespace) -> int:
    ensure_edge(args)
    with connected_page(args, match=args.match, new_tab=False) as page:
        page.wait_for_load_state("domcontentloaded", timeout=10000)
        text = page.locator("body").inner_text(timeout=10000)
        elements = page.locator("a,button,input,textarea,select,[role=button],[role=menuitem]").evaluate_all(
            """
            (nodes) => nodes.slice(0, 200).map((node) => ({
              tag: node.tagName.toLowerCase(),
              role: node.getAttribute('role') || '',
              text: (node.innerText || node.value || node.getAttribute('aria-label') || node.getAttribute('title') || '').trim().slice(0, 120),
              id: node.id || '',
              name: node.getAttribute('name') || '',
              type: node.getAttribute('type') || '',
              placeholder: node.getAttribute('placeholder') || '',
              disabled: !!node.disabled || node.getAttribute('aria-disabled') === 'true',
              hidden: node.getAttribute('type') === 'hidden' || node.offsetParent === null,
            })).filter((item) => !item.hidden && (item.text || item.id || item.name || item.placeholder))
            """
        )
        print_json(
            {
                "ok": True,
                "title": page.title(),
                "url": page.url,
                "text": text[: max(0, args.max_text)],
                "elements": elements[: max(1, args.max_elements)],
            },
            args,
        )
    return 0


def cmd_screenshot(args: argparse.Namespace) -> int:
    ensure_edge(args)
    output = Path(args.output).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    with connected_page(args, match=args.match, new_tab=False) as page:
        page.screenshot(path=str(output), full_page=bool(args.full_page))
        print_json({"ok": True, "output": str(output.resolve()), "title": page.title(), "url": page.url}, args)
    return 0


def cmd_click(args: argparse.Namespace) -> int:
    if not args.selector and not args.text:
        raise EdgeToolError("click requires --selector or --text")
    ensure_edge(args)
    with connected_page(args, match=args.match, new_tab=False) as page:
        if args.selector:
            page.locator(args.selector).first.click(timeout=args.timeout_ms)
        else:
            page.get_by_text(args.text, exact=False).first.click(timeout=args.timeout_ms)
        print_json({"ok": True, "title": page.title(), "url": page.url, "input_method": "cdp_no_physical_mouse"}, args)
    return 0


def cmd_fill(args: argparse.Namespace) -> int:
    if not args.selector and not args.label:
        raise EdgeToolError("fill requires --selector or --label")
    ensure_edge(args)
    with connected_page(args, match=args.match, new_tab=False) as page:
        if args.selector:
            page.locator(args.selector).first.fill(args.value, timeout=args.timeout_ms)
        else:
            page.get_by_label(args.label, exact=False).first.fill(args.value, timeout=args.timeout_ms)
        print_json({"ok": True, "title": page.title(), "url": page.url}, args)
    return 0


def cmd_press(args: argparse.Namespace) -> int:
    ensure_edge(args)
    with connected_page(args, match=args.match, new_tab=False) as page:
        page.keyboard.press(args.key)
        print_json({"ok": True, "title": page.title(), "url": page.url}, args)
    return 0


class connected_page:
    def __init__(self, args: argparse.Namespace, *, match: str | None, new_tab: bool) -> None:
        self.args = args
        self.match = match
        self.new_tab = new_tab
        self.playwright: Any = None
        self.browser: Any = None
        self.page: Any = None

    def __enter__(self) -> Any:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise EdgeToolError(
                "Python package 'playwright' is not installed. Run scripts/install-desktop-tools.ps1."
            ) from exc
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{self.args.port}")
        context = self.browser.contexts[0] if self.browser.contexts else self.browser.new_context()
        if self.new_tab:
            self.page = context.new_page()
            return self.page
        pages = [page for c in self.browser.contexts for page in c.pages]
        if not pages:
            self.page = context.new_page()
            return self.page
        if self.match:
            needle = self.match.lower()
            for page in reversed(pages):
                title = safe_title(page).lower()
                if needle in page.url.lower() or needle in title:
                    self.page = page
                    return self.page
            raise EdgeToolError(f"No Edge tab matched: {self.match}")
        self.page = pages[-1]
        return self.page

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self.playwright is not None:
            self.playwright.stop()


def safe_title(page: Any) -> str:
    try:
        return str(page.title())
    except Exception:
        return ""


def ensure_edge(args: argparse.Namespace) -> None:
    if not port_open(args.port):
        start_edge_if_needed(args, getattr(args, "url", DEFAULT_URL))


def start_edge_if_needed(args: argparse.Namespace, url: str) -> bool:
    if port_open(args.port):
        return False
    edge = edge_executable()
    command = edge_command(edge, args, url)
    subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    wait_for_port(args.port, timeout=12, profile_mode=str(args.profile_mode))
    return True


def edge_command(edge: Path, args: argparse.Namespace, url: str) -> list[str]:
    command = [
        str(edge),
        f"--remote-debugging-port={args.port}",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    if str(args.profile_mode).lower() == "main":
        profile_directory = resolve_main_profile_directory(args)
        if profile_directory:
            command.append(f"--profile-directory={profile_directory}")
        command.extend(["--new-window", url])
        return command

    profile = profile_dir(args)
    profile.mkdir(parents=True, exist_ok=True)
    command.extend([f"--user-data-dir={profile}", url])
    return command


def edge_profile_description(args: argparse.Namespace) -> dict[str, str]:
    if str(args.profile_mode).lower() == "main":
        profile_directory = resolve_main_profile_directory(args)
        return {
            "mode": "main",
            "profile_display_name": str(args.profile_display_name or DEFAULT_PROFILE_DISPLAY_NAME),
            "profile_directory": profile_directory,
        }
    return {"mode": "agent", "profile_dir": str(profile_dir(args))}


def edge_start_note(args: argparse.Namespace) -> str:
    if str(args.profile_mode).lower() == "main":
        display_name = str(args.profile_display_name or DEFAULT_PROFILE_DISPLAY_NAME)
        return (
            f"Uses displayed Edge {display_name} so existing Zoom/Google SSO cookies are available. "
            "Edge may store that visible profile in the internal Default directory on this machine. "
            "If CDP is not reachable because Edge was already open without debugging, do not close or restart Edge by default. "
            "Use an available connector/debuggable session, or ask the user before any restart."
        )
    return "Uses the isolated agent Edge profile. Use Profile 1 for Zoom admin tasks unless the user asks otherwise."


def resolve_main_profile_directory(args: argparse.Namespace) -> str:
    requested_display_name = str(args.profile_display_name or DEFAULT_PROFILE_DISPLAY_NAME).strip()
    requested_directory = str(args.profile_directory or "").strip()
    if requested_directory:
        display_for_directory = edge_profile_display_name_for_directory(requested_directory)
        if (
            not requested_display_name
            or not display_for_directory
            or display_for_directory.casefold() == requested_display_name.casefold()
        ):
            return requested_directory
        display_directory = edge_profile_directory_for_display_name(requested_display_name)
        if display_directory:
            return display_directory
        return requested_directory
    display_directory = edge_profile_directory_for_display_name(requested_display_name)
    if display_directory:
        return display_directory
    raise EdgeToolError(
        f"Could not find displayed Edge profile '{requested_display_name}'. "
        "Pass --profile-directory with a verified internal Edge profile directory only if the user explicitly approves it."
    )


def edge_profile_display_name_for_directory(directory: str) -> str:
    try:
        profile = edge_profile_info_cache().get(directory)
    except EdgeToolError:
        return ""
    if not isinstance(profile, dict):
        return ""
    return str(profile.get("name") or "").strip()


def edge_profile_directory_for_display_name(display_name: str) -> str:
    if not display_name:
        return ""
    try:
        info_cache = edge_profile_info_cache()
    except EdgeToolError:
        return ""
    for directory, profile in info_cache.items():
        if not isinstance(profile, dict):
            continue
        if str(profile.get("name") or "").strip().casefold() == display_name.casefold():
            return str(directory)
    return ""


def edge_profile_info_cache() -> dict[str, Any]:
    local_state = edge_user_data_dir() / "Local State"
    if not local_state.exists():
        raise EdgeToolError(f"Edge profile metadata was not found at {local_state}.")
    try:
        data = json.loads(local_state.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EdgeToolError(f"Could not read Edge profile metadata at {local_state}: {exc}") from exc
    info_cache = data.get("profile", {}).get("info_cache", {})
    if not isinstance(info_cache, dict):
        raise EdgeToolError("Edge profile metadata does not include a usable profile info cache.")
    return info_cache


def edge_user_data_dir() -> Path:
    override = os.getenv("EDGE_USER_DATA_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    local_app_data = os.getenv("LOCALAPPDATA", "").strip()
    if not local_app_data:
        raise EdgeToolError("LOCALAPPDATA is not set; cannot resolve Edge main profile metadata.")
    return Path(local_app_data) / "Microsoft" / "Edge" / "User Data"


def edge_executable() -> Path:
    override = os.getenv("EDGE_EXE", "").strip()
    candidates = [
        Path(override) if override else None,
        Path(os.getenv("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        Path(os.getenv("ProgramFiles", r"C:\Program Files")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
    ]
    for candidate in candidates:
        if candidate and candidate.exists():
            return candidate
    raise EdgeToolError("Microsoft Edge executable was not found. Set EDGE_EXE if it is installed elsewhere.")


def stop_edge_processes() -> int:
    if os.name != "nt":
        raise EdgeToolError("--force-restart is only implemented for Windows.")
    command = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        "$p=Get-Process msedge -ErrorAction SilentlyContinue; "
        "$count=($p | Measure-Object).Count; "
        "if ($p) { $p | Stop-Process -Force -ErrorAction Stop }; "
        "Write-Output $count",
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise EdgeToolError(f"Could not close Edge before restart: {completed.stderr.strip()}")
    output = completed.stdout.strip().splitlines()
    if not output:
        return 0
    try:
        return int(output[-1].strip())
    except ValueError:
        return 0


def ensure_restart_approved(args: argparse.Namespace) -> None:
    if bool(getattr(args, "confirm_close_browser", False)):
        return
    if os.getenv("AGENTCHAT_ALLOW_BROWSER_FORCE_RESTART", "").strip() in {"1", "true", "TRUE", "yes", "YES"}:
        return
    raise EdgeToolError(
        "--force-restart would close the user's Edge windows and is disabled by default. "
        "Use an existing browser connector/debuggable session, or get explicit user approval and pass "
        "--confirm-close-browser (or set AGENTCHAT_ALLOW_BROWSER_FORCE_RESTART=1 for that approved run)."
    )


def edge_process_count() -> int:
    if os.name != "nt":
        return 0
    command = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        "$p=Get-Process msedge -ErrorAction SilentlyContinue; "
        "($p | Measure-Object).Count",
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        return 0
    output = completed.stdout.strip().splitlines()
    if not output:
        return 0
    try:
        return int(output[-1].strip())
    except ValueError:
        return 0


def profile_dir(args: argparse.Namespace) -> Path:
    path = Path(str(args.profile_dir)).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.resolve()


def port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def wait_for_port(port: int, *, timeout: float, profile_mode: str) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if port_open(port):
            return
        time.sleep(0.2)
    hint = ""
    if profile_mode.lower() == "main":
        hint = (
            " If Microsoft Edge was already running, the remote debugging flag may have been ignored. "
            "Do not close or restart Edge by default. Use an existing browser connector/debuggable session, "
            "or ask the user before any restart; approved restarts require --force-restart --confirm-close-browser."
        )
    raise EdgeToolError(f"Edge did not open CDP port {port} within {timeout:.0f}s.{hint}")


def cdp_json(port: int, path: str) -> Any:
    url = f"http://127.0.0.1:{port}{path}"
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        raise EdgeToolError(f"Could not read Edge CDP endpoint {url}: {exc}") from exc


def print_json(value: dict[str, Any], args: argparse.Namespace) -> None:
    print(json.dumps(value, indent=args.json_indent, ensure_ascii=False))


if __name__ == "__main__":
    raise SystemExit(main())
