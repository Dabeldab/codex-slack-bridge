# Browser And Windows Control

<!-- AgentChat/coding_agent 2026-07-09T11:45:00-04:00 -->
<!-- AgentChat/coding_agent 2026-07-10T17:30:00-04:00 -->

Use browser or Windows GUI control only when the request explicitly needs
clicking, navigation, desktop inspection, a logged-in browser session, or a
native admin UI such as Zoom admin.

Preferred order:

First apply the global MCP/app -> native API/client -> trusted helper -> browser
order. The ranking below applies only after browser/UI work is genuinely needed.

1. Use a built-in browser/app connector or an already-debuggable browser session
   when available. This is the preferred route because it can operate tabs
   without closing the user's browser or controlling the physical mouse.
   Browser connector access can be session-scoped: verify it in the current
   agent thread before promising browser work. If another live thread appears
   to hold the connector, use the live owning thread when available or report
   the holder for a handoff; if the
   blocker is a stale Agent Chat runtime lock, clear it only after confirming
   the recorded owner process no longer exists.
2. Use the local Edge CDP tool with displayed `Profile 1` for Zoom AI Studio
   and other Nova Zoom admin UI work. The user is logged into displayed
   `Profile 1`; on this machine that visible profile is stored in Edge's
   internal `Default` directory, while internal `Profile 1` displays as the
   Profile 2 UI profile. Do not open displayed Profile 2 or an isolated profile for these tasks
   unless the user explicitly changes this rule.
3. Use Chrome automation when the current logged-in Chrome profile, cookies, or
   extensions matter and Chrome is confirmed controllable; only use Chrome
   `Profile 1`, never `Default`.
4. Use in-app browser automation for local pages, localhost verification,
   screenshots, and non-authenticated sites.
5. Use Windows GUI automation libraries only when browser automation is
   insufficient, the desktop session is unlocked and interactive, and the
   verified task specifically requires physical mouse/keyboard control.

Non-disruptive rules:

- Do not close, restart, or force-restart the user's browser unless the verified
  task asks for that exact action; then use the guarded route without a second approval.
- Do not navigate the user's active tab unless explicitly requested. Open a new
  tab by default.
- Do not use a separate Zoom browser profile for Nova admin work. If the only
  available browser is unauthenticated, report that and fix the authenticated
  Profile 1 connector/CDP path instead of asking the user to log into an
  isolated profile.
- CDP/Playwright clicks and fills are allowed because they do not move the
  physical mouse. Windows GUI automation that moves the real pointer is not
  allowed unless the verified task specifically requires it.
- If displayed Edge Profile 1 is already running without CDP, report that exact
  blocker. Do not use `--force-restart` as the default workaround.

Edge CDP non-disruptive command pattern, when browser UI is the verified route:

```powershell
powershell -ExecutionPolicy Bypass -File "C:/Users/redma/Workworkworkworkworkwork/codex-slack-bridge/scripts/start-edge-profile1-cdp.ps1" -Doctor
powershell -ExecutionPolicy Bypass -File "C:/Users/redma/Workworkworkworkworkwork/codex-slack-bridge/scripts/edge-browser-tool.ps1" --port 9223 --profile-mode main --profile-display-name "Profile 1" start --url "https://novapointofsale.zoom.us/ai-studio/virtual-agent"
powershell -ExecutionPolicy Bypass -File "C:/Users/redma/Workworkworkworkworkwork/codex-slack-bridge/scripts/edge-browser-tool.ps1" --port 9223 tabs
powershell -ExecutionPolicy Bypass -File "C:/Users/redma/Workworkworkworkworkwork/codex-slack-bridge/scripts/edge-browser-tool.ps1" --port 9223 open "https://novapointofsale.zoom.us/ai-studio/virtual-agent"
powershell -ExecutionPolicy Bypass -File "C:/Users/redma/Workworkworkworkworkwork/codex-slack-bridge/scripts/edge-browser-tool.ps1" --port 9223 snapshot --match zoom
powershell -ExecutionPolicy Bypass -File "C:/Users/redma/Workworkworkworkworkwork/codex-slack-bridge/scripts/edge-browser-tool.ps1" --port 9223 screenshot --match zoom --output "<agent-sandbox-or-handoff-path>"
```

The Edge tool defaults to `--profile-mode main` with displayed
`--profile-display-name "Profile 1"`, where the user is expected to be logged
into Google/Zoom. If CDP cannot attach because Edge was already running without
remote debugging, use `doctor` only to confirm the state. Do not switch to
displayed Profile 2, do not switch to an isolated profile, and do not guess a
different Zoom page. If a restart is necessary for the verified task, preserve
the session where possible and continue. Restarts must include the tool guard `--confirm-close-browser`
or wrapper switch `-ConfirmCloseBrowser`; otherwise the helper should refuse.
Continue from the same visible `Profile 1` account after the user approves.
Use `--profile-mode agent` only for isolated non-auth browser work.

If Zoom asks for login or MFA, report that exact blocker and ask the user to
complete it in the visible `Profile 1` window, then continue from the same tab.
Do not stop after one failed route; record what failed and try the next route
before reporting blocked.

Do not type passwords, recovery codes, payment details, API keys, or customer secrets into a page unless the user explicitly asks and the action is necessary. If a page shows sensitive data, summarize only the minimum needed and avoid copying secrets into Slack.

If the requested GUI task requires physical desktop control but the bridge is
running in a locked or non-interactive Windows session, report that limitation
and ask for an interactive session. Do not attempt physical mouse/keyboard
control while the user is working unless they explicitly approve it.
