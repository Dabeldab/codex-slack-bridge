# AgentChat/direct_codex 2026-07-11T08:43:00-04:00
# AgentChat/direct_codex 2026-07-14T14:45:00-04:00: verify concise review findings without internal agent prompts.
# AgentChat/direct_codex 2026-07-14T15:31:01-04:00: verify compact update status without duplicate reply transcript.
# AgentChat/direct_codex 2026-07-14T17:58:31-04:00: verify reversible Drawing Board controls and visible agent work.
# AgentChat/direct_codex 2026-07-14T18:14:28-04:00: verify ticket agent results render inside Technical Notes.
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "kanban-command-center" / "index.html").read_text(encoding="utf-8")
APP = (ROOT / "kanban-command-center" / "app.js").read_text(encoding="utf-8")
STYLES = (ROOT / "kanban-command-center" / "styles.css").read_text(encoding="utf-8")
TICKET_DATA = (ROOT / "kanban-command-center" / "ticket-data.js").read_text(encoding="utf-8")
THOR_ASSET = ROOT / "kanban-command-center" / "assets" / "forge-office-agents" / "thor-agent.png"


def test_agent_chat_owns_call_entry_and_voice_is_not_chosen_per_call():
    assert 'id="agentChatCall"' in INDEX
    assert 'id="voiceRoomAgentIdentity"' in INDEX
    assert 'id="voiceRoomAgent"' not in INDEX
    assert 'id="voiceRoomVoice"' not in INDEX
    assert 'id="voiceRoomJoin"' not in INDEX
    for agent, voice in {
        "alex": "af_nicole",
        "jamie": "af_bella",
        "taylor": "af_heart",
    }.items():
        assert f'{agent}: {{ voice: "{voice}"' in APP


def test_chat_opening_forces_latest_message_and_popups_dismiss_outside():
    assert "state.agentChatScrollToLatest = true;" in APP
    assert "const shouldStickToBottom = state.agentChatScrollToLatest" in APP
    assert "if (!changed)" in APP
    assert "state.agentChatPreserveScrollTop = preservedScrollTop;" in APP
    assert "agentChatIsNearBottom()" in APP
    assert 'document.addEventListener("pointerdown"' in APP
    assert "!agentChatDrawer.contains(target)" in APP


def test_background_refresh_skips_unchanged_board_and_active_assignment_renders():
    assert "fingerprint !== state.ticketDataFingerprint" in APP
    assert "nextFingerprint !== state.activeJobsFingerprint" in APP
    assert "stableDataFingerprint(nextJobs)" in APP


def test_dashboard_batches_live_reads_with_backoff_and_visible_outage_state():
    assert 'id="runtimeAlert"' in INDEX
    assert 'id="runtimeAlertMessage"' in INDEX
    assert "const dashboardStateEndpoint" in APP
    assert "async function loadDashboardState(options = {})" in APP
    assert "function applyDashboardState(snapshot)" in APP
    assert "function dashboardPollDelay()" in APP
    assert "dashboardMaxBackoffMs" in APP
    assert 'document.addEventListener("visibilitychange"' in APP
    assert "startInboxEventStream" not in APP
    assert "new EventSource" not in APP
    for old_interval in (
        "ticketDataPollMs",
        "activeAssignmentPollMs",
        "dispatchUpdatesPollMs",
        "reviewPacketPollMs",
        "activityPollMs",
        "agentChatPollMs",
        "emailWatchPollMs",
    ):
        assert old_interval not in APP


def test_agent_chat_accepts_clipboard_images_with_preview_and_remove_controls():
    assert 'id="agentChatAttachments"' in INDEX
    assert 'id="agentChatAttach"' in INDEX
    assert 'id="agentChatFileInput"' in INDEX
    assert "attach up to 5 files" in INDEX
    assert 'agentChatInput?.addEventListener("paste", pasteAgentChatImages);' in APP
    assert 'agentChatFileInput?.addEventListener("change"' in APP
    assert "agentChatAttachmentEndpoint" in APP
    assert "data-remove-chat-attachment" in APP
    assert "up to 5" in INDEX
    assert "10 * 1024 * 1024" in APP


def test_agent_chat_renders_verified_agent_files_and_image_previews():
    assert "renderAgentChatReturnedFiles" in APP
    assert "verifiedAgentChatArtifactUrl" in APP
    assert "agent-chat\\/artifacts" in APP
    assert "agent-chat-returned-file" in STYLES
    assert ".xlsm,.xls" in INDEX


def test_ticket_sync_status_surfaces_each_live_lane_count():
    assert '["support", "billing", "review"].includes(column.key)' in APP
    assert "`${column.label} ${Number(column.count || 0)}`" in APP
    assert 'const source = data === staticTicketData ? "Static snapshot" : "Live cache";' in APP


def test_office_agents_wait_only_for_a_live_darius_decision():
    assert TICKET_DATA.count('agent: "taylor"') == 1
    assert 'agent: "taylor", name: "Taylor", role: "Tech Support · Engineering", state: "idle", load: 0' in TICKET_DATA
    assert "agentStateByKey" not in APP
    assert "function agentDecisionRequest(agentKey)" in APP
    assert "item?.operatorActionRequired === true" in APP
    assert "function operatorDecisionFromResult(result)" in APP
    assert "OPERATOR_ACTION_REQUIRED" in APP
    assert 'return decision ? { mode: "waiting", decision } : { mode: "idle", decision: "" };' in APP
    assert "function syncOfficeAgentStates(options = {})" in APP
    assert "syncOfficeAgentStates({ instant: true });" in APP
    assert APP.count("syncOfficeAgentStates();") >= 3
    assert INDEX.count('class="agent-status-icon"') == 3
    assert "Waiting on Darius" in INDEX
    assert '.agent-sprite[data-state="waiting"] .agent-status-icon' in STYLES
    for node in ("waitAlex", "waitJamie", "waitTaylor"):
        assert f"{node}:" in APP


def test_agent_labels_show_one_tech_support_team_with_scoped_responsibilities():
    for label in (
        "Tech Support · Tickets",
        "Tech Support · Billing",
        "Tech Support · Engineering",
    ):
        assert label in INDEX
    assert "Cool Guy" not in INDEX
    assert "Support Agent" not in INDEX
    assert "Billing Agent" not in INDEX
    assert "Ops Agent" not in INDEX
    assert ">THOR<" not in INDEX
    assert ">Claude<" not in INDEX
    assert '<option value="claude_agent">Thor</option>' not in INDEX
    assert 'label: "Thor"' not in APP
    assert 'claude_agent: "Thor"' in APP
    assert 'name: "Thor", role: "Tech Support · Support Quality"' not in TICKET_DATA


def test_drawing_board_requires_an_actionable_brief_before_dispatch():
    for field_id in (
        "drawingTaskRequest",
        "drawingTaskOutcome",
        "drawingTaskNext",
        "drawingTaskAssigneeAction",
        "drawingTaskSource",
        "drawingTaskCriteria",
        "drawingTaskAgent",
    ):
        assert f'id="{field_id}"' in INDEX
    for responsibility in (
        "Alex - Tickets",
        "Jamie - Billing",
        "Taylor - Engineering",
    ):
        assert responsibility in INDEX
    assert "Personal tasks can be checked off directly" in INDEX
    assert 'id="drawingTaskMode"' in INDEX
    assert 'id="drawingAdvancedFields"' in INDEX
    assert "task.actionable === true" in APP
    assert 'brief.actionable ? "EDIT BRIEF" : "ADD DETAILS"' in APP
    assert "SEND BRIEF TO" in APP
    assert "function drawingTaskLane(task)" in APP
    assert 'if (task.status === "in_progress") return "doing";' in APP
    assert 'return "todo";' in APP
    assert 'const tracked = task.actionable === true && ["ready", "in_progress", "waiting", "evidence_required"].includes(task.status);' in APP
    assert "riskIds" not in APP
    assert 'task.status === "verified_complete" ? "ARCHIVE" : "DISMISS"' in APP
    assert "COMPLETED" in APP
    assert 'actions.push(["in_progress", "START"])' not in APP
    assert "ASK FOR PROOF" not in APP
    assert 'actions.push(["ready", "RETURN TO TODO"])' in APP
    assert 'actions.push(["verify", "MARK DONE"])' in APP
    assert "function drawingAgentWorkMarkup(task)" in APP
    assert 'item.evidence_kind === "agent_report"' in APP
    assert 'item.evidence_kind === "work_product"' in APP
    assert "This card will move to Waiting with the result and any attached files." in APP


def test_disabled_thor_asset_is_archived_without_dispatch_or_animation_controls():
    # Retain the historic asset, but do not load/animate or route the agent.
    assert THOR_ASSET.is_file()
    assert THOR_ASSET.read_bytes().startswith(bytes([137, 80, 78, 71, 13, 10, 26, 10]))
    assert 'class="agent-sprite claude-agent thor-agent"' not in INDEX
    assert 'src="./assets/forge-office-agents/thor-agent.png"' not in INDEX
    assert 'data-dispatch-agent="claude"' not in INDEX
    assert 'data-agent="claude"' not in INDEX
    assert 'value="claude_agent"' not in INDEX
    assert 'thor: "claude"' not in APP
    assert 'support_quality: "claude"' not in APP
    assert 'quality: "claude"' not in APP
    # The remaining three agents retain the general-task dispatch surface.
    assert 'data-dispatch-mode="task">General task<' in INDEX
    assert 'id="dispatchTaskTitle"' in INDEX
    assert 'COMPLETED_WITH_ISSUES' in APP


def test_drawing_board_operator_owned_tasks_are_completed_by_darius_not_dispatched():
    assert "function drawingTaskIsOperatorOwned(task)" in APP
    assert "task?.operator_owned === true || task?.operatorOwned === true" in APP
    assert 'actions.push(["complete", "CHECK OFF"])' in APP
    assert 'actions.push(["start", "START"])' in APP
    assert "task.agent_name && !operatorOwned" in APP
    assert 'operatorOwned ? "Darius - Operator"' in APP
    assert 'operatorOwned ? "YOUR ACTION"' in APP
    assert 'operatorOwned ? ["Operator-owned"]' in APP
    assert 'operatorOwned && task.status === "ready"' in APP
    assert 'if (action === "complete")' in APP


def test_mail_watch_only_renders_live_verified_pending_gmail_items():
    assert "function verifiedPendingEmailWatchEmails" in APP
    assert "email?.gmailState?.verified === true && email.gmailState.pending === true" in APP
    assert "const emails = verifiedPendingEmailWatchEmails(watch);" in APP
    assert APP.count("const emails = verifiedPendingEmailWatchEmails();") >= 3
    assert "There are no current unread, unanswered action emails." in APP
    assert "Gmail verification pending" in APP
    assert "Unverified, read, and already-answered messages are not shown." in APP


def test_mail_watch_makes_verified_reply_all_and_native_signature_explicit():
    assert "Reply All With Signature" in APP
    assert "Send Reply All" in APP
    assert "exact live recipients" in APP
    assert "live headers" in APP
    assert "existing Gmail signature" in APP


def test_mail_watch_refreshes_in_the_slow_dashboard_batch_and_after_queue_changes():
    assert "const dashboardSlowPollMs = 60000;" in APP
    assert "if (snapshot.emailWatch) applyEmailWatchSnapshot(snapshot.emailWatch);" in APP
    assert "function emailWatchIsVisible()" in APP
    assert APP.count("await loadEmailWatch({ silent: true });") >= 2


def test_dispatch_validation_errors_are_not_mislabeled_as_gateway_outages():
    assert 'const reason = String(result.message || "task was not accepted").trim();' in APP
    assert '`${taskLabel} not queued: ${reason}`' in APP
    assert 'const retryable = response.status === 408' in APP
    assert 'if (retryable) queueDispatchPayload(payload);' in APP
    assert 'retryable: true,' in APP
    assert "Command center gateway unavailable; ${payload.taskTitle || payload.ticketNumber} saved locally." not in APP


def test_review_technical_notes_show_findings_not_internal_agent_instructions():
    start = APP.index("function ticketFromReviewPacket(packet)")
    end = APP.index("function buildBoardColumns()", start)
    review_renderer = APP[start:end]

    assert "Original instruction:" not in review_renderer
    assert "No agent result recorded." not in review_renderer
    assert "Decision needed:" in review_renderer
    assert "Finding and recommendation:" in review_renderer


def test_ticket_detail_uses_compact_agent_update_status_without_duplicate_reply_section():
    assert 'class="agent-update-summary"' in INDEX
    assert 'id="agentRepliesStatus"' in INDEX
    assert "Agent Replies" not in INDEX
    assert 'id="agentRepliesList"' not in INDEX
    assert 'id="agentRepliesRefresh"' not in INDEX
    assert "agentRepliesStatus.hidden = false;" in APP
    assert "agentRepliesStatus.dataset.state" in APP
    assert "agent-reply-card" not in APP


def test_ticket_agent_results_render_in_technical_notes_without_dispatch_instructions():
    start = APP.index("function ticketAgentUpdatesText(ticket)")
    end = APP.index("function ticketSessionHistoryText", start)
    renderer = APP[start:end]

    assert "job.result" in renderer
    assert "Agent updates:" in renderer
    assert "payload.instruction" not in renderer
    assert "payload.prompt" not in renderer
    assert 'document.querySelector("#detailNotes").textContent = ticketNotesWithAgentUpdates(ticket);' in APP
