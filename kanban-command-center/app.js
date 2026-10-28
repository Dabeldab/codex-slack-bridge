// AgentChat/coding_agent 2026-07-10T13:05:00-04:00
// AgentChat/direct_codex 2026-07-11T08:43:00-04:00: fixed per-agent voices, chat call entry, latest-message opening, and outside-click dismissal.
// AgentChat/coding_agent 2026-07-14T12:20:00-04:00: turn Drawing Board into a task-first operator Kanban with optional agent briefs.
// AgentChat/coding_agent 2026-07-13T23:42:00-04:00: keep explicit Salesforce-open state authoritative and never age-filter board tickets.
// AgentChat/direct_codex 2026-07-14T00:00:00-04:00: update Mail Watch from the durable inbox-ledger event stream.
// AgentChat/direct_codex 2026-07-14T14:45:00-04:00: render review findings and decisions without exposing agent instructions.
// AgentChat/direct_codex 2026-07-14T15:31:01-04:00: keep only a compact agent-update indicator in ticket details.
// AgentChat/direct_codex 2026-07-14T18:14:28-04:00: show ticket-linked agent results in Technical Notes without exposing dispatch prompts.
// AgentChat/direct_codex 2026-07-14T17:58:31-04:00: add reversible Drawing Board flow and attached agent work products.
if (window.location.protocol === "file:") {
  window.location.replace("http://127.0.0.1:17866/dashboard/");
}

const nativeBrowserFetch = window.fetch.bind(window);
const fetch = (input, init = {}) => {
  const url = typeof input === "string" ? input : String(input?.url || "");
  const isCommandCenterRequest = url.startsWith("http://127.0.0.1:17866")
    || (window.location.protocol.startsWith("http") && url.startsWith(window.location.origin));
  if (!isCommandCenterRequest) {
    return nativeBrowserFetch(input, init);
  }
  const method = String(init.method || (typeof input !== "string" && input?.method) || "GET").toUpperCase();
  const headers = new Headers(init.headers || (typeof input !== "string" ? input?.headers : undefined));
  if (!new Set(["GET", "HEAD", "OPTIONS"]).has(method)) {
    const csrf = document.cookie
      .split(";")
      .map((item) => item.trim())
      .find((item) => item.startsWith("NovaCommandCenterCsrf="))
      ?.slice("NovaCommandCenterCsrf=".length);
    if (csrf) headers.set("X-Nova-CSRF", decodeURIComponent(csrf));
  }
  return nativeBrowserFetch(input, {
    ...init,
    headers,
    credentials: "same-origin",
    cache: init.cache || "no-store",
  });
};

const staticTicketData = window.NOVA_OPS_TICKET_DATA || { columns: [], agentActivity: [], analytics: {} };
let data = staticTicketData;

const state = {
  draggedCard: null,
  selectedTicket: null,
  dispatchTicket: null,
  dispatchAgent: null,
  dispatchMode: "ticket",
  agentLocations: {},
  agentMoves: {},
  officeAgentModes: {},
  activeJobs: [],
  activeJobsFingerprint: "",
  dispatchJobs: [],
  activityJobs: [],
  dispatchSubmitting: false,
  dispatchPendingKeys: new Set(),
  boardColumns: [],
  ticketDataFingerprint: "",
  activeAssignmentsLoaded: false,
  dispatchJobsLoaded: false,
  activityJobsLoaded: false,
  ticketRefreshQueued: false,
  ticketRefreshRequestedAt: "",
  ticketRefreshPollsRemaining: 0,
  ticketRefreshPollTimer: null,
  kpiDashboard: null,
  usageHistory: null,
  usageLoading: false,
  usageLoadedAt: 0,
  kpiRefreshQueued: false,
  kpiRefreshRequestedAt: "",
  kpiRefreshPollsRemaining: 0,
  kpiRefreshPollTimer: null,
  emailWatch: null,
  emailDrafts: new Map(),
  emailSendPendingKeys: new Set(),
  emailMarkReadPendingKeys: new Set(),
  dashboardPollTimer: null,
  dashboardPollInFlight: false,
  dashboardPollHalted: false,
  dashboardPollFailures: 0,
  dashboardLastSuccessAt: "",
  dashboardLastSlowAt: 0,
  dashboardLastKpiAt: 0,
  reviewPackets: [],
  reviewPacketActionsPending: new Set(),
  agentChatMessages: [],
  agentChatFingerprint: "",
  agentChatLoaded: false,
  agentChatAgent: null,
  agentChatOpen: false,
  agentChatScrollToLatest: false,
  agentChatPreserveScrollTop: null,
  agentChatSending: false,
  agentChatPendingKeys: new Set(),
  agentChatAttachments: [],
  agentChatLastSeen: {},
  schedule: null,
  drawingBoard: [],
  drawingBoardBriefing: null,
  drawingBoardLoaded: false,
  drawingBoardLoading: false,
  drawingBoardPending: new Set(),
  drawingBoardEditingTaskId: null,
  voiceRoom: {
    phase: "idle",
    provider: "local",
    peer: null,
    channel: null,
    stream: null,
    muted: false,
    audioContext: null,
    sourceNode: null,
    processorNode: null,
    silentGainNode: null,
    pcmChunks: [],
    preRollChunks: [],
    speechStarted: false,
    speechStartedAt: 0,
    lastVoiceAt: 0,
    bargeFrames: 0,
    localBusy: false,
    localSessionId: 0,
    localAbortController: null,
    playbackUrl: "",
    transcriptEntries: new Map(),
    heldToolCalls: new Set(),
    agentKey: null,
    voice: "",
  },
  leftRailCollapsed: false,
  selectionClearedByUser: false,
};

const appShell = document.querySelector(".app-shell");
const kanbanBoard = document.querySelector("#kanbanBoard");
const agentList = document.querySelector("#agentList");
const toastStack = document.querySelector("#toastStack");
const notesTooltip = document.querySelector("#notesTooltip");
const agentButtons = [...document.querySelectorAll("button.agent-sprite[data-agent]")];
const youElement = document.querySelector(".you-agent");
const dispatchPanel = document.querySelector("#dispatchPanel");
const dispatchTicketNumber = document.querySelector("#dispatchTicketNumber");
const dispatchClearTicket = document.querySelector("#dispatchClearTicket");
const dispatchStatus = document.querySelector("#dispatchStatus");
const dispatchInstruction = document.querySelector("#dispatchInstruction");
const dispatchTaskTitle = document.querySelector("#dispatchTaskTitle");
const dispatchSubmit = document.querySelector("#dispatchSubmit");
const dispatchModeButtons = [...document.querySelectorAll("[data-dispatch-mode]")];
const dispatchAgentButtons = [...document.querySelectorAll("[data-dispatch-agent]")];
const agentRepliesStatus = document.querySelector("#agentRepliesStatus");
const rightPanel = document.querySelector(".right-panel");
const emailDrawer = document.querySelector("#emailDrawer");
const emailDrawerToggle = document.querySelector("#emailDrawerToggle");
const emailDrawerClose = document.querySelector("#emailDrawerClose");
const emailRefresh = document.querySelector("#emailRefresh");
const emailWatchStatus = document.querySelector("#emailWatchStatus");
const emailSummary = document.querySelector("#emailSummary");
const emailWatchList = document.querySelector("#emailWatchList");
const emailPageRefresh = document.querySelector("#emailPageRefresh");
const emailPageStatus = document.querySelector("#emailPageStatus");
const emailPageSummary = document.querySelector("#emailPageSummary");
const emailPageList = document.querySelector("#emailPageList");
const detailClearSelection = document.querySelector("#detailClearSelection");
const reviewPacketActions = document.querySelector("#reviewPacketActions");
const reviewPacketStatus = document.querySelector("#reviewPacketStatus");
const reviewPacketContinue = document.querySelector("#reviewPacketContinue");
const reviewPacketAbandon = document.querySelector("#reviewPacketAbandon");
const reviewPacketClose = document.querySelector("#reviewPacketClose");
const scheduleRefresh = document.querySelector("#scheduleRefresh");
const meetingList = document.querySelector("#meetingList");
const kanbanSurface = document.querySelector('.view-surface[data-view="kanban"]');
const officeStage = document.querySelector(".office-stage");
const ticketResizeHandle = document.querySelector("#ticketResizeHandle");
const ticketRefresh = document.querySelector("#ticketRefresh");
const ticketSyncStatus = document.querySelector("#ticketSyncStatus");
const runtimeAlert = document.querySelector("#runtimeAlert");
const runtimeAlertMessage = document.querySelector("#runtimeAlertMessage");
const leftRailToggle = document.querySelector("#leftRailToggle");
const activityStatus = document.querySelector("#activityStatus");
const kpiRefresh = document.querySelector("#kpiRefresh");
const kpiStatus = document.querySelector("#kpiStatus");
const analyticsSummary = document.querySelector("#analyticsSummary");
const kpiSections = document.querySelector("#kpiSections");
const agentChatDrawer = document.querySelector("#agentChatDrawer");
const agentChatClose = document.querySelector("#agentChatClose");
const agentChatCall = document.querySelector("#agentChatCall");
const agentChatTitle = document.querySelector("#agentChatTitle");
const agentChatStatus = document.querySelector("#agentChatStatus");
const agentChatMessages = document.querySelector("#agentChatMessages");
const agentChatForm = document.querySelector("#agentChatForm");
const agentChatInput = document.querySelector("#agentChatInput");
const agentChatSend = document.querySelector("#agentChatSend");
const agentChatAttachments = document.querySelector("#agentChatAttachments");
const agentChatAttach = document.querySelector("#agentChatAttach");
const agentChatFileInput = document.querySelector("#agentChatFileInput");
const drawingBoardColumns = document.querySelector("#drawingBoardColumns");
const drawingBoardStatus = document.querySelector("#drawingBoardStatus");
const drawingBoardCreate = document.querySelector("#drawingBoardCreate");
const drawingBoardNew = document.querySelector("#drawingBoardNew");
const drawingBoardCreateClose = document.querySelector("#drawingBoardCreateClose");
const drawingBoardCancel = document.querySelector("#drawingBoardCancel");
const drawingBoardFormTitle = document.querySelector("#drawingBoardFormTitle");
const drawingBoardSaveBrief = document.querySelector("#drawingBoardSaveBrief");
const drawingTaskMode = document.querySelector("#drawingTaskMode");
const drawingAdvancedFields = document.querySelector("#drawingAdvancedFields");
const drawingTaskTitle = document.querySelector("#drawingTaskTitle");
const drawingTaskRequest = document.querySelector("#drawingTaskRequest");
const drawingTaskOutcome = document.querySelector("#drawingTaskOutcome");
const drawingTaskNext = document.querySelector("#drawingTaskNext");
const drawingTaskAssigneeAction = document.querySelector("#drawingTaskAssigneeAction");
const drawingTaskSource = document.querySelector("#drawingTaskSource");
const drawingTaskCriteria = document.querySelector("#drawingTaskCriteria");
const drawingTaskOwner = document.querySelector("#drawingTaskOwner");
const drawingTaskAgent = document.querySelector("#drawingTaskAgent");
const drawingTaskPriority = document.querySelector("#drawingTaskPriority");
const drawingTaskDue = document.querySelector("#drawingTaskDue");
const drawingBoardBrief = document.querySelector("#drawingBoardBrief");
const drawingBoardBriefing = document.querySelector("#drawingBoardBriefing");
const drawingBoardBriefClose = document.querySelector("#drawingBoardBriefClose");
const drawingBoardBriefContent = document.querySelector("#drawingBoardBriefContent");
const drawingBoardDigest = document.querySelector("#drawingBoardDigest");
const drawingBoardRefresh = document.querySelector("#drawingBoardRefresh");
const drawingActiveCount = document.querySelector("#drawingActiveCount");
const drawingDraftCount = document.querySelector("#drawingDraftCount");
const drawingDueCount = document.querySelector("#drawingDueCount");
const drawingStaleCount = document.querySelector("#drawingStaleCount");
const drawingWaitingCount = document.querySelector("#drawingWaitingCount");
const drawingProofCount = document.querySelector("#drawingProofCount");
const voiceRoomShell = document.querySelector("#voiceRoomShell");
const voiceRoomStateLabel = document.querySelector("#voiceRoomStateLabel");
const voiceRoomPrompt = document.querySelector("#voiceRoomPrompt");
const voiceRoomDetail = document.querySelector("#voiceRoomDetail");
const voiceRoomProvider = document.querySelector("#voiceRoomProvider");
const voiceRoomProviderButtons = [...document.querySelectorAll("[data-voice-provider]")];
const voiceRoomMute = document.querySelector("#voiceRoomMute");
const voiceRoomEnd = document.querySelector("#voiceRoomEnd");
const voiceRoomClear = document.querySelector("#voiceRoomClear");
const voiceRoomTranscript = document.querySelector("#voiceRoomTranscript");
const voiceRoomEvents = document.querySelector("#voiceRoomEvents");
const voiceRoomAudio = document.querySelector("#voiceRoomAudio");
const voiceRoomPrivacy = document.querySelector("#voiceRoomPrivacy");
const voiceRoomAgentIdentity = document.querySelector("#voiceRoomAgentIdentity");
const voiceRoomAgentAvatar = document.querySelector("#voiceRoomAgentAvatar");
const voiceRoomAgentName = document.querySelector("#voiceRoomAgentName");
const voiceRoomAgentVoice = document.querySelector("#voiceRoomAgentVoice");
const runtimeSecurityBadge = document.querySelector("#runtimeSecurityBadge");
const operatorIdentity = document.querySelector("#operatorIdentity");
const operatorLogout = document.querySelector("#operatorLogout");

const laneTheme = {
  support: "support",
  billing: "billing",
  progress: "active-lane",
  review: "review",
};

const commandCenterBaseUrl = window.location.protocol.startsWith("http")
  ? window.location.origin
  : "http://127.0.0.1:17866";
const healthEndpoint = `${commandCenterBaseUrl}/health`;
const authSessionEndpoint = `${commandCenterBaseUrl}/auth/session`;
const authLogoutEndpoint = `${commandCenterBaseUrl}/auth/logout`;
const dispatchEndpoint = `${commandCenterBaseUrl}/dispatch`;
const jobsEndpoint = `${commandCenterBaseUrl}/jobs`;
const dashboardStateEndpoint = `${commandCenterBaseUrl}/ops/dashboard-state`;
const usageHistoryEndpoint = `${commandCenterBaseUrl}/usage/history`;
const ticketsEndpoint = `${commandCenterBaseUrl}/ops/tickets`;
const ticketRefreshEndpoint = `${commandCenterBaseUrl}/ops/tickets/refresh`;
const emailWatchEndpoint = `${commandCenterBaseUrl}/ops/email-watch`;
const emailScanEndpoint = `${commandCenterBaseUrl}/ops/email-watch/scan`;
const emailSendEndpoint = `${commandCenterBaseUrl}/ops/email-watch/send-reply`;
const emailMarkReadEndpoint = `${commandCenterBaseUrl}/ops/email-watch/mark-read`;
const reviewPacketsEndpoint = `${commandCenterBaseUrl}/ops/review-packets`;
const reviewPacketContinueEndpoint = `${commandCenterBaseUrl}/ops/review-packets/continue`;
const reviewPacketCloseEndpoint = `${commandCenterBaseUrl}/ops/review-packets/proceed-close`;
const reviewPacketAbandonEndpoint = `${commandCenterBaseUrl}/ops/review-packets/abandon`;
const scheduleEndpoint = `${commandCenterBaseUrl}/ops/schedule`;
const scheduleScanEndpoint = `${commandCenterBaseUrl}/ops/schedule/scan`;
const kpiDashboardEndpoint = `${commandCenterBaseUrl}/ops/kpi-dashboard`;
const kpiDashboardRefreshEndpoint = `${commandCenterBaseUrl}/ops/kpi-dashboard/refresh`;
const agentChatEndpoint = `${commandCenterBaseUrl}/agent-chat`;
const agentChatAttachmentEndpoint = `${commandCenterBaseUrl}/agent-chat/attachments`;
const agentChatSendEndpoint = `${commandCenterBaseUrl}/agent-chat/send`;
const drawingBoardEndpoint = `${commandCenterBaseUrl}/ops/drawing-board`;
const drawingBoardCreateEndpoint = `${drawingBoardEndpoint}/tasks`;
const drawingBoardUpdateEndpoint = `${drawingBoardEndpoint}/tasks/update`;
const drawingBoardDispatchEndpoint = `${drawingBoardEndpoint}/tasks/dispatch`;
const drawingBoardDigestEndpoint = `${drawingBoardEndpoint}/digest`;
const voiceRoomSessionEndpoint = `${commandCenterBaseUrl}/voice/realtime/session`;
const voiceRoomLocalStatusEndpoint = `${commandCenterBaseUrl}/voice/local/status`;
const voiceRoomLocalWarmupEndpoint = `${commandCenterBaseUrl}/voice/local/warmup`;
const voiceRoomLocalTranscribeEndpoint = `${commandCenterBaseUrl}/voice/local/transcribe`;
const voiceRoomLocalSynthesizeEndpoint = `${commandCenterBaseUrl}/voice/local/synthesize`;
const ticketBoardHeightKey = "novaOpsTicketBoardHeight";
const leftRailCollapsedKey = "novaOpsLeftRailCollapsed";
const agentChatLastSeenKey = "novaOpsAgentChatLastSeen";
const dashboardPollVisibleMs = 10000;
const dashboardPollHiddenMs = 60000;
const dashboardSlowPollMs = 60000;
const dashboardKpiPollMs = 300000;
const dashboardMaxBackoffMs = 60000;
const dashboardRequestTimeoutMs = 20000;
const ticketRefreshPollMs = 12000;
const kpiRefreshPollMs = 15000;
const activeJobStatuses = new Set(["queued", "running"]);
const inactiveDecisionStatuses = new Set(["resolved", "verified_complete", "completed", "abandoned", "dismissed", "closed"]);
const supportTicketRecordTypes = new Set(["1. nova classic", "2. nova wave"]);
const billingTicketRecordTypes = new Set(["3. billing", "billing", "nova billing"]);
const closedTicketStatuses = new Set(["closed", "complete", "completed", "done", "resolved", "cancelled", "canceled", "merged", "void", "voided"]);
const excludedAccountPattern = /demo|test|template/i;
const excludedTechnicalIssuePattern = /\bbug\b|feature request/i;
const excludedDevelopmentRecordTypes = new Set(["5. development", "development"]);
const dispatchAgentMap = {
  alex: "tickets_agent",
  jamie: "billing_agent",
  taylor: "coding_agent",
};
const dispatchAgentAliases = Object.freeze({});
const agentVoiceProfiles = Object.freeze({
  alex: { voice: "af_nicole", label: "Nicole" },
  jamie: { voice: "af_bella", label: "Bella" },
  taylor: { voice: "af_heart", label: "Heart" },
});
const agentRoster = [
  { key: "alex", agentName: "tickets_agent", label: "Alex", color: "cyan" },
  { key: "jamie", agentName: "billing_agent", label: "Jamie", color: "green" },
  { key: "taylor", agentName: "coding_agent", label: "Taylor", color: "purple" },
];
const activeSourceTypes = new Set(["dispatch", "review-packet-continue", "review-packet-close", "ops-email-watch", "ops-email-send", "ops-email-mark-read", "ops-schedule", "ops-ticket-refresh", "ops-kpi-dashboard", "ops-singapore-ftp"]);
const activitySourceTypes = new Set([...activeSourceTypes, "agent-direct-chat"]);
const ticketReplySourceTypes = new Set(["dispatch", "review-packet-continue", "review-packet-close"]);

const agentElements = Object.fromEntries(agentButtons.map((item) => [item.dataset.agent, item]));

const officeNodes = {
  alexHome: { x: 22, y: 41 },
  jamieHome: { x: 78, y: 41 },
  taylorHome: { x: 22, y: 78 },
  claudeHome: { x: 78, y: 78 },
  leadDesk: { x: 50, y: 61 },
  handoff: { x: 50, y: 74 },
  waitAlex: { x: 35, y: 72 },
  waitJamie: { x: 65, y: 72 },
  waitTaylor: { x: 42, y: 83 },
  waitClaude: { x: 58, y: 83 },
  westHub: { x: 37, y: 55 },
  eastHub: { x: 63, y: 55 },
  southHub: { x: 50, y: 82 },
};

const agentConfig = {
  alex: {
    home: "alexHome",
    wait: "waitAlex",
    route: ["alexHome", "westHub", "handoff"],
    waitRoute: ["alexHome", "westHub", "waitAlex"],
  },
  jamie: {
    home: "jamieHome",
    wait: "waitJamie",
    route: ["jamieHome", "eastHub", "handoff"],
    waitRoute: ["jamieHome", "eastHub", "waitJamie"],
  },
  taylor: {
    home: "taylorHome",
    wait: "waitTaylor",
    route: ["taylorHome", "westHub", "southHub", "handoff"],
    waitRoute: ["taylorHome", "southHub", "waitTaylor"],
  },
};

function escapeText(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function isPlainEnterKey(event) {
  return event.key === "Enter"
    && !event.shiftKey
    && !event.ctrlKey
    && !event.metaKey
    && !event.altKey
    && !event.isComposing;
}

function parseSteerCommand(value) {
  const text = String(value || "").trim();
  const match = text.match(/^\/(btw|steer)\b(?:\s*[:,-]\s*|\s+)?([\s\S]*)$/i);
  if (!match) {
    return { isSteer: false, command: "", text };
  }
  return { isSteer: true, command: `/${String(match[1] || "").toLowerCase()}`, text: String(match[2] || "").trim() };
}

function operatorInstructionLine(value, fallback = "") {
  const parsed = parseSteerCommand(value || fallback);
  if (parsed.isSteer) {
    return `Operator steering note (${parsed.command}): ${parsed.text || fallback || "Use this as steering for the current work."}`;
  }
  return `Operator instruction: ${parsed.text || fallback || "Handle the requested operational task."}`;
}

function steeringRuleLine(value) {
  return parseSteerCommand(value).isSteer
    ? "Steering note rule: apply this as a separate queued follow-up after any in-flight lane work. The bridge did not inject it into an already in-flight turn. Do not paste `/btw` or `/steer` into Salesforce, customer messages, email, Zoom, SQL, or notes."
    : "";
}

function formatSnapshotTime(value) {
  if (!value) return "Snapshot unavailable";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Snapshot loaded";
  return `Snapshot ${date.toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}`;
}

function getStaticColumns() {
  return Array.isArray(data.columns) ? data.columns : [];
}

function ticketIdentity(ticket) {
  return String(ticket?.number || ticket?.id || ticket?.ticketNumber || ticket?.taskId || "").trim();
}

function getJobTicketNumber(job) {
  const payload = job?.payload || {};
  return String(payload.ticketNumber || payload.ticket || payload.ticketId || payload.taskId || "").trim();
}

function isActiveDispatchJob(job) {
  return activeSourceTypes.has(String(job?.sourceType || "")) && activeJobStatuses.has(String(job?.status || ""));
}

function isGeneralTaskJob(job) {
  const payload = job?.payload || {};
  return String(payload.type || "") === "general-agent-task" || Boolean(payload.taskId || payload.taskTitle);
}

function isOperationalTaskJob(job) {
  const sourceType = jobSourceType(job);
  return Boolean(sourceType && activeSourceTypes.has(sourceType) && !ticketReplySourceTypes.has(sourceType));
}

function isBoardTaskJob(job) {
  return isOperationalTaskJob(job);
}

function jobBoardIdentity(job) {
  return getJobTicketNumber(job) || (isBoardTaskJob(job) ? jobIdentity(job) : "");
}

function uiAgentForJob(job) {
  const payload = job?.payload || {};
  const rawValue = String(payload.agent || payload.targetAgent || "").trim().toLowerCase();
  const rawAgent = dispatchAgentAliases[rawValue] || rawValue;
  if (dispatchAgentMap[rawAgent]) return rawAgent;
  const agentName = String(payload.agentName || job?.agentName || "").trim().toLowerCase();
  return Object.entries(dispatchAgentMap).find(([, mapped]) => mapped === agentName)?.[0] || rawAgent || agentName;
}

function getStaticTicket(number) {
  const normalized = String(number || "").trim();
  if (!normalized) return null;
  for (const column of getStaticColumns()) {
    for (const ticket of column.tickets || []) {
      if (ticketIdentity(ticket) === normalized) return ticket;
    }
  }
  return null;
}

function normalizedText(value) {
  return String(value || "").trim().toLowerCase();
}

function hasAllowedTicketScope(ticket) {
  const recordType = normalizedText(ticket?.recordType || ticket?.type || ticket?.category);
  if (recordType) return supportTicketRecordTypes.has(recordType) || billingTicketRecordTypes.has(recordType);
  const productText = normalizedText([ticket?.product, ticket?.mainIssue, ticket?.technicalIssue].join(" "));
  return /\bnova classic\b|\bnova wave\b|\bbilling\b/.test(productText);
}

function isExcludedAccountTicket(ticket) {
  const account = String(ticket?.account || ticket?.accountName || ticket?.AccountName || "").trim();
  return excludedAccountPattern.test(account);
}

function isDevelopmentTicket(ticket) {
  return excludedDevelopmentRecordTypes.has(normalizedText(ticket?.recordType || ticket?.type || ticket?.category));
}

function hasExcludedTechnicalIssue(ticket) {
  const technicalIssue = normalizedText(ticket?.technicalIssue || ticket?.technical_issue || ticket?.Technical_Issue__c);
  return excludedTechnicalIssuePattern.test(technicalIssue);
}

function explicitTicketStatus(ticket) {
  const fields = [
    "status",
    "ticketStatus",
    "caseStatus",
    "state",
    "stage",
    "statusName",
    "Status",
    "Ticket_Status__c",
    "Status__c",
  ];
  for (const field of fields) {
    const value = normalizedText(ticket?.[field]);
    if (value) return value;
  }
  return "";
}

function isClosedTicket(ticket) {
  for (const field of ["isClosed", "IsClosed", "Is_Closed__c"]) {
    if (!Object.prototype.hasOwnProperty.call(ticket || {}, field)) continue;
    const value = ticket[field];
    if (typeof value === "boolean") return value;
    const normalized = normalizedText(value);
    if (normalized) return ["true", "1", "yes", "y", "closed"].includes(normalized);
  }
  const explicitStatus = explicitTicketStatus(ticket);
  if (closedTicketStatuses.has(explicitStatus)) return true;
  return false;
}

function isBoardEligibleTicket(ticket) {
  return Boolean(ticket)
    && hasAllowedTicketScope(ticket)
    && !isExcludedAccountTicket(ticket)
    && !isDevelopmentTicket(ticket)
    && !hasExcludedTechnicalIssue(ticket)
    && !isClosedTicket(ticket);
}

function isSupportTicket(ticket) {
  return supportTicketRecordTypes.has(normalizedText(ticket?.recordType));
}

function isBillingTicket(ticket) {
  const recordType = normalizedText(ticket?.recordType);
  return billingTicketRecordTypes.has(recordType);
}

function ticketNotesText(ticket) {
  const base = String(ticket?.notesFull || ticket?.technicalNotes || ticket?.notes || "").trim();
  const sessionHistory = ticketSessionHistoryText(ticket, base);
  const chatter = ticketChatterText(ticket);
  const sections = [];
  if (sessionHistory && !/\b(LogMeIn|Rescue|Zoom) \/ Session History\b/i.test(base)) {
    sections.push(`LogMeIn / Session History:\n${sessionHistory}`);
  }
  if (base) sections.push(base);
  if (chatter && !/\bSalesforce Chatter \/ Comments\b/i.test(base)) {
    sections.push(`Salesforce Chatter / Comments:\n${chatter}`);
  }
  return sections.join("\n\n").trim() || "No technical notes recorded.";
}

function ticketAgentUpdatesText(ticket) {
  if (!ticket || !state.dispatchJobsLoaded) return "";
  const seen = new Set();
  const updates = sortJobsNewestFirst(
    state.dispatchJobs.filter((job) => jobMatchesTicket(job, ticket))
  ).filter((job) => {
    const identity = jobIdentity(job);
    if (!identity || seen.has(identity) || !String(job?.result || "").trim()) return false;
    seen.add(identity);
    return true;
  });
  return updates.map((job) => {
    const agentKey = uiAgentForJob(job);
    const agentLabel = labelForAgent(agentKey) || job?.payload?.agentLabel || job?.agentName || "Agent";
    const status = normalizedJobStatus(job).replaceAll("_", " ");
    const when = formatCompactDate(jobTimestamp(job));
    const heading = [agentLabel, when, status].filter(Boolean).join(" - ");
    return `${heading}:\n${String(job.result).trim()}`;
  }).join("\n\n");
}

function ticketNotesWithAgentUpdates(ticket) {
  const base = ticketNotesText(ticket);
  const reconIsCurrent = Boolean(
    ticket?.reconFingerprint
      && ticket?.reconEvidenceFingerprint
      && ticket.reconFingerprint === ticket.reconEvidenceFingerprint
  );
  const recon = reconIsCurrent ? String(ticket?.reconResult || "").trim() : "";
  const reconAgent = labelForAgent(agentKeyForAgentName(ticket?.reconAgentName || ""))
    || ticket?.reconAgentName
    || "Agent";
  const reconState = String(ticket?.reconState || "").replaceAll("_", " ");
  const updates = ticketAgentUpdatesText(ticket);
  const technicalNotes = base === "No technical notes recorded." ? "" : base;
  return [
    technicalNotes,
    recon ? `Proactive solution plan - ${reconAgent}${reconState ? ` (${reconState})` : ""}:\n\n${recon}` : "",
    updates ? `Agent updates:\n\n${updates}` : "",
  ].filter(Boolean).join("\n\n") || "No technical notes recorded.";
}

function ticketSessionHistoryText(ticket, baseNotes = "") {
  if (!ticket) return "";
  const direct = sessionHistoryDirectFields(ticket).map((item) => item.trim()).filter(Boolean);
  const itemFields = [
    "sessionHistoryItems",
    "sessionHistory",
    "session_history",
    "sessionHistories",
    "sessionHistoryRecords",
    "sessionHistoryRecords__r",
    "SessionHistory",
    "Session_History__r",
    "Session_History__c",
    "rescueSessions",
    "rescueSession",
    "logmeinSessions",
    "logmeinSession",
    "zoomSessionHistory",
    "zoomSessions",
  ];
  const items = itemFields.flatMap((field) => {
    const value = ticket[field];
    if (Array.isArray(value)) return value;
    if (value && typeof value === "object") return [value];
    return [];
  });
  const itemText = items.map(formatSessionHistoryItem).filter(Boolean);
  const extracted = extractSessionHistoryFromNotes(baseNotes || String(ticket.notesFull || ticket.technicalNotes || ticket.notes || ""));
  return uniqueNoteLines([...direct, ...itemText, ...extracted]).join("\n").trim();
}

function sessionHistoryDirectFields(ticket) {
  const labeledFields = [
    ["logmeinSessionId", "LogMeIn Session ID"],
    ["logmeinSessionID", "LogMeIn Session ID"],
    ["logmein_session_id", "LogMeIn Session ID"],
    ["LogMeInSessionID", "LogMeIn Session ID"],
    ["LogMeIn_Session_ID__c", "LogMeIn Session ID"],
    ["rescueSessionId", "LogMeIn Session ID"],
    ["rescue_session_id", "LogMeIn Session ID"],
    ["Rescue_Session_ID__c", "LogMeIn Session ID"],
    ["sessionId", "Session ID"],
    ["session_id", "Session ID"],
    ["SessionId", "Session ID"],
    ["Session_ID__c", "Session ID"],
    ["zoomEngagementId", "Zoom Engagement ID"],
    ["Zoom_Engagement_ID__c", "Zoom Engagement ID"],
    ["sessionHistoryId", "Session History"],
    ["Session_History__c", "Session History"],
  ];
  const lines = [];
  for (const [field, label] of labeledFields) {
    const value = stringNoteValue(ticket[field]);
    if (value) lines.push(`${label}: ${value}`);
  }
  const noteFields = [
    "sessionHistorySummary",
    "sessionHistoryNotes",
    "sessionHistoryText",
    "session_history_summary",
    "session_history_notes",
    "rescueSessionSummary",
    "logmeinSessionSummary",
    "zoomSessionSummary",
    "smartNotes",
    "Smart_Notes__c",
  ];
  for (const field of noteFields) {
    const value = stringNoteValue(ticket[field]);
    if (value) lines.push(value);
  }
  return lines;
}

function formatSessionHistoryItem(item) {
  if (!item) return "";
  if (typeof item === "string") return item.trim();
  const id = item.sessionId || item.session_id || item.rescueSessionId || item.rescue_session_id || item.Rescue_Session_ID__c || item.Id || item.id || item.Name || item.name || "";
  const source = item.source || item.channel || item.type || item.Source_Channel__c || "";
  const started = formatCompactDate(item.startedAt || item.startTime || item.start_time || item.Start_Time__c || item.createdAt || item.CreatedDate || "");
  const ended = formatCompactDate(item.endedAt || item.endTime || item.end_time || item.End_Time__c || "");
  const tech = item.technician || item.technicianName || item.agent || item.owner || item.CreatedBy?.Name || "";
  const duration = item.duration || item.totalTime || item.total_time || item.Duration__c || "";
  const status = item.status || item.sessionStatus || item.Status__c || "";
  const summary = item.summary || item.notes || item.body || item.text || item.transcriptSummary || item.smartNotes || item.Smart_Notes__c || "";
  const bits = [
    id ? `Session ${id}` : "Session history",
    source,
    started ? `start ${started}` : "",
    ended ? `end ${ended}` : "",
    tech ? `tech ${tech}` : "",
    duration ? `duration ${duration}` : "",
    status,
  ].filter(Boolean);
  const prefix = bits.join(" | ");
  return [prefix, String(summary || "").trim()].filter(Boolean).join(": ");
}

function extractSessionHistoryFromNotes(notes) {
  const text = String(notes || "");
  if (!text) return [];
  const lines = [];
  const seenIds = new Set();
  for (const match of text.matchAll(/\b(?:LogMeIn|Rescue)\s+Session\s+ID\s*[:#]?\s*([A-Za-z0-9_-]+)/gi)) {
    const id = match[1];
    if (!seenIds.has(id)) {
      seenIds.add(id);
      lines.push(`LogMeIn Session ID: ${id}`);
    }
  }
  if (!seenIds.size) {
    for (const match of text.matchAll(/\bSession\s+ID\s*[:#]?\s*([0-9]{6,})/gi)) {
      const id = match[1];
      if (!seenIds.has(id)) {
        seenIds.add(id);
        lines.push(`Session ID: ${id}`);
      }
    }
  }
  const eventLines = text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => /\b(CHATLOG:|Connecting to:|Remote Control|Applet|technician ended|customer ended|Switched to P2P|permission to remote control|device is rebooting)\b/i.test(line))
    .slice(0, 8);
  return uniqueNoteLines([...lines, ...eventLines]);
}

function uniqueNoteLines(lines) {
  const seen = new Set();
  const result = [];
  for (const line of lines) {
    const text = String(line || "").trim();
    if (!text) continue;
    const key = text.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    result.push(truncateLongText(text, 1600));
  }
  return result;
}

function ticketChatterText(ticket) {
  if (!ticket) return "";
  const directFields = [
    "chatterSummary",
    "chatterNotes",
    "chatterText",
    "salesforceComments",
    "caseComments",
    "comments",
  ];
  const direct = directFields
    .map((field) => stringNoteValue(ticket[field]))
    .filter(Boolean)
    .join("\n\n");
  const itemFields = ["chatterItems", "chatterNotes", "chatter", "feedItems", "feedElements", "commentItems", "comments", "salesforceComments", "caseComments"];
  const items = itemFields.flatMap((field) => Array.isArray(ticket[field]) ? ticket[field] : []);
  const itemText = items.map(formatChatterItem).filter(Boolean).join("\n\n");
  return [direct, itemText].filter(Boolean).join("\n\n").trim();
}

function stringNoteValue(value) {
  if (typeof value !== "string") return "";
  return value.trim();
}

function formatChatterItem(item) {
  if (!item) return "";
  if (typeof item === "string") return item.trim();
  const author = item.author || item.createdBy || item.createdByName || item.user || item.actor || "";
  const when = formatCompactDate(item.createdAt || item.createdDate || item.date || item.timestamp || "");
  const body = item.body || item.text || item.comment || item.message || item.summary || "";
  const prefix = [when, author].filter(Boolean).join(" - ");
  return [prefix, String(body || "").trim()].filter(Boolean).join(": ");
}

function ticketAgentNotesContext(ticket) {
  const notes = ticketNotesText(ticket)
    .replace(/\n--- Chat log ---[\s\S]*?(?=\n\nSalesforce Chatter \/ Comments:|$)/i, "\n--- Chat log omitted from dispatch prompt; open the ticket/dashboard if needed. ---")
    .trim();
  return truncateLongText(notes, 7000);
}

function boardLaneForTicket(ticket, sourceLane) {
  if (isBillingTicket(ticket)) return "billing";
  if (isSupportTicket(ticket)) return "support";
  if (sourceLane === "review" && ticket?.needsReview === true) return "review";
  return "support";
}

function ticketFromDispatchJob(job, staticTicket) {
  const payload = job?.payload || {};
  const ticketNumber = getJobTicketNumber(job) || ticketIdentity(staticTicket) || jobIdentity(job) || String(job?.id || "").trim();
  const agentKey = uiAgentForJob(job);
  const agentLabel = payload.agentLabel || labelForAgent(agentKey) || job?.agentName || "Agent";
  const status = String(job?.status || "queued");
  const instruction = String(payload.instruction || "").trim();
  if (isBoardTaskJob(job)) {
    const taskTitle = payload.taskTitle || describeJobTarget(job) || truncateText(instruction, 80) || "General task";
    const taskId = payload.taskId || ticketNumber || String(job?.id || "").trim();
    const taskNote = [
      "Command Center General Task",
      `Agent: ${agentLabel}`,
      `Status: ${status}`,
      job?.id ? `Job: ${job.id}` : "",
      `Source: ${sourceTypeLabel(job)}`,
      `Task: ${taskTitle}`,
      instruction ? `Operator instruction: ${instruction}` : "",
      payload.outputPath ? `Output cache: ${payload.outputPath}` : "",
    ].filter(Boolean).join("\n");
    return {
      id: taskId,
      number: taskId,
      taskId,
      isGeneralTask: true,
      account: isOperationalTaskJob(job) ? "Background ops job" : "General task",
      mainIssue: taskTitle,
      technicalIssue: payload.taskCategory || sourceTypeLabel(job) || "Ops / non-ticket work",
      openedBy: "Darius",
      owner: agentLabel,
      url: "",
      lane: "progress",
      assignedAgent: agentKey,
      assignedAgentLabel: agentLabel,
      jobId: job?.id || "",
      jobStatus: status,
      priority: "Task",
      recordType: "General Task",
      notesPreview: `${agentLabel} ${status === "running" ? "is working" : "has queued work"} - ${taskTitle}`,
      notesFull: taskNote,
    };
  }
  const assignmentNote = [
    `Command Center Assignment`,
    `Agent: ${agentLabel}`,
    `Status: ${status}`,
    job?.id ? `Job: ${job.id}` : "",
    instruction ? `Operator instruction: ${instruction}` : "",
  ].filter(Boolean).join("\n");
  return {
    ...(staticTicket || {}),
    id: staticTicket?.id || ticketNumber,
    number: ticketNumber,
    account: payload.account || staticTicket?.account || "No account linked",
    mainIssue: payload.mainIssue || staticTicket?.mainIssue || "Assigned command-center task",
    technicalIssue: payload.technicalIssue || staticTicket?.technicalIssue || "Agent work in progress",
    openedBy: payload.openedBy || staticTicket?.openedBy || "Unknown",
    owner: agentLabel,
    url: payload.salesforceUrl || payload.url || staticTicket?.url || "",
    lane: "progress",
    assignedAgent: agentKey,
    assignedAgentLabel: agentLabel,
    jobId: job?.id || "",
    jobStatus: status,
    notesPreview: `${agentLabel} ${status === "running" ? "is working" : "has queued work"}${instruction ? ` - ${instruction}` : ""}`,
    notesFull: `${staticTicket ? `${ticketNotesText(staticTicket)}\n\n` : ""}${assignmentNote}`,
  };
}

function ticketFromReviewPacket(packet) {
  const ticketNumber = String(packet?.ticketNumber || packet?.number || "").trim();
  const staticTicket = getStaticTicket(ticketNumber);
  const agentKey = uiAgentForJob({ agentName: packet?.agentName, payload: packet });
  const agentLabel = labelForAgent(agentKey) || packet?.agentLabel || packet?.agentName || "Agent";
  const agentResult = String(packet?.agentResult || "").trim();
  const followupResult = String(packet?.lastFollowupResult || "").trim();
  const operatorAction = String(packet?.operatorAction || "").trim();
  const notesContext = String(packet?.notesContext || "").trim();
  const notesFull = [
    "Command Center Review Packet",
    `Packet: ${packet?.id || "unknown"}`,
    `Agent: ${agentLabel}`,
    `Status: ${packet?.status || "needs_review"}`,
    operatorAction ? `Decision needed: ${operatorAction}` : "",
    agentResult ? "\nFinding and recommendation:" : "",
    agentResult,
    followupResult && followupResult !== agentResult ? "\nLatest follow-up result:" : "",
    followupResult && followupResult !== agentResult ? followupResult : "",
    notesContext ? "\nTicket notes / Chatter context:" : "",
    notesContext,
  ].filter((line) => line !== "").join("\n");
  return {
    ...(staticTicket || {}),
    id: ticketNumber || packet?.id || "",
    number: ticketNumber || packet?.id || "",
    isReviewPacket: true,
    packetId: packet?.id || "",
    packet,
    account: packet?.account || staticTicket?.account || "No account linked",
    mainIssue: packet?.mainIssue || staticTicket?.mainIssue || "Review packet",
    technicalIssue: packet?.technicalIssue || staticTicket?.technicalIssue || "Agent reply awaiting review",
    openedBy: packet?.openedBy || staticTicket?.openedBy || "Unknown",
    owner: agentLabel,
    url: packet?.salesforceUrl || packet?.url || staticTicket?.url || "",
    lane: "review",
    needsReview: true,
    priority: "Review",
    recordType: staticTicket?.recordType || "Review Packet",
    daysActive: Number(staticTicket?.daysActive) || 0,
    assignedAgent: agentKey,
    assignedAgentLabel: agentLabel,
    notesPreview: operatorAction
      ? `${agentLabel} needs a decision - ${truncateText(operatorAction, 110)}`
      : `${agentLabel} research ready${agentResult ? ` - ${truncateText(agentResult, 110)}` : ""}`,
    notesFull,
  };
}

function buildBoardColumns() {
  const staticColumns = getStaticColumns();
  const activeTickets = [];
  const activeTicketNumbers = new Set();
  const seenJobsByTicket = new Set();
  const activeJobs = state.activeJobs.filter(isActiveDispatchJob);
  const reviewPacketTickets = state.reviewPackets.map(ticketFromReviewPacket).filter((ticket) => ticket.number);
  const reviewPacketTicketNumbers = new Set(reviewPacketTickets.map((ticket) => ticketIdentity(ticket)).filter(Boolean));

  for (const job of activeJobs) {
    const boardIdentity = jobBoardIdentity(job);
    if (!boardIdentity || seenJobsByTicket.has(boardIdentity)) continue;
    const ticketNumber = getJobTicketNumber(job);
    const staticTicket = getStaticTicket(ticketNumber);
    const payloadTicket = job?.payload || {};
    if (isBoardTaskJob(job)) {
      seenJobsByTicket.add(boardIdentity);
      activeTickets.push(ticketFromDispatchJob(job, null));
      continue;
    }
    if ((staticTicket && !isBoardEligibleTicket(staticTicket)) || (!staticTicket && !isBoardEligibleTicket(payloadTicket))) continue;
    seenJobsByTicket.add(boardIdentity);
    activeTicketNumbers.add(ticketNumber);
    activeTickets.push(ticketFromDispatchJob(job, staticTicket));
  }

  const visibleTicketsByLane = new Map(staticColumns.map((column) => [column.key, []]));

  for (const column of staticColumns) {
    if (column.key === "progress") continue;
    for (const ticket of column.tickets || []) {
      if (activeTicketNumbers.has(ticketIdentity(ticket)) || reviewPacketTicketNumbers.has(ticketIdentity(ticket)) || !isBoardEligibleTicket(ticket)) continue;
      const laneKey = boardLaneForTicket(ticket, column.key);
      if (!visibleTicketsByLane.has(laneKey)) visibleTicketsByLane.set(laneKey, []);
      visibleTicketsByLane.get(laneKey).push({ ...ticket, lane: laneKey });
    }
  }
  visibleTicketsByLane.set("review", [...reviewPacketTickets, ...(visibleTicketsByLane.get("review") || [])]);

  const columns = staticColumns.map((column) => {
    if (column.key === "progress") {
      return { ...column, count: activeTickets.length, tickets: activeTickets };
    }
    const tickets = visibleTicketsByLane.get(column.key) || [];
    return { ...column, count: tickets.length, tickets };
  });

  if (!columns.some((column) => column.key === "progress")) {
    columns.splice(2, 0, {
      key: "progress",
      label: "Assigned / In Progress",
      count: activeTickets.length,
      tickets: activeTickets,
    });
  }
  return columns;
}

function rebuildBoardColumns() {
  state.boardColumns = buildBoardColumns();
  return state.boardColumns;
}

function getBoardColumns() {
  return state.boardColumns.length ? state.boardColumns : rebuildBoardColumns();
}

function getAllTickets() {
  const seen = new Set();
  return getBoardColumns().flatMap((column) => column.tickets || []).filter((ticket) => {
    const id = ticketIdentity(ticket);
    if (!id || seen.has(id)) return false;
    seen.add(id);
    return true;
  });
}

function findTicket(number) {
  const normalized = String(number || "").trim();
  return getAllTickets().find((ticket) => ticketIdentity(ticket) === normalized) || getStaticTicket(normalized);
}

function renderStats() {
  const columns = rebuildBoardColumns();
  const tickets = getAllTickets();
  const realTickets = tickets.filter((ticket) => !ticket.isGeneralTask);
  const progress = columns.find((column) => column.key === "progress")?.count || 0;
  const review = columns.find((column) => column.key === "review")?.count || 0;
  document.querySelector("#openCount").textContent = String(realTickets.length);
  document.querySelector("#progressCount").textContent = String(progress);
  document.querySelector("#reviewCount").textContent = String(review);
  document.querySelector("#staleCount").textContent = String(realTickets.filter((ticket) => Number(ticket.daysActive) >= 3).length);
  document.querySelector("#snapshotTime").textContent = formatSnapshotTime(data.generatedAt);
  updateTicketSyncStatus();
}

function truncateText(value, limit = 160) {
  const text = String(value ?? "").replace(/\s+/g, " ").trim();
  return text.length > limit ? `${text.slice(0, Math.max(0, limit - 3))}...` : text;
}

function truncateLongText(value, limit = 7000) {
  const text = String(value ?? "").trim();
  if (text.length <= limit) return text;
  return `${text.slice(0, Math.max(0, limit - 80)).trimEnd()}\n\n[Context trimmed in dashboard dispatch prompt.]`;
}

function jobAgentName(job) {
  const payload = job?.payload || {};
  return String(job?.agentName || payload.agentName || dispatchAgentMap[String(payload.agent || "").toLowerCase()] || "").trim();
}

function jobSourceType(job) {
  return String(job?.sourceType || job?.payload?.type || "").trim();
}

function sourceTypeLabel(job) {
  const sourceType = jobSourceType(job);
  if (sourceType === "dispatch" && isGeneralTaskJob(job)) return "General task";
  const labels = {
    dispatch: "Ticket dispatch",
    "review-packet-continue": "Packet follow-up",
    "review-packet-close": "Packet close",
    "ops-email-watch": "Mail watch",
    "ops-email-send": "Mail send",
    "ops-email-mark-read": "Mail read",
    "ops-schedule": "Schedule watch",
    "ops-ticket-refresh": "Ticket refresh",
    "ops-kpi-dashboard": "KPI dashboard",
    "ops-singapore-ftp": "Singapore FTP",
    "agent-direct-chat": "Direct chat",
  };
  return labels[sourceType] || sourceType || "Command-center job";
}

function describeJobTarget(job) {
  const payload = job?.payload || {};
  if (isGeneralTaskJob(job)) return `Task ${payload.taskTitle || payload.taskId || job?.id || ""}`.trim();
  const ticketNumber = getJobTicketNumber(job);
  if (ticketNumber) return `Ticket ${ticketNumber}`;
  if (payload.subject) return String(payload.subject);
  if (payload.dashboardHint) return String(payload.dashboardHint);
  if (payload.type) return sourceTypeLabel(job);
  if (payload.outputPath) return String(payload.outputPath).split(/[\\/]/).pop() || sourceTypeLabel(job);
  return sourceTypeLabel(job);
}

function jobInstructionText(job) {
  const payload = job?.payload || {};
  return (
    payload.instruction ||
    payload.taskTitle ||
    payload.prompt ||
    payload.dashboardHint ||
    payload.type ||
    job?.prompt ||
    ""
  );
}

function describeJobActivity(job) {
  const status = normalizedJobStatus(job);
  if (status === "queued") return `${sourceTypeLabel(job)} is queued.`;
  if (status === "running") return `${sourceTypeLabel(job)} is running.`;
  if (status === "failed") return truncateText(job?.error || `${sourceTypeLabel(job)} failed.`, 220);
  if (["completed", "completed_with_issues", "blocked", "unclassified", "interrupted", "recovery_review_required"].includes(status)) {
    return truncateText(job?.result || job?.reviewReason || `${sourceTypeLabel(job)} requires review.`, 220);
  }
  return `${sourceTypeLabel(job)} status: ${status || "unknown"}.`;
}

function describeJobNote(job) {
  const instruction = truncateText(jobInstructionText(job), 220);
  if (instruction) return instruction;
  const updated = jobTimestamp(job);
  return updated ? `Last update ${formatTimeAgo(updated)}.` : "No job note available.";
}

function activityColorForStatus(status, fallback = "cyan") {
  if (status === "running" || status === "queued") return "orange";
  if (status === "completed") return "green";
  if (status === "completed_with_issues") return "orange";
  if (["blocked", "failed", "recovery_review_required"].includes(status)) return "red";
  if (["unclassified", "interrupted"].includes(status)) return "orange";
  return fallback;
}

function operatorDecisionFromResult(result) {
  const lines = String(result || "").split(/\r?\n/);
  const nonempty = lines.map((line) => line.trim()).filter(Boolean);
  if (!nonempty.length) return "";
  const match = nonempty[nonempty.length - 1].match(/^OPERATOR_ACTION_REQUIRED\s*:\s*(.*?)\s*$/i);
  if (!match) return "";
  const action = String(match[1] || "").trim();
  return ["", "none", "no", "not_required", "not required"].includes(action.toLowerCase()) ? "" : action;
}

function operatorDecisionFromJob(job) {
  const reviewStatus = String(job?.reviewStatus || "").trim().toLowerCase();
  if (reviewStatus && inactiveDecisionStatuses.has(reviewStatus)) return "";
  if (job?.activeFollowupJobId && ["queued", "running"].includes(String(job?.activeFollowupStatus || "").toLowerCase())) {
    return "";
  }
  const direct = String(job?.operatorAction || "").trim();
  if (job?.operatorActionRequired === true && direct) return direct;
  if (job?.needsReview !== true) return "";
  return operatorDecisionFromResult(job?.result);
}

function agentDecisionRequest(agentKey) {
  const agentName = dispatchAgentMap[agentKey];
  if (!agentName) return "";
  const packet = (state.reviewPackets || []).find((item) => {
    const packetStatus = String(item?.status || "").trim().toLowerCase();
    const followupStatus = String(item?.activeFollowupStatus || "").trim().toLowerCase();
    const action = String(item?.operatorAction || "").trim();
    return String(item?.agentName || "").trim() === agentName
      && !inactiveDecisionStatuses.has(packetStatus)
      && !["queued", "running"].includes(followupStatus)
      && item?.operatorActionRequired === true
      && Boolean(action);
  });
  if (packet) return String(packet.operatorAction || "").trim();
  const jobs = sortJobsNewestFirst(state.activityJobs || []);
  const job = jobs.find((item) => jobAgentName(item) === agentName && Boolean(operatorDecisionFromJob(item)));
  return job ? operatorDecisionFromJob(job) : "";
}

function agentHasActiveJob(agentKey) {
  const agentName = dispatchAgentMap[agentKey];
  return Boolean(agentName) && (state.activityJobs || []).some(
    (job) => jobAgentName(job) === agentName && activeJobStatuses.has(normalizedJobStatus(job))
  );
}

function currentAgentActivityItems() {
  const jobs = sortJobsNewestFirst(state.activityJobs || []);
  return agentRoster.map((agent) => {
    const agentJobs = jobs.filter((job) => jobAgentName(job) === agent.agentName);
    const currentJob = agentJobs.find((job) => activeJobStatuses.has(normalizedJobStatus(job)));
    const decision = currentJob ? "" : agentDecisionRequest(agent.key);
    const latestJob = currentJob || agentJobs[0];
    if (decision) {
      return {
        agent: agent.label,
        key: agent.key,
        state: "waiting",
        color: "purple",
        workingOn: "Waiting on Darius",
        activity: truncateText(decision, 220),
        reasoning: "A specific operator decision is required before this agent can continue.",
        updatedAt: jobTimestamp(latestJob),
        jobId: jobIdentity(latestJob),
        decisionPending: true,
        decision,
      };
    }
    if (!latestJob) {
      return {
        agent: agent.label,
        key: agent.key,
        state: state.activityJobsLoaded ? "idle" : "unavailable",
        color: state.activityJobsLoaded ? agent.color : "red",
        workingOn: state.activityJobsLoaded ? "No current command-center job" : "Gateway activity not connected",
        activity: state.activityJobsLoaded ? "Waiting for the next queued task." : "Live activity has not loaded from the gateway.",
        reasoning: state.activityJobsLoaded ? "No queued or running job for this agent." : "Start or restart the command-center gateway when ready.",
        updatedAt: "",
      };
    }
    const status = normalizedJobStatus(latestJob);
    const active = Boolean(currentJob);
    return {
      agent: agent.label,
      key: agent.key,
      state: active ? status : status === "completed" ? "complete" : status,
      color: activityColorForStatus(status, agent.color),
      workingOn: `${active ? "Current" : "Latest"}: ${describeJobTarget(latestJob)}`,
      activity: describeJobActivity(latestJob),
      reasoning: describeJobNote(latestJob),
      updatedAt: jobTimestamp(latestJob),
      jobId: jobIdentity(latestJob),
      decisionPending: false,
    };
  });
}

function ticketDataIsUsable(candidate) {
  return Boolean(candidate && Array.isArray(candidate.columns) && candidate.columns.length);
}

function applyTicketSnapshot(body) {
  if (!ticketDataIsUsable(body)) return false;
  const updated = isTicketDataNewerThan(body, state.ticketRefreshRequestedAt);
  const fingerprint = stableDataFingerprint({
    columns: body.columns,
    analytics: body.analytics || {},
    agentActivity: body.agentActivity || [],
    updatedAtUtc: body.updatedAtUtc || body.generatedAtUtc || "",
  });
  if (fingerprint !== state.ticketDataFingerprint) {
    state.ticketDataFingerprint = fingerprint;
    applyTicketData(body);
  }
  if (state.ticketRefreshQueued && updated) {
    finishTicketRefresh("Ticket board updated from Salesforce cache.");
  }
  return true;
}

async function loadTicketData(options = {}) {
  try {
    const response = await fetch(ticketsEndpoint, { method: "GET" });
    const body = await response.json();
    if (!response.ok || body.ok === false) {
      throw new Error(body.message || response.statusText);
    }
    if (applyTicketSnapshot(body)) return true;
    if (!options.silent) {
      updateTicketSyncStatus("No live ticket cache yet. Using static snapshot.");
    }
  } catch (error) {
    if (!options.silent) {
      updateTicketSyncStatus(`Gateway unavailable. Using static snapshot. ${error?.message || ""}`.trim());
    }
  }
  return false;
}

async function requestTicketRefresh() {
  updateTicketRefreshButton(true);
  state.ticketRefreshQueued = true;
  state.ticketRefreshRequestedAt = new Date().toISOString();
  updateTicketSyncStatus("Queueing ticket refresh...");
  try {
    const response = await fetch(ticketRefreshEndpoint, { method: "POST" });
    const body = await response.json().catch(() => ({}));
    if (!response.ok || body.accepted === false) {
      throw new Error(body.message || response.statusText);
    }
    if (body.completed === true) {
      await loadTicketData({ silent: true });
      finishTicketRefresh(`Ticket board refreshed from Salesforce (${Number(body.total || 0)} open).`);
      showToast(`Ticket refresh completed: ${Number(body.total || 0)} open ticket(s).`);
      return;
    }
    showToast(`Ticket refresh queued: ${body.job_id || body.bridge_job_id || "job"}.`);
    updateTicketSyncStatus("Refresh queued. Waiting for the Salesforce cache to update.");
    startTicketRefreshPolling();
  } catch (error) {
    state.ticketRefreshQueued = false;
    updateTicketRefreshButton(false);
    updateTicketSyncStatus(`Ticket refresh not queued: ${error?.message || "gateway unavailable"}.`);
    showToast(`Ticket refresh not queued: ${error?.message || "gateway unavailable"}.`);
  }
}

function applyTicketData(nextData) {
  data = {
    ...staticTicketData,
    ...nextData,
    agentActivity: Array.isArray(nextData.agentActivity) && nextData.agentActivity.length
      ? nextData.agentActivity
      : staticTicketData.agentActivity || [],
    analytics: nextData.analytics || staticTicketData.analytics || {},
  };
  state.boardColumns = [];
  renderStats();
  renderAgentList();
  renderKanban();
  renderAnalytics();
  if (state.selectedTicket) {
    const selected = findTicket(ticketIdentity(state.selectedTicket));
    if (selected) selectTicket(selected);
    else clearSelectedTicket({ keepInstruction: true, keepTaskTitle: true });
  }
}

function stableDataFingerprint(value) {
  try {
    return stableHash(JSON.stringify(value));
  } catch {
    return "";
  }
}

function startTicketRefreshPolling() {
  window.clearInterval(state.ticketRefreshPollTimer);
  state.ticketRefreshPollsRemaining = 20;
  state.ticketRefreshPollTimer = window.setInterval(async () => {
    state.ticketRefreshPollsRemaining -= 1;
    await loadTicketData({ silent: true });
    if (!state.ticketRefreshQueued || state.ticketRefreshPollsRemaining <= 0) {
      window.clearInterval(state.ticketRefreshPollTimer);
      state.ticketRefreshPollTimer = null;
      if (state.ticketRefreshQueued) {
        state.ticketRefreshQueued = false;
        updateTicketRefreshButton(false);
        updateTicketSyncStatus("Refresh is still running or did not update the cache yet. Auto-sync will keep checking.");
      }
    }
  }, ticketRefreshPollMs);
}

function finishTicketRefresh(message) {
  state.ticketRefreshQueued = false;
  state.ticketRefreshRequestedAt = "";
  window.clearInterval(state.ticketRefreshPollTimer);
  state.ticketRefreshPollTimer = null;
  updateTicketRefreshButton(false);
  updateTicketSyncStatus(message);
}

function updateTicketRefreshButton(syncing = state.ticketRefreshQueued) {
  if (!ticketRefresh) return;
  ticketRefresh.disabled = Boolean(syncing);
  ticketRefresh.classList.toggle("syncing", Boolean(syncing));
  ticketRefresh.textContent = syncing ? "SYNCING" : "SYNC";
}

function updateTicketSyncStatus(message = "") {
  if (!ticketSyncStatus) return;
  const liveCounts = getBoardColumns()
    .filter((column) => ["support", "billing", "review"].includes(column.key))
    .map((column) => `${column.label} ${Number(column.count || 0)}`)
    .join(" · ");
  if (message) {
    ticketSyncStatus.textContent = liveCounts ? `${message} ${liveCounts}.` : message;
    return;
  }
  const timestamp = syncTimestampForData(data);
  if (state.ticketRefreshQueued) {
    ticketSyncStatus.textContent = timestamp
      ? `Refresh queued. Current cache ${formatTimeAgo(timestamp)}.`
      : "Refresh queued. Waiting for first live ticket cache.";
    return;
  }
  if (timestamp) {
    const source = data === staticTicketData ? "Static snapshot" : "Live cache";
    ticketSyncStatus.textContent = `${source} synced ${formatTimeAgo(timestamp)}.${liveCounts ? ` ${liveCounts}.` : ""}`;
    return;
  }
  ticketSyncStatus.textContent = "No ticket sync loaded.";
}

function applyKpiDashboardSnapshot(body) {
  if (!body || body.ok === false) return false;
  state.kpiDashboard = body;
  if (state.kpiRefreshQueued && isKpiDashboardNewerThan(body, state.kpiRefreshRequestedAt)) {
    finishKpiRefresh("KPI cache updated from Google dashboard.");
  } else {
    updateKpiStatus();
  }
  renderAnalytics();
  return true;
}

async function loadKpiDashboard(options = {}) {
  try {
    const response = await fetch(kpiDashboardEndpoint, { method: "GET" });
    const body = await response.json();
    if (!response.ok || body.ok === false) {
      throw new Error(body.message || response.statusText);
    }
    applyKpiDashboardSnapshot(body);
  } catch (error) {
    if (!options.silent) {
      updateKpiStatus(`KPI cache unavailable: ${error?.message || "gateway unavailable"}.`);
    }
    renderAnalytics();
  }
}

async function requestKpiRefresh() {
  updateKpiRefreshButton(true);
  state.kpiRefreshQueued = true;
  state.kpiRefreshRequestedAt = new Date().toISOString();
  updateKpiStatus("Queueing KPI dashboard refresh...");
  try {
    const response = await fetch(kpiDashboardRefreshEndpoint, { method: "POST" });
    const body = await response.json().catch(() => ({}));
    if (!response.ok || body.accepted === false) {
      throw new Error(body.message || response.statusText);
    }
    showToast(`KPI refresh queued: ${body.job_id || body.bridge_job_id || "job"}.`);
    updateKpiStatus("KPI refresh queued. Analytics will update when the cache is written.");
    startKpiRefreshPolling();
  } catch (error) {
    state.kpiRefreshQueued = false;
    updateKpiRefreshButton(false);
    updateKpiStatus(`KPI refresh not queued: ${error?.message || "gateway unavailable"}.`);
    showToast(`KPI refresh not queued: ${error?.message || "gateway unavailable"}.`);
  }
}

function startKpiRefreshPolling() {
  window.clearInterval(state.kpiRefreshPollTimer);
  state.kpiRefreshPollsRemaining = 24;
  state.kpiRefreshPollTimer = window.setInterval(async () => {
    state.kpiRefreshPollsRemaining -= 1;
    await loadKpiDashboard({ silent: true });
    if (!state.kpiRefreshQueued || state.kpiRefreshPollsRemaining <= 0) {
      window.clearInterval(state.kpiRefreshPollTimer);
      state.kpiRefreshPollTimer = null;
      if (state.kpiRefreshQueued) {
        state.kpiRefreshQueued = false;
        updateKpiRefreshButton(false);
        updateKpiStatus("KPI refresh is still running or has not written the cache yet. Background sync will keep checking.");
      }
    }
  }, kpiRefreshPollMs);
}

function finishKpiRefresh(message) {
  state.kpiRefreshQueued = false;
  state.kpiRefreshRequestedAt = "";
  window.clearInterval(state.kpiRefreshPollTimer);
  state.kpiRefreshPollTimer = null;
  updateKpiRefreshButton(false);
  updateKpiStatus(message);
}

function updateKpiRefreshButton(syncing = state.kpiRefreshQueued) {
  if (!kpiRefresh) return;
  kpiRefresh.disabled = Boolean(syncing);
  kpiRefresh.classList.toggle("syncing", Boolean(syncing));
  kpiRefresh.textContent = syncing ? "SYNCING" : "SYNC KPI";
}

function updateKpiStatus(message = "") {
  if (!kpiStatus) return;
  if (message) {
    kpiStatus.textContent = message;
    return;
  }
  const dashboard = state.kpiDashboard || {};
  if (state.kpiRefreshQueued) {
    kpiStatus.textContent = dashboard.updatedAtUtc
      ? `KPI refresh queued. Current cache ${formatTimeAgo(dashboard.updatedAtUtc)}.`
      : "KPI refresh queued. Waiting for first cache.";
    return;
  }
  if (dashboard.updatedAtUtc) {
    const source = kpiSourceLabel(dashboard);
    kpiStatus.textContent = `${source} synced ${formatTimeAgo(dashboard.updatedAtUtc)}.`;
    return;
  }
  kpiStatus.textContent = "No Google KPI dashboard cache loaded.";
}

function isKpiDashboardNewerThan(candidate, isoTimestamp) {
  if (!isoTimestamp) return true;
  const nextTime = new Date(candidate?.updatedAtUtc || "").getTime();
  const requestedTime = new Date(isoTimestamp).getTime();
  return Number.isFinite(nextTime) && Number.isFinite(requestedTime) && nextTime >= requestedTime;
}

function kpiSourceLabel(dashboard) {
  const source = dashboard?.source;
  if (typeof source === "string") return source || "KPI cache";
  return source?.name || "KPI cache";
}

function syncTimestampForData(ticketData) {
  return ticketData?.updatedAtUtc || ticketData?.generatedAt || "";
}

function isTicketDataNewerThan(candidate, isoTimestamp) {
  if (!isoTimestamp) return true;
  const nextTime = new Date(syncTimestampForData(candidate)).getTime();
  const requestedTime = new Date(isoTimestamp).getTime();
  return Number.isFinite(nextTime) && Number.isFinite(requestedTime) && nextTime >= requestedTime;
}

function formatTimeAgo(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "at unknown time";
  const seconds = Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000));
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ${minutes % 60}m ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function preserveScrollPositions(callback) {
  const positions = captureScrollPositions();
  const result = callback();
  restoreScrollPositions(positions);
  window.requestAnimationFrame(() => restoreScrollPositions(positions));
  return result;
}

function captureScrollPositions() {
  const positions = new Map();
  trackedScrollElements().forEach((element, index) => {
    const key = scrollElementKey(element, index);
    if (!key) return;
    positions.set(key, {
      top: element.scrollTop,
      left: element.scrollLeft,
    });
  });
  return positions;
}

function restoreScrollPositions(positions) {
  if (!positions?.size) return;
  trackedScrollElements().forEach((element, index) => {
    const key = scrollElementKey(element, index);
    const position = positions.get(key);
    if (!position) return;
    element.scrollTop = Math.min(position.top, Math.max(0, element.scrollHeight - element.clientHeight));
    element.scrollLeft = Math.min(position.left, Math.max(0, element.scrollWidth - element.clientWidth));
  });
}

function trackedScrollElements() {
  return [
    ...document.querySelectorAll(".lane-body"),
    document.querySelector(".detail-panel"),
    document.querySelector("#detailNotes"),
    document.querySelector("#emailWatchList"),
    document.querySelector("#emailPageList"),
    document.querySelector("#meetingList"),
    document.querySelector("#activityGrid"),
    document.querySelector("#analyticsMetrics"),
    document.querySelector("#kpiSections"),
  ].filter(Boolean);
}

function scrollElementKey(element, index) {
  if (element.dataset?.dropLane) return `lane:${element.dataset.dropLane}`;
  if (element.id) return `id:${element.id}`;
  return `scroll:${index}`;
}

function renderAgentList() {
  const items = currentAgentActivityItems();
  agentList.innerHTML = items.map((item) => `
    <button class="agent-row ${["waiting", "queued", "running", "blocked", "completed_with_issues", "failed", "interrupted", "recovery_review_required", "unclassified"].includes(item.state) ? "warning" : ""} ${state.agentChatAgent === item.key && state.agentChatOpen ? "active" : ""}" data-agent-link="${escapeText(item.key)}">
      <span class="avatar ${escapeText(item.key)}">${escapeText(item.agent[0])}</span>
      <span><strong>${escapeText(item.agent)}</strong><small>${escapeText(String(item.state).toUpperCase())}</small></span>
      <span class="agent-row-tail">
        ${item.decisionPending ? `<b class="agent-decision-icon" title="${escapeText(item.decision || "Waiting for Darius")}">?</b>` : ""}
        ${unreadAgentChatCount(item.key) ? `<em>${unreadAgentChatCount(item.key)}</em>` : ""}
        <i class="${escapeText(item.color)}"></i>
      </span>
    </button>
  `).join("");
  agentList.querySelectorAll("[data-agent-link]").forEach((button) => {
    button.addEventListener("click", () => openAgentChat(button.dataset.agentLink));
  });
}

function ticketCard(ticket) {
  const priorityClass = String(ticket.priority || "Low").toLowerCase();
  return `
    <article class="ticket-card ${ticket.lane === "billing" ? "billing-card" : "support-card"} ${ticket.isReviewPacket ? "review-packet-card" : ""}" draggable="true" data-ticket-id="${escapeText(ticket.number)}">
      <div class="card-top">
        <strong>${escapeText(ticket.number)}</strong>
        <span class="age-pill">${ticket.isReviewPacket ? "PACKET" : `${Number(ticket.daysActive) || 0}d`}</span>
      </div>
      <h3>${escapeText(ticket.account || "No account linked")}</h3>
      <p class="issue-line">${escapeText(ticket.mainIssue || "Unclassified")}</p>
      <p class="tech-line">${escapeText(ticket.technicalIssue || "No technical issue selected")}</p>
      <button class="notes-hover" type="button" data-ticket-id="${escapeText(ticket.number)}">
        <span>Notes</span>
        <em>${escapeText(ticket.notesPreview || "No notes recorded.")}</em>
      </button>
      <footer>
        <span class="badge ${priorityClass}">${escapeText(ticket.priority || "Low")}</span>
        <span class="badge opened-by">${escapeText(ticket.openedBy || "Unknown")}</span>
        ${ticket.assignedAgentLabel ? `<span class="badge opened-by">${escapeText(ticket.assignedAgentLabel)}</span>` : ""}
      </footer>
    </article>
  `;
}

function renderKanban() {
  preserveScrollPositions(() => {
    const columns = rebuildBoardColumns();
    const selectedTicketNumber = ticketIdentity(state.selectedTicket);
    kanbanBoard.innerHTML = columns.map((column) => `
      <section class="lane ${laneTheme[column.key] || ""}" data-lane="${escapeText(column.key)}">
        <header><h2>${escapeText(column.label)}</h2><span>${Number(column.count) || 0}</span></header>
        <div class="lane-body" data-drop-lane="${escapeText(column.key)}">
          ${(column.tickets || []).map(ticketCard).join("")}
          <div class="drop-hint">${escapeText(dropHintForLane(column.key))}</div>
        </div>
      </section>
    `).join("");

    document.querySelectorAll(".ticket-card[draggable='true']").forEach(wireCard);
    document.querySelectorAll(".notes-hover").forEach(wireNotesHover);
    document.querySelectorAll("[data-drop-lane]").forEach(wireLaneDrop);

    if (selectedTicketNumber) {
      const selected = findTicket(selectedTicketNumber);
      if (selected) {
        selectTicket(selected);
        return;
      }
      state.selectedTicket = null;
    }
    if (!state.selectionClearedByUser) {
      const firstTicket = getAllTickets()[0];
      if (firstTicket) selectTicket(firstTicket);
    }
  });
}

function jobIdentity(job) {
  return String(job?.id || job?.bridgeJobId || job?.bridge_job_id || job?.payload?.id || "").trim();
}

function jobTimestamp(job) {
  return job?.completedAtUtc || job?.updatedAtUtc || job?.startedAtUtc || job?.createdAtUtc || job?.payload?.createdAt || "";
}

function sortJobsNewestFirst(jobs) {
  return [...jobs].sort((left, right) => {
    const leftTime = new Date(jobTimestamp(left)).getTime();
    const rightTime = new Date(jobTimestamp(right)).getTime();
    return (Number.isFinite(rightTime) ? rightTime : 0) - (Number.isFinite(leftTime) ? leftTime : 0);
  });
}

function normalizedJobStatus(job) {
  return String(job?.status || "queued").trim().toLowerCase() || "queued";
}

function jobMatchesTicket(job, ticket) {
  const ticketNumber = ticketIdentity(ticket);
  return Boolean(ticketNumber && getJobTicketNumber(job) === ticketNumber);
}

function renderAgentUpdateSummary(errorMessage = "") {
  if (!agentRepliesStatus) return;
  const hideSummary = () => {
    agentRepliesStatus.hidden = true;
    agentRepliesStatus.textContent = "";
    agentRepliesStatus.removeAttribute("data-state");
  };
  const ticket = state.selectedTicket;
  if (!ticket || errorMessage || !state.dispatchJobsLoaded) {
    hideSummary();
    return;
  }

  const jobs = sortJobsNewestFirst(state.dispatchJobs.filter((job) => jobMatchesTicket(job, ticket)));
  if (!jobs.length) {
    hideSummary();
    return;
  }

  const activeCount = jobs.filter((job) => activeJobStatuses.has(normalizedJobStatus(job))).length;
  const completedCount = jobs.filter((job) => normalizedJobStatus(job) === "completed").length;
  const attentionStatuses = new Set(["failed", "blocked", "completed_with_issues", "unclassified", "interrupted"]);
  const attentionCount = jobs.filter((job) => attentionStatuses.has(normalizedJobStatus(job))).length;
  agentRepliesStatus.hidden = false;
  agentRepliesStatus.dataset.state = activeCount ? "active" : attentionCount ? "attention" : "complete";
  agentRepliesStatus.textContent = `${jobs.length} agent update${jobs.length === 1 ? "" : "s"} - ${activeCount} active, ${completedCount} complete${attentionCount ? `, ${attentionCount} needs attention` : ""}.`;
}

function agentKeyForAgentName(agentName) {
  const normalized = String(agentName || "").trim().toLowerCase();
  const found = Object.entries(dispatchAgentMap).find(([, mapped]) => mapped === normalized);
  return found?.[0] || normalized;
}

function agentNameForKey(agentKey) {
  return dispatchAgentMap[String(agentKey || "").toLowerCase()] || String(agentKey || "");
}

function agentChatEvents(agentKey = state.agentChatAgent) {
  const agentName = agentNameForKey(agentKey);
  return (state.agentChatMessages || []).filter((event) => {
    const eventAgent = String(event.agentName || "").trim().toLowerCase();
    return eventAgent === agentName.toLowerCase() && isVisibleAgentChatEvent(event);
  });
}

const quietAgentChatSourceTypes = new Set([
  "ops-email-watch",
  "ops-ticket-refresh",
  "ops-kpi-dashboard",
  "ops-schedule",
]);

function isVisibleAgentChatEvent(event) {
  const sourceType = String(event?.sourceType || "").trim().toLowerCase();
  if (!quietAgentChatSourceTypes.has(sourceType)) return true;
  const text = String(event?.text || "");
  return isOperatorNoticeText(text) || isFailureSyncText(text);
}

function isOperatorNoticeText(text) {
  const normalized = String(text || "").toLowerCase();
  return normalized.includes("email_notice:") || normalized.includes("account match needed:");
}

function isFailureSyncText(text) {
  const normalized = String(text || "").toLowerCase();
  return /\b(failed|failure|error|unavailable|blocked|partial|could not|unable to)\b/.test(normalized);
}

function unreadAgentChatCount(agentKey) {
  const agentName = agentNameForKey(agentKey);
  const lastSeen = new Date(state.agentChatLastSeen[agentName] || 0).getTime();
  return agentChatEvents(agentKey).filter((event) => {
    const role = String(event.role || "").toLowerCase();
    if (role === "user") return false;
    const time = new Date(event.atUtc || "").getTime();
    return Number.isFinite(time) && time > lastSeen;
  }).length;
}

function loadAgentChatLastSeen() {
  try {
    const parsed = JSON.parse(readLocalValue(agentChatLastSeenKey) || "{}");
    state.agentChatLastSeen = parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
  } catch {
    state.agentChatLastSeen = {};
  }
}

function saveAgentChatLastSeen() {
  writeLocalValue(agentChatLastSeenKey, JSON.stringify(state.agentChatLastSeen || {}));
}

function markAgentChatSeen(agentKey = state.agentChatAgent) {
  if (!agentKey) return;
  const agentName = agentNameForKey(agentKey);
  const events = agentChatEvents(agentKey);
  const latest = events.map((event) => new Date(event.atUtc || "").getTime()).filter(Number.isFinite).sort((a, b) => b - a)[0];
  state.agentChatLastSeen[agentName] = latest ? new Date(latest).toISOString() : new Date().toISOString();
  saveAgentChatLastSeen();
  renderAgentList();
}

function applyAgentChatSnapshot(body) {
  if (!body || body.ok === false) return false;
  const nextMessages = Array.isArray(body.events) ? body.events : [];
  const nextFingerprint = stableDataFingerprint(nextMessages);
  const changed = nextFingerprint !== state.agentChatFingerprint;
  const wasNearBottom = agentChatIsNearBottom();
  const preservedScrollTop = agentChatMessages?.scrollTop ?? 0;
  state.agentChatMessages = nextMessages;
  state.agentChatFingerprint = nextFingerprint;
  state.agentChatLoaded = true;
  if (!changed) {
    renderAgentList();
    return true;
  }
  if (state.agentChatOpen && state.agentChatAgent && wasNearBottom) {
    state.agentChatScrollToLatest = true;
    markAgentChatSeen(state.agentChatAgent);
  } else if (state.agentChatOpen) {
    state.agentChatPreserveScrollTop = preservedScrollTop;
  }
  renderAgentChat();
  renderAgentList();
  return true;
}

async function loadAgentChat(options = {}) {
  try {
    const response = await fetch(`${agentChatEndpoint}?limit=300`, { method: "GET" });
    const body = await response.json();
    if (!response.ok || body.ok === false) {
      throw new Error(body.message || response.statusText);
    }
    applyAgentChatSnapshot(body);
    return;
  } catch (error) {
    state.agentChatLoaded = false;
    if (!options.silent) {
      showToast(`Agent chat unavailable: ${error?.message || "gateway unavailable"}.`);
    }
  }
  renderAgentChat();
  renderAgentList();
}

function agentChatIsNearBottom() {
  if (!agentChatMessages || !agentChatMessages.scrollHeight) return true;
  return agentChatMessages.scrollHeight - agentChatMessages.scrollTop - agentChatMessages.clientHeight < 32;
}

function openAgentChat(agentKey) {
  if (!agentKey) return;
  if (state.agentChatAgent && state.agentChatAgent !== agentKey && state.agentChatAttachments.length) {
    clearAgentChatAttachments();
  }
  state.agentChatAgent = agentKey;
  state.agentChatOpen = true;
  state.agentChatScrollToLatest = true;
  if (agentChatDrawer) {
    agentChatDrawer.hidden = false;
    agentChatDrawer.setAttribute("aria-hidden", "false");
  }
  renderAgentChat();
  loadAgentChat({ silent: true });
  window.setTimeout(() => agentChatInput?.focus(), 50);
}

function closeAgentChat() {
  state.agentChatOpen = false;
  if (state.agentChatAgent && agentChatIsNearBottom()) {
    markAgentChatSeen(state.agentChatAgent);
  }
  if (agentChatDrawer) {
    agentChatDrawer.setAttribute("aria-hidden", "true");
    agentChatDrawer.hidden = true;
  }
  renderAgentList();
}

function voiceProfileForAgent(agentKey) {
  return agentVoiceProfiles[String(agentKey || "").toLowerCase()] || agentVoiceProfiles.taylor;
}

function renderAgentChatCall() {
  if (!agentChatCall) return;
  const agentKey = state.agentChatAgent || "taylor";
  const label = labelForAgent(agentKey);
  const activeForAgent = voiceRoomIsActive() && state.voiceRoom.agentKey === agentKey;
  agentChatCall.querySelector("strong").textContent = activeForAgent ? "Open call" : `Call ${label}`;
  agentChatCall.title = `${label} always uses the ${voiceProfileForAgent(agentKey).label} voice.`;
}

function cleanAgentChatDisplayText(value) {
  const original = String(value || "").replace(/\r\n/g, "\n").trim();
  if (!original) return "";
  const lines = original.split("\n");
  const kept = [];
  let skippingFileSection = false;
  let legacyDirectChatWrapper = false;

  lines.forEach((line, index) => {
    const trimmed = line.trim();
    const normalized = trimmed.toLowerCase();
    if (index === 0 && /^command center (?:direct|voice) chat\.?$/i.test(trimmed)) {
      legacyDirectChatWrapper = true;
      return;
    }
    if (legacyDirectChatWrapper && /^agent\s*:/i.test(trimmed)) {
      return;
    }
    if (legacyDirectChatWrapper && /^instruction\s*:/i.test(trimmed)) {
      kept.push(trimmed.replace(/^instruction\s*:\s*/i, ""));
      legacyDirectChatWrapper = false;
      return;
    }
    if (!trimmed) {
      skippingFileSection = false;
      kept.push("");
      return;
    }
    if (/^(files changed|file changes|changed files|specific file changes|modified files|updated files)\s*:?\s*$/.test(normalized)) {
      skippingFileSection = true;
      return;
    }
    if (skippingFileSection && /^[-*]\s+/.test(trimmed) && /[\\/].+\.[a-z0-9]{1,8}(\b|:|\))?/i.test(trimmed)) {
      return;
    }
    if (/^(verification|verified|validation|tests?)\b.*\b(passed|pass|ok|successful|success)\b\.?$/i.test(trimmed)) {
      return;
    }
    if (/^[-*]\s*(py -3|pytest|npm test|dotnet test|compileall|ruff|eslint)\b.*\b(passed|pass|ok|successful|success)\b/i.test(trimmed)) {
      return;
    }
    kept.push(line);
  });

  const cleaned = kept.join("\n").replace(/\n{3,}/g, "\n\n").trim();
  return cleaned || original;
}

function formatAgentChatMessageHtml(value) {
  const text = cleanAgentChatDisplayText(value);
  if (!text) return "";
  const blocks = text.split(/\n{2,}/).map((block) => block.trim()).filter(Boolean);
  return blocks.map(formatAgentChatBlockHtml).join("");
}

function formatAgentChatBlockHtml(block) {
  if (/^```/.test(block)) {
    const code = block.replace(/^```[a-z0-9_-]*\s*/i, "").replace(/```$/i, "").trim();
    return `<pre class="agent-chat-code">${escapeText(code)}</pre>`;
  }
  const lines = block.split("\n").map((line) => line.trim()).filter(Boolean);
  if (lines.length > 1 && lines.every((line) => /^[-*]\s+/.test(line))) {
    return `<ul>${lines.map((line) => `<li>${escapeText(line.replace(/^[-*]\s+/, ""))}</li>`).join("")}</ul>`;
  }
  if (lines.length > 1 && lines.every((line) => /^\d+[.)]\s+/.test(line))) {
    return `<ol>${lines.map((line) => `<li>${escapeText(line.replace(/^\d+[.)]\s+/, ""))}</li>`).join("")}</ol>`;
  }
  return `<p>${escapeText(block).replace(/\n/g, "<br>")}</p>`;
}

function renderAgentChatAttachments() {
  if (!agentChatAttachments) return;
  const attachments = state.agentChatAttachments || [];
  agentChatAttachments.innerHTML = attachments.map((item) => {
    const status = item.status === "ready" ? "ready" : item.status === "error" ? "error" : "uploading";
    const statusLabel = item.status === "ready" ? "Ready" : item.status === "error" ? (item.error || "Failed") : "Securing";
    const mimetype = String(item.attachment?.mimetype || item.mimetype || "").toLowerCase();
    const isImage = mimetype.startsWith("image/");
    const preview = isImage
      ? `<img src="${escapeText(item.previewUrl)}" alt="Attachment preview">`
      : `<div class="agent-chat-file-preview"><strong>${escapeText((item.name || "file").split(".").pop()?.toUpperCase() || "FILE")}</strong><span>${escapeText(item.name || "attachment")}</span></div>`;
    return `
      <article class="agent-chat-attachment ${status}" data-client-id="${escapeText(item.clientId)}" data-status="${escapeText(statusLabel)}" title="${escapeText(item.name || "Attachment")}">
        ${preview}
        <button type="button" data-remove-chat-attachment="${escapeText(item.clientId)}" aria-label="Remove ${escapeText(item.name || "attachment")}">×</button>
      </article>
    `;
  }).join("");
}

function removeAgentChatAttachment(clientId) {
  const index = state.agentChatAttachments.findIndex((item) => item.clientId === clientId);
  if (index < 0) return;
  const [removed] = state.agentChatAttachments.splice(index, 1);
  if (removed?.previewUrl) URL.revokeObjectURL(removed.previewUrl);
  renderAgentChat();
}

function clearAgentChatAttachments() {
  (state.agentChatAttachments || []).forEach((item) => {
    if (item.previewUrl) URL.revokeObjectURL(item.previewUrl);
  });
  state.agentChatAttachments = [];
  renderAgentChatAttachments();
}

async function addAgentChatFiles(files) {
  const allowedTypes = new Set([
    "application/json",
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "image/bmp",
    "image/gif",
    "image/jpeg",
    "image/png",
    "image/tiff",
    "image/webp",
    "message/rfc822",
    "text/csv",
    "text/markdown",
    "text/plain",
    "text/tab-separated-values",
  ]);
  const allowedExtensions = new Set(["csv", "docx", "eml", "gif", "jpeg", "jpg", "json", "md", "pdf", "png", "pptx", "tif", "tiff", "tsv", "txt", "webp", "xlsx"]);
  const available = Math.max(0, 5 - state.agentChatAttachments.length);
  const accepted = [...files].filter((file) => {
    const mimetype = String(file.type || "").toLowerCase();
    const extension = String(file.name || "").split(".").pop()?.toLowerCase() || "";
    return allowedTypes.has(mimetype)
      || ((!mimetype || mimetype === "application/octet-stream") && allowedExtensions.has(extension));
  }).slice(0, available);
  if (!available) {
    showToast("A chat message can include up to 5 files.");
    return;
  }
  if (!accepted.length) {
    showToast("Attach a supported PDF, image, text, email, or Office file.");
    return;
  }
  if (accepted.length < files.length) {
    showToast("Only supported files within the 5-file limit were added.");
  }
  accepted.forEach((file, index) => {
    const clientId = globalThis.crypto?.randomUUID?.() || `paste-${Date.now()}-${index}-${stableHash(file.name || file.type)}`;
    const item = {
      clientId,
      name: file.name || `attachment-${Date.now()}`,
      mimetype: file.type || "application/octet-stream",
      previewUrl: String(file.type || "").startsWith("image/") ? URL.createObjectURL(file) : "",
      status: "uploading",
      attachment: null,
      error: "",
    };
    state.agentChatAttachments.push(item);
    uploadAgentChatFile(item, file);
  });
  renderAgentChat();
}

async function uploadAgentChatFile(item, file) {
  if (file.size > 10 * 1024 * 1024) {
    item.status = "error";
    item.error = "Over 10 MB";
    renderAgentChat();
    return;
  }
  try {
    const response = await fetch(`${agentChatAttachmentEndpoint}?name=${encodeURIComponent(item.name)}`, {
      method: "POST",
      headers: { "Content-Type": file.type },
      body: file,
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok || body.ok === false || !body.attachment?.id) {
      throw new Error(body.message || response.statusText);
    }
    const current = state.agentChatAttachments.find((candidate) => candidate.clientId === item.clientId);
    if (!current) return;
    current.status = "ready";
    current.attachment = body.attachment;
    current.error = "";
  } catch (error) {
    const current = state.agentChatAttachments.find((candidate) => candidate.clientId === item.clientId);
    if (!current) return;
    current.status = "error";
    current.error = String(error?.message || "Upload failed").slice(0, 48);
  }
  renderAgentChat();
}

function pasteAgentChatImages(event) {
  const imageFiles = [...(event.clipboardData?.items || [])]
    .filter((item) => item.kind === "file" && String(item.type || "").toLowerCase().startsWith("image/"))
    .map((item) => item.getAsFile())
    .filter(Boolean);
  if (!imageFiles.length) return;
  const pastedText = event.clipboardData?.getData("text/plain") || "";
  event.preventDefault();
  if (pastedText && agentChatInput) {
    const start = agentChatInput.selectionStart ?? agentChatInput.value.length;
    const end = agentChatInput.selectionEnd ?? start;
    agentChatInput.setRangeText(pastedText, start, end, "end");
  }
  addAgentChatFiles(imageFiles);
}

function renderAgentChat() {
  if (!agentChatDrawer || !agentChatMessages || !agentChatTitle || !agentChatStatus) return;
  const agentKey = state.agentChatAgent || "taylor";
  const label = labelForAgent(agentKey);
  const events = agentChatEvents(agentKey);
  agentChatTitle.textContent = `${label} Chat`;
  const latestRole = String(events[events.length - 1]?.role || "").toLowerCase();
  if (state.agentChatSending) {
    agentChatStatus.textContent = "Sending your message...";
  } else if (!state.agentChatLoaded) {
    agentChatStatus.textContent = "Loading conversation.";
  } else if (latestRole === "acknowledgement") {
    agentChatStatus.textContent = "Request received — work is underway.";
  } else {
    agentChatStatus.textContent = "Conversation ready.";
  }
  const shouldStickToBottom = state.agentChatScrollToLatest
    || (state.agentChatPreserveScrollTop === null && agentChatIsNearBottom());
  const preservedScrollTop = state.agentChatPreserveScrollTop ?? agentChatMessages.scrollTop;
  if (!events.length) {
    agentChatMessages.innerHTML = `
      <article class="agent-chat-empty">
        <strong>Start a conversation</strong>
        <span>Send a message and a receipt will appear as soon as it is accepted.</span>
      </article>
    `;
  } else {
    agentChatMessages.innerHTML = events.map((event) => {
      const rawRole = String(event.role || "").toLowerCase();
      const role = rawRole === "assistant" ? "assistant" : rawRole === "acknowledgement" ? "acknowledgement" : "user";
      const returnedFiles = renderAgentChatReturnedFiles(event.attachments || []);
      return `
        <article class="agent-chat-message ${escapeText(role)}">
          <header>
            <span>${escapeText(formatCompactDate(event.atUtc))}</span>
          </header>
          <div class="agent-chat-message-body">${formatAgentChatMessageHtml(event.text || "")}</div>
          ${returnedFiles}
        </article>
      `;
    }).join("");
    if (shouldStickToBottom) {
      agentChatMessages.scrollTop = agentChatMessages.scrollHeight;
    } else if (Number.isFinite(preservedScrollTop)) {
      agentChatMessages.scrollTop = Math.min(
        preservedScrollTop,
        Math.max(0, agentChatMessages.scrollHeight - agentChatMessages.clientHeight),
      );
    }
  }
  state.agentChatScrollToLatest = false;
  state.agentChatPreserveScrollTop = null;
  renderAgentChatCall();
  renderAgentChatAttachments();
  if (agentChatSend) {
    const attachments = state.agentChatAttachments || [];
    const attachmentReady = attachments.length > 0 && attachments.every((item) => item.status === "ready" && item.attachment?.id);
    const attachmentBusy = attachments.some((item) => item.status === "uploading" || item.status === "error");
    const hasContent = Boolean(agentChatInput?.value.trim()) || attachmentReady;
    agentChatSend.disabled = state.agentChatSending || !state.agentChatAgent || !hasContent || attachmentBusy;
    agentChatSend.textContent = state.agentChatSending ? "Sending..." : "Send";
  }
}

function verifiedAgentChatArtifactUrl(item, preview = false) {
  const path = String(item?.downloadUrl || "").trim();
  if (!/^\/agent-chat\/artifacts\/[0-9a-f]{32}$/.test(path)) return "";
  return `${commandCenterBaseUrl}${path}${preview ? "?preview=1" : ""}`;
}

function compactFileSize(value) {
  const bytes = Math.max(0, Number(value) || 0);
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(bytes >= 10 * 1024 * 1024 ? 0 : 1)} MB`;
  if (bytes >= 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${bytes} B`;
}

function renderAgentChatReturnedFiles(attachments) {
  const verified = (Array.isArray(attachments) ? attachments : [])
    .map((item) => ({ item, url: verifiedAgentChatArtifactUrl(item) }))
    .filter(({ url }) => Boolean(url));
  if (!verified.length) return "";
  return `
    <div class="agent-chat-returned-files" aria-label="Files returned by the agent">
      ${verified.map(({ item, url }) => {
        const isImage = String(item.kind || "").toLowerCase() === "image";
        const previewUrl = isImage ? verifiedAgentChatArtifactUrl(item, true) : "";
        const extension = String(item.name || "file").split(".").pop().slice(0, 5).toUpperCase();
        return `
          <a class="agent-chat-returned-file" href="${escapeText(url)}" download>
            ${previewUrl
              ? `<img src="${escapeText(previewUrl)}" alt="${escapeText(item.name || "Returned image")}">`
              : `<span class="agent-chat-returned-file-icon" aria-hidden="true">${escapeText(extension || "FILE")}</span>`}
            <span class="agent-chat-returned-file-copy">
              <strong>${escapeText(item.name || "Download file")}</strong>
              <small>${escapeText(compactFileSize(item.size))} · Download</small>
            </span>
          </a>
        `;
      }).join("")}
    </div>
  `;
}

async function submitAgentChatMessage(event) {
  event.preventDefault();
  const agentKey = state.agentChatAgent;
  const message = agentChatInput?.value.trim() || "";
  const attachments = (state.agentChatAttachments || []).filter((item) => item.status === "ready" && item.attachment?.id);
  if (!agentKey || (!message && !attachments.length)) {
    showToast("Choose an agent, then type a message or attach a file.");
    renderAgentChat();
    return;
  }
  if (state.agentChatAttachments.some((item) => item.status !== "ready")) {
    showToast("Wait for attachments to finish securing, or remove the failed file.");
    return;
  }
  const idempotencyKey = directChatIdempotencyKey(agentKey, message, attachments);
  if (state.agentChatPendingKeys.has(idempotencyKey)) {
    showToast(`Message is already being sent to ${labelForAgent(agentKey)}.`);
    return;
  }
  const payload = {
    id: idempotencyKey,
    idempotencyKey,
    type: "agent-direct-chat",
    agent: agentKey,
    agentName: agentNameForKey(agentKey),
    agentLabel: labelForAgent(agentKey),
    message,
    instruction: message,
    attachments: attachments.map((item) => item.attachment),
    createdAt: new Date().toISOString(),
  };
  state.agentChatPendingKeys.add(idempotencyKey);
  state.agentChatSending = true;
  renderAgentChat();
  try {
    const response = await fetch(agentChatSendEndpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok || body.accepted === false) {
      throw new Error(body.message || response.statusText);
    }
    const localJob = buildLocalJobFromDispatchResult(body, payload, "agent-direct-chat");
    upsertActivityJob(localJob);
    if (agentChatInput) agentChatInput.value = "";
    clearAgentChatAttachments();
    showToast(`Message sent to ${labelForAgent(agentKey)}.`);
    await loadAgentChat({ silent: true });
  } catch (error) {
    showToast(`Message not sent: ${error?.message || "gateway unavailable"}.`);
  } finally {
    state.agentChatPendingKeys.delete(idempotencyKey);
    state.agentChatSending = false;
    renderAgentChat();
  }
}

function directChatIdempotencyKey(agentKey, message, attachments = []) {
  const fingerprint = [
    "direct-chat",
    agentKey,
    normalizeDispatchText(message),
    attachments.map((item) => item.attachment?.sha256 || "").join(","),
    Math.floor(Date.now() / 1000),
  ].join("|");
  return `chat-${agentKey}-${stableHash(fingerprint)}`;
}

function renderReviewPacketActions(ticket = state.selectedTicket) {
  const isPacket = Boolean(ticket?.isReviewPacket && ticket?.packetId);
  if (!reviewPacketActions) return;
  reviewPacketActions.hidden = !isPacket;
  if (!isPacket) return;
  const packet = ticket.packet || {};
  const pendingContinue = state.reviewPacketActionsPending.has(reviewPacketActionKey("continue", ticket, dispatchInstruction?.value || ""));
  const pendingClose = state.reviewPacketActionsPending.has(reviewPacketActionKey("close", ticket, dispatchInstruction?.value || ""));
  const pendingAbandon = state.reviewPacketActionsPending.has(reviewPacketActionKey("abandon", ticket, dispatchInstruction?.value || ""));
  const activeStatus = String(packet.activeFollowupStatus || "").toLowerCase();
  const followupActive = ["queued", "running"].includes(activeStatus) || packet.status === "followup_queued";
  if (reviewPacketStatus) {
    reviewPacketStatus.textContent = followupActive
      ? `${ticket.assignedAgentLabel || ticket.owner || "Agent"} follow-up is ${activeStatus || "queued"}.`
      : packet.status === "ready_to_resolve"
        ? "Follow-up completed. Resolve only after final readback."
        : `${ticket.assignedAgentLabel || ticket.owner || "Agent"} packet updated ${formatCompactDate(packet.updatedAtUtc || packet.createdAtUtc || "") || "recently"}.`;
  }
  if (reviewPacketContinue) {
    reviewPacketContinue.disabled = pendingContinue || pendingClose || followupActive;
    reviewPacketContinue.textContent = pendingContinue ? "Sending" : "Follow-up";
  }
  if (reviewPacketClose) {
    reviewPacketClose.disabled = pendingClose || pendingContinue || followupActive;
    reviewPacketClose.textContent = pendingClose ? "Resolving" : "Resolve";
  }
  if (reviewPacketAbandon) {
    reviewPacketAbandon.disabled = pendingAbandon || pendingContinue || pendingClose || followupActive;
    reviewPacketAbandon.textContent = pendingAbandon ? "Clearing" : "Abandon";
  }
}

function applyReviewPacketsSnapshot(body) {
  if (!body || body.ok === false) return false;
  state.reviewPackets = Array.isArray(body.packets) ? body.packets : [];
  renderStats();
  renderKanban();
  renderAgentList();
  syncOfficeAgentStates();
  return true;
}

async function loadReviewPackets(options = {}) {
  try {
    const response = await fetch(reviewPacketsEndpoint, { method: "GET" });
    const body = await response.json();
    if (!response.ok || body.ok === false) {
      throw new Error(body.message || response.statusText);
    }
    applyReviewPacketsSnapshot(body);
    return;
  } catch (error) {
    state.reviewPackets = [];
    if (!options.silent) {
      console.info("Review packets unavailable:", error?.message || error);
    }
  }
  renderStats();
  renderKanban();
  renderAgentList();
  syncOfficeAgentStates();
}

async function submitReviewPacketAction(action) {
  const ticket = state.selectedTicket;
  if (!ticket?.isReviewPacket || !ticket.packetId) {
    showToast("Select a review packet first.");
    return;
  }
  const instruction = dispatchInstruction?.value.trim() || "";
  if (action === "continue" && !instruction) {
    showToast("Add a follow-up note before sending this packet back to the agent.");
    dispatchInstruction?.focus();
    return;
  }
  const selectedAgentKey = String(state.dispatchAgent || "").trim().toLowerCase();
  const targetAgent = Object.prototype.hasOwnProperty.call(dispatchAgentMap, selectedAgentKey)
    ? dispatchAgentMap[selectedAgentKey]
    : "";
  if (action !== "abandon" && !targetAgent) {
    showToast("Choose a valid agent lane before continuing this review packet.");
    updateDispatchPanel();
    return;
  }
  const pendingKey = reviewPacketActionKey(action, ticket, instruction);
  if (state.reviewPacketActionsPending.has(pendingKey)) {
    showToast(`${ticket.number} packet action is already queued.`);
    return;
  }
  state.reviewPacketActionsPending.add(pendingKey);
  renderReviewPacketActions(ticket);
  try {
    const health = await fetchCommandCenterHealth();
    if (!health.ok) throw new Error(health.message);
    const endpoint = action === "close"
      ? reviewPacketCloseEndpoint
      : action === "abandon"
        ? reviewPacketAbandonEndpoint
        : reviewPacketContinueEndpoint;
    const response = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        packetId: ticket.packetId,
        instruction,
        ...(action === "abandon" ? {} : { targetAgent }),
      }),
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok || body.accepted === false) {
      throw new Error(reviewPacketActionErrorMessage(action, response, body));
    }
    if (action === "abandon") {
      state.reviewPackets = state.reviewPackets.filter((packet) => String(packet.id || packet.packetId || "") !== String(ticket.packetId));
      showToast(`${ticket.number} review packet abandoned.`);
      if (dispatchInstruction) dispatchInstruction.value = "";
      clearSelectedTicket({ keepInstruction: true, keepTaskTitle: true });
      renderStats();
      renderKanban();
      loadDashboardState({ full: true, silent: true });
      return;
    }
    const sourceType = action === "close" ? "review-packet-close" : "review-packet-continue";
    const returnedAgentName = String(body.agentName || body.targetAgent || targetAgent).trim();
    const returnedAgentKey = agentKeyForAgentName(returnedAgentName);
    const returnedAgentLabel = labelForAgent(returnedAgentKey) || returnedAgentName || "agent";
    const payload = {
      type: sourceType,
      packetId: ticket.packetId,
      ticketNumber: ticket.number,
      instruction,
      agent: returnedAgentKey,
      agentName: returnedAgentName,
      agentLabel: returnedAgentLabel,
      targetAgent: returnedAgentName,
    };
    const job = buildLocalJobFromDispatchResult(body, payload, sourceType);
    upsertDispatchJob(job);
    upsertActivityJob(job);
    if (ticket.packet) {
      ticket.packet.status = "followup_queued";
      ticket.packet.activeFollowupJobId = body.job_id || "";
      ticket.packet.activeFollowupStatus = body.status || "queued";
    }
    if (action === "close") {
      showToast(`${ticket.number} close review queued for ${returnedAgentLabel}.`);
      if (dispatchStatus) dispatchStatus.textContent = `${ticket.number} close review queued for ${returnedAgentLabel}. Packet will clear after verified closure.`;
    } else {
      showToast(`${ticket.number} follow-up queued for ${returnedAgentLabel}.`);
      if (dispatchInstruction) dispatchInstruction.value = "";
      if (dispatchStatus) dispatchStatus.textContent = `${ticket.number} packet follow-up queued for ${returnedAgentLabel}.`;
    }
    loadDashboardState({ full: true, silent: true });
  } catch (error) {
    showToast(`Packet action not queued: ${error?.message || "gateway unavailable"}.`);
  } finally {
    state.reviewPacketActionsPending.delete(pendingKey);
    renderReviewPacketActions(state.selectedTicket);
  }
}

function reviewPacketActionKey(action, ticket, instruction) {
  return `${action}:${ticket?.packetId || ""}:${stableHash(normalizeDispatchText(instruction || "proceed"))}`;
}

function reviewPacketActionErrorMessage(action, response, result) {
  const raw = String(result?.message || response?.statusText || "gateway unavailable").trim();
  if (response?.status === 404 || /^not found$/i.test(raw)) {
    if (action === "abandon") {
      return `review-packet abandon endpoint not found on ${commandCenterBaseUrl}. Restart the command-center gateway after jobs finish, then reload the dashboard.`;
    }
    return `review-packet endpoint not found on ${commandCenterBaseUrl}. Restart the command-center gateway after jobs finish, then reload the dashboard.`;
  }
  return raw || "gateway unavailable";
}

function dropHintForLane(laneKey) {
  if (laneKey !== "progress") return "Drop ticket here";
  if (!state.activeAssignmentsLoaded) return "Gateway jobs appear here when connected";
  return "Accepted agent jobs appear here";
}

function wireCard(card) {
  card.addEventListener("click", (event) => {
    if (event.target.closest(".notes-hover")) return;
    const ticket = findTicket(card.dataset.ticketId);
    if (ticket) selectTicket(ticket);
  });

  card.addEventListener("dragstart", (event) => {
    state.draggedCard = card;
    card.classList.add("dragging");
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", card.dataset.ticketId || "ticket");
    agentButtons
      .filter((agent) => agent.dataset.qualityOnly !== "true")
      .forEach((agent) => agent.classList.add("drop-ready"));
  });

  card.addEventListener("dragend", () => {
    card.classList.remove("dragging");
    state.draggedCard = null;
    document.querySelectorAll(".lane.drag-over").forEach((lane) => lane.classList.remove("drag-over"));
    agentButtons.forEach((agent) => agent.classList.remove("drop-ready"));
    dispatchPanel?.classList.remove("drag-over");
  });
}

function wireLaneDrop(dropTarget) {
  dropTarget.addEventListener("dragover", (event) => {
    event.preventDefault();
    dropTarget.closest(".lane")?.classList.add("drag-over");
  });

  dropTarget.addEventListener("dragleave", () => {
    dropTarget.closest(".lane")?.classList.remove("drag-over");
  });

  dropTarget.addEventListener("drop", (event) => {
    event.preventDefault();
    if (!state.draggedCard) return;
    const lane = dropTarget.closest(".lane");
    const laneKey = lane?.dataset.lane || "";
    const ticket = findTicket(state.draggedCard.dataset.ticketId);
    if (laneKey === "progress") {
      lane?.classList.remove("drag-over");
      if (ticket) setDispatchTicket(ticket);
      showToast("Use Agent Dispatch. This lane only shows accepted queued or running agent jobs.");
      return;
    }
    dropTarget.insertBefore(state.draggedCard, dropTarget.querySelector(".drop-hint"));
    lane?.classList.remove("drag-over");
    if (ticket) setDispatchTicket(ticket);
    showToast(`${state.draggedCard.dataset.ticketId} moved to ${lane?.querySelector("h2")?.textContent || "lane"}.`);
  });
}

function wireNotesHover(button) {
  const ticket = findTicket(button.dataset.ticketId);
  if (!ticket) return;
  const show = () => showNotesTooltip(button, ticket);
  button.addEventListener("mouseenter", show);
  button.addEventListener("focus", show);
  button.addEventListener("mouseleave", hideNotesTooltip);
  button.addEventListener("blur", hideNotesTooltip);
  button.addEventListener("click", (event) => {
    event.stopPropagation();
    selectTicket(ticket);
    show();
  });
}

function showNotesTooltip(anchor, ticket) {
  notesTooltip.innerHTML = `
    <strong>${escapeText(ticket.number)} opened by ${escapeText(ticket.openedBy || "Unknown")}</strong>
    <span>${escapeText(ticket.account || "")}</span>
    <pre>${escapeText(ticketNotesWithAgentUpdates(ticket))}</pre>
  `;
  const rect = anchor.getBoundingClientRect();
  const width = Math.min(520, window.innerWidth - 32);
  notesTooltip.style.width = `${width}px`;
  notesTooltip.style.left = `${Math.min(window.innerWidth - width - 16, Math.max(16, rect.left - 80))}px`;
  notesTooltip.style.top = `${Math.max(76, rect.top - 18)}px`;
  notesTooltip.classList.add("visible");
}

function hideNotesTooltip() {
  notesTooltip.classList.remove("visible");
}

function clearSelectedTicket(options = {}) {
  state.selectedTicket = null;
  state.dispatchTicket = null;
  state.selectionClearedByUser = options.userCleared !== false;
  document.querySelectorAll(".ticket-card.selected").forEach((card) => card.classList.remove("selected"));
  const detailValues = {
    "#detailTitle": "Select a ticket",
    "#detailSubtitle": "Open Salesforce snapshot",
    "#detailAccount": "-",
    "#detailAge": "-",
    "#detailMainIssue": "-",
    "#detailTechIssue": "-",
    "#detailOpenedBy": "-",
    "#detailOwner": "-",
    "#detailNotes": "Hover a card's notes or select a ticket to view the full technical notes.",
  };
  Object.entries(detailValues).forEach(([selector, value]) => {
    const element = document.querySelector(selector);
    if (element) element.textContent = value;
  });
  const link = document.querySelector("#detailLink");
  if (link) {
    link.href = "#";
    link.classList.add("disabled");
  }
  if (!options.keepInstruction && dispatchInstruction) dispatchInstruction.value = "";
  if (!options.keepTaskTitle && dispatchTaskTitle) dispatchTaskTitle.value = "";
  if (!options.keepDispatchMode) state.dispatchMode = "ticket";
  renderReviewPacketActions(null);
  renderAgentUpdateSummary();
  updateDispatchPanel();
}

function selectTicket(ticket) {
  state.selectionClearedByUser = false;
  state.selectedTicket = ticket;
  document.querySelectorAll(".ticket-card.selected").forEach((card) => card.classList.remove("selected"));
  document.querySelector(`[data-ticket-id="${CSS.escape(ticket.number)}"]`)?.classList.add("selected");
  document.querySelector("#detailTitle").textContent = ticket.isGeneralTask ? ticket.mainIssue || "General task" : ticket.number || "Ticket";
  document.querySelector("#detailSubtitle").textContent = ticket.recordType || "Salesforce ticket";
  document.querySelector("#detailAccount").textContent = ticket.account || "-";
  document.querySelector("#detailAge").textContent = `${Number(ticket.daysActive) || 0} days`;
  document.querySelector("#detailMainIssue").textContent = ticket.mainIssue || "-";
  document.querySelector("#detailTechIssue").textContent = ticket.technicalIssue || "-";
  document.querySelector("#detailOpenedBy").textContent = ticket.openedBy || "-";
  document.querySelector("#detailOwner").textContent = ticket.owner || "-";
  document.querySelector("#detailNotes").textContent = ticketNotesWithAgentUpdates(ticket);
  const link = document.querySelector("#detailLink");
  link.href = ticket.url || "#";
  link.classList.toggle("disabled", !ticket.url);
  if (ticket.isGeneralTask) {
    setDispatchMode("task", { keepInstruction: true });
    if (dispatchTaskTitle) dispatchTaskTitle.value = ticket.mainIssue || "";
    setDispatchTicket(null);
  } else {
    setDispatchMode("ticket", { keepInstruction: true });
    setDispatchTicket(ticket);
    if (ticket.isReviewPacket && ticket.assignedAgent && dispatchAgentMap[ticket.assignedAgent]) {
      setDispatchAgent(ticket.assignedAgent);
    }
  }
  renderReviewPacketActions(ticket);
  renderAgentUpdateSummary();
}

agentButtons.forEach((agent) => {
  agent.addEventListener("dragover", (event) => {
    if (agent.dataset.qualityOnly === "true") return;
    event.preventDefault();
    agent.classList.add("drop-ready");
  });
  agent.addEventListener("dragleave", () => agent.classList.remove("drop-ready"));
  agent.addEventListener("drop", (event) => {
    event.preventDefault();
    if (!state.draggedCard) return;
    const targetAgent = agent.dataset.agent;
    if (agent.dataset.qualityOnly === "true") {
      agent.classList.remove("drop-ready");
      showToast("Thor reviews support quality and does not accept Salesforce tickets. Use General task.");
      return;
    }
    const ticket = findTicket(state.draggedCard.dataset.ticketId);
    if (ticket) selectTicket(ticket);
    setDispatchAgent(targetAgent);
    agent.classList.remove("drop-ready");
    showToast(`${state.draggedCard.dataset.ticketId} ready for ${labelForAgent(targetAgent)}. Add notes and send.`);
    dispatchInstruction?.focus();
  });

  agent.addEventListener("dblclick", () => {
    completeAgentWork(agent.dataset.agent, "manual completion");
  });
});

dispatchAgentButtons.forEach((button) => {
  button.addEventListener("click", () => setDispatchAgent(button.dataset.dispatchAgent));
  button.addEventListener("dragover", (event) => {
    if (button.dataset.qualityOnly === "true") return;
    event.preventDefault();
    button.classList.add("active");
  });
  button.addEventListener("dragleave", () => {
    button.classList.toggle("active", state.dispatchAgent === button.dataset.dispatchAgent);
  });
  button.addEventListener("drop", (event) => {
    event.preventDefault();
    if (!state.draggedCard) return;
    if (button.dataset.qualityOnly === "true") {
      button.classList.remove("active");
      showToast("Thor reviews support quality and does not accept Salesforce tickets. Use General task.");
      return;
    }
    const ticket = findTicket(state.draggedCard.dataset.ticketId);
    if (ticket) selectTicket(ticket);
    setDispatchAgent(button.dataset.dispatchAgent);
    dispatchInstruction?.focus();
  });
});

dispatchModeButtons.forEach((button) => {
  button.addEventListener("click", () => setDispatchMode(button.dataset.dispatchMode || "ticket"));
});

if (dispatchPanel) {
  dispatchPanel.addEventListener("dragover", (event) => {
    if (!state.draggedCard) return;
    event.preventDefault();
    dispatchPanel.classList.add("drag-over");
  });
  dispatchPanel.addEventListener("dragleave", (event) => {
    if (event.relatedTarget instanceof Node && dispatchPanel.contains(event.relatedTarget)) return;
    dispatchPanel.classList.remove("drag-over");
  });
  dispatchPanel.addEventListener("drop", (event) => {
    if (!state.draggedCard) return;
    event.preventDefault();
    dispatchPanel.classList.remove("drag-over");
    const ticket = findTicket(state.draggedCard.dataset.ticketId);
    if (ticket) {
      selectTicket(ticket);
      dispatchInstruction?.focus();
      showToast(`${ticket.number} attached to Agent Dispatch.`);
    }
  });
}

dispatchPanel?.addEventListener("submit", submitDispatchPrompt);
emailDrawerToggle?.addEventListener("click", () => {
  setEmailDrawerOpen(true);
  loadEmailWatch();
});
emailDrawerClose?.addEventListener("click", () => setEmailDrawerOpen(false));
emailRefresh?.addEventListener("click", requestEmailScan);
emailPageRefresh?.addEventListener("click", requestEmailScan);
detailClearSelection?.addEventListener("click", () => clearSelectedTicket({ keepInstruction: true, keepTaskTitle: true }));
dispatchClearTicket?.addEventListener("click", () => {
  clearSelectedTicket({
    keepDispatchMode: state.dispatchMode === "task",
    keepInstruction: true,
    keepTaskTitle: true,
  });
  showToast("Ticket context cleared from dispatch.");
});
reviewPacketContinue?.addEventListener("click", () => submitReviewPacketAction("continue"));
reviewPacketAbandon?.addEventListener("click", () => submitReviewPacketAction("abandon"));
reviewPacketClose?.addEventListener("click", () => submitReviewPacketAction("close"));
dispatchInstruction?.addEventListener("input", () => {
  renderReviewPacketActions();
  updateDispatchPanel();
});
dispatchInstruction?.addEventListener("keydown", (event) => {
  if (!isPlainEnterKey(event)) return;
  event.preventDefault();
  if (state.selectedTicket?.isReviewPacket && !reviewPacketActions?.hidden) {
    submitReviewPacketAction("continue");
    return;
  }
  dispatchPanel?.requestSubmit();
});
dispatchTaskTitle?.addEventListener("input", updateDispatchPanel);
dispatchTaskTitle?.addEventListener("keydown", (event) => {
  if (!isPlainEnterKey(event)) return;
  event.preventDefault();
  dispatchPanel?.requestSubmit();
});
scheduleRefresh?.addEventListener("click", requestScheduleScan);
ticketRefresh?.addEventListener("click", requestTicketRefresh);
kpiRefresh?.addEventListener("click", requestKpiRefresh);
document.querySelector("#usageRefresh")?.addEventListener("click", () => refreshUsageAnalytics(true));
agentChatClose?.addEventListener("click", closeAgentChat);
agentChatCall?.addEventListener("click", () => startAgentVoiceCall(state.agentChatAgent));
agentChatForm?.addEventListener("submit", submitAgentChatMessage);
agentChatInput?.addEventListener("input", renderAgentChat);
agentChatInput?.addEventListener("paste", pasteAgentChatImages);
agentChatMessages?.addEventListener("scroll", () => {
  if (state.agentChatOpen && state.agentChatAgent && agentChatIsNearBottom()) {
    markAgentChatSeen(state.agentChatAgent);
  }
}, { passive: true });
agentChatAttach?.addEventListener("click", () => agentChatFileInput?.click());
agentChatFileInput?.addEventListener("change", () => {
  addAgentChatFiles(agentChatFileInput.files || []);
  agentChatFileInput.value = "";
});
agentChatAttachments?.addEventListener("click", (event) => {
  const button = event.target.closest("[data-remove-chat-attachment]");
  if (!button) return;
  removeAgentChatAttachment(button.dataset.removeChatAttachment || "");
});
agentChatInput?.addEventListener("keydown", (event) => {
  if (!isPlainEnterKey(event)) return;
  event.preventDefault();
  agentChatForm?.requestSubmit();
});
initTicketBoardResize();

function markAgentWorkStarted(ticket, targetAgent) {
  if (!ticket || !targetAgent) return;
  const sourceAgent = ticket.assignedAgent;
  if (agentElements[targetAgent]) {
    agentElements[targetAgent].dataset.state = "working";
  }
  if (sourceAgent && sourceAgent !== targetAgent) {
    handoffTask(sourceAgent, targetAgent, ticket.number);
  } else {
    receiveTask(targetAgent, ticket.number);
  }
}

function setDispatchTicket(ticket) {
  state.dispatchTicket = ticket || null;
  updateDispatchPanel();
}

function setDispatchMode(mode, options = {}) {
  const previousMode = state.dispatchMode || "ticket";
  state.dispatchMode = mode === "task" ? "task" : "ticket";
  if (state.dispatchMode === "ticket" && isQualityOnlyAgentKey(state.dispatchAgent)) {
    state.dispatchAgent = null;
    showToast("Thor is quality-only and was cleared from ticket mode.");
  }
  if (state.dispatchMode === "task") {
    state.dispatchTicket = null;
    if (state.selectedTicket && !state.selectedTicket.isGeneralTask && !options.keepSelection) {
      clearSelectedTicket({
        keepDispatchMode: true,
        keepInstruction: options.keepInstruction === true,
        keepTaskTitle: true,
      });
    } else if (!options.keepInstruction && previousMode !== "task" && dispatchInstruction) {
      dispatchInstruction.value = "";
    }
  } else if (!options.keepInstruction && dispatchTaskTitle) {
    dispatchTaskTitle.value = "";
  }
  updateDispatchPanel();
}

function setDispatchAgent(agentKey) {
  const normalizedAgentKey = dispatchAgentAliases[String(agentKey || "").trim().toLowerCase()]
    || String(agentKey || "").trim().toLowerCase();
  if (isQualityOnlyAgentKey(normalizedAgentKey) && state.dispatchMode !== "task") {
    setDispatchMode("task", { keepInstruction: true, keepTaskTitle: true });
    showToast("Thor accepts general support-quality tasks only. Switched to General task.");
  }
  state.dispatchAgent = normalizedAgentKey || null;
  updateDispatchPanel();
}

function isQualityOnlyAgentKey(agentKey) {
  const normalized = dispatchAgentAliases[String(agentKey || "").trim().toLowerCase()]
    || String(agentKey || "").trim().toLowerCase();
  return normalized === "claude";
}

function updateDispatchPanel() {
  const mode = state.dispatchMode || "ticket";
  const selectedTicket = state.selectedTicket?.isGeneralTask ? null : state.selectedTicket;
  const ticket = mode === "ticket" ? (state.dispatchTicket || selectedTicket) : null;
  const agentKey = state.dispatchAgent;
  const qualityOnlyTask = mode === "task" && isQualityOnlyAgentKey(agentKey);
  const taskTitle = dispatchTaskTitle?.value.trim() || "";
  dispatchModeButtons.forEach((button) => {
    button.classList.toggle("active", button.dataset.dispatchMode === mode);
  });
  dispatchTaskTitle?.toggleAttribute("hidden", mode !== "task");
  if (dispatchTaskTitle) {
    dispatchTaskTitle.placeholder = qualityOnlyTask
      ? "Support-quality audit title"
      : "Quality review or other concrete task title";
  }
  if (dispatchInstruction) {
    dispatchInstruction.placeholder = qualityOnlyTask
      ? "Read-only call, transcript, Rescue, representative-performance, or meeting-agenda scope"
      : "Instruction, customer context, or ticket update";
  }
  if (dispatchTicketNumber) {
    dispatchTicketNumber.textContent = mode === "task" ? "Task" : ticket?.number || "No ticket";
  }
  if (dispatchClearTicket) {
    dispatchClearTicket.disabled = mode !== "task" && !ticket && !state.selectedTicket;
    dispatchClearTicket.textContent = mode === "task" ? "Clear" : ticket ? "Clear" : "Clear";
  }
  if (dispatchStatus) {
    if (qualityOnlyTask) {
      dispatchStatus.textContent = "Thor ready for a read-only support-quality audit.";
    } else if (mode === "task" && agentKey) {
      dispatchStatus.textContent = `${labelForAgent(agentKey)} ready for a general task.`;
    } else if (mode === "task") {
      dispatchStatus.textContent = "General task mode. Choose an agent.";
    } else if (ticket?.isReviewPacket && agentKey) {
      dispatchStatus.textContent = `${ticket.number} review packet ready for ${labelForAgent(agentKey)}.`;
    } else if (ticket?.isReviewPacket) {
      dispatchStatus.textContent = `${ticket.number} review packet selected. Choose an agent.`;
    } else if (ticket && agentKey) {
      dispatchStatus.textContent = `${ticket.number} ready for ${labelForAgent(agentKey)}.`;
    } else if (ticket) {
      dispatchStatus.textContent = `${ticket.number} attached. Choose an agent.`;
    } else if (agentKey) {
      dispatchStatus.textContent = `${labelForAgent(agentKey)} selected. Attach a ticket.`;
    } else {
      dispatchStatus.textContent = "Select a ticket and agent.";
    }
  }
  dispatchAgentButtons.forEach((button) => {
    const qualityOnlyInTicketMode = mode !== "task" && button.dataset.qualityOnly === "true";
    button.classList.toggle("active", button.dataset.dispatchAgent === agentKey);
    button.disabled = qualityOnlyInTicketMode;
    button.setAttribute("aria-disabled", qualityOnlyInTicketMode ? "true" : "false");
  });
  updateDispatchSubmitState(ticket, agentKey, taskTitle);
}

function updateDispatchSubmitState(ticket, agentKey, taskTitle = "") {
  if (dispatchSubmit) {
    const instruction = dispatchInstruction?.value.trim() || "";
    const canSubmitTicket = state.dispatchMode !== "task"
      && ticket
      && agentKey
      && !isQualityOnlyAgentKey(agentKey);
    const canSubmitTask = state.dispatchMode === "task" && agentKey && (taskTitle || instruction);
    dispatchSubmit.disabled = state.dispatchSubmitting || !(canSubmitTicket || canSubmitTask);
    dispatchSubmit.textContent = state.dispatchSubmitting ? "Sending..." : "Send to Agent";
  }
}

async function submitDispatchPrompt(event) {
  event.preventDefault();
  const mode = state.dispatchMode || "ticket";
  const selectedTicket = state.selectedTicket?.isGeneralTask ? null : state.selectedTicket;
  const ticket = mode === "ticket" ? (state.dispatchTicket || selectedTicket) : null;
  const agentKey = state.dispatchAgent;
  const instruction = dispatchInstruction?.value.trim() || "";
  const taskTitle = dispatchTaskTitle?.value.trim() || "";
  if (mode === "ticket" && isQualityOnlyAgentKey(agentKey)) {
    showToast("Thor cannot receive Salesforce tickets. Switch to General task for a support-quality review.");
    updateDispatchPanel();
    return;
  }
  if (mode === "ticket" && (!ticket || !agentKey)) {
    showToast("Attach a ticket and choose an agent before sending.");
    updateDispatchPanel();
    return;
  }
  if (mode === "task" && (!agentKey || !(taskTitle || instruction))) {
    showToast("Choose an agent and add a task title or instruction.");
    updateDispatchPanel();
    return;
  }
  const idempotencyKey = mode === "task"
    ? generalTaskIdempotencyKey(agentKey, taskTitle, instruction)
    : dispatchIdempotencyKey(ticket, agentKey, instruction);
  if (state.dispatchPendingKeys.has(idempotencyKey)) {
    showToast(`${mode === "task" ? "Task" : ticket.number} is already being sent to ${labelForAgent(agentKey)}.`);
    return;
  }
  const payload = mode === "task"
    ? buildGeneralTaskPayload(agentKey, taskTitle, instruction, idempotencyKey)
    : {
        id: idempotencyKey,
        idempotencyKey,
        type: "salesforce-ticket-agent-prompt",
        agent: agentKey,
        agentName: dispatchAgentMap[agentKey] || agentKey,
        agentLabel: labelForAgent(agentKey),
        ticketNumber: ticket.number,
        salesforceUrl: ticket.url || "",
        account: ticket.account || "",
        recordType: ticket.recordType || "",
        mainIssue: ticket.mainIssue || "",
        technicalIssue: ticket.technicalIssue || "",
        openedBy: ticket.openedBy || "",
        notesContext: ticketAgentNotesContext(ticket),
        instruction,
        prompt: buildDispatchPrompt(ticket, agentKey, instruction),
        createdAt: new Date().toISOString(),
      };
  state.dispatchPendingKeys.add(idempotencyKey);
  state.dispatchSubmitting = true;
  updateDispatchPanel();
  try {
    const result = await sendDispatchPayload(payload);
    if (result.accepted) {
      const activeJob = buildLocalJobFromDispatchResult(result, payload);
      upsertDispatchJob(activeJob);
      upsertActivityJob(activeJob);
      if (result.duplicate) {
        if (dispatchStatus) dispatchStatus.textContent = `${payload.taskTitle || payload.ticketNumber} was already queued for ${labelForAgent(agentKey)}.`;
        showToast(`${payload.taskTitle || payload.ticketNumber} was already sent recently; duplicate ignored.`);
      } else {
        upsertActiveJob(activeJob);
        markAgentWorkStarted(mode === "task" ? ticketFromDispatchJob(activeJob, null) : ticket, agentKey);
        renderStats();
        renderKanban();
        renderAnalytics();
        if (dispatchInstruction) dispatchInstruction.value = "";
        if (mode === "task" && dispatchTaskTitle) dispatchTaskTitle.value = "";
        if (dispatchStatus) dispatchStatus.textContent = `${payload.taskTitle || payload.ticketNumber} sent to ${labelForAgent(agentKey)}.`;
        showToast(`${payload.taskTitle || payload.ticketNumber} queued for ${labelForAgent(agentKey)}.`);
      }
      loadDashboardState({ full: true, silent: true });
    } else {
      const taskLabel = payload.taskTitle || payload.ticketNumber;
      const reason = String(result.message || "task was not accepted").trim();
      if (result.retryable) {
        if (dispatchStatus) dispatchStatus.textContent = `${taskLabel} saved locally for retry: ${reason}`;
        showToast(`${taskLabel} saved locally for retry: ${reason}`);
      } else {
        if (dispatchStatus) dispatchStatus.textContent = `${taskLabel} not queued: ${reason}`;
        showToast(`${taskLabel} not queued: ${reason}`);
      }
    }
  } finally {
    state.dispatchPendingKeys.delete(idempotencyKey);
    state.dispatchSubmitting = false;
    updateDispatchPanel();
  }
}

function dispatchIdempotencyKey(ticket, agentKey, instruction) {
  const fingerprint = [
    "dispatch",
    ticketIdentity(ticket),
    agentKey,
    normalizeDispatchText(instruction || "default"),
  ].join("|");
  return `dispatch-${ticketIdentity(ticket) || "ticket"}-${agentKey}-${stableHash(fingerprint)}`;
}

function generalTaskIdempotencyKey(agentKey, taskTitle, instruction) {
  const fingerprint = [
    "general-task",
    agentKey,
    normalizeDispatchText(taskTitle || "untitled"),
    normalizeDispatchText(instruction || "default"),
  ].join("|");
  return `task-${agentKey}-${stableHash(fingerprint)}`;
}

function buildGeneralTaskPayload(agentKey, taskTitle, instruction, idempotencyKey) {
  const title = taskTitle || truncateText(instruction, 80) || "General task";
  const taskId = `TASK-${stableHash(`${agentKey}|${title}|${instruction || ""}`).toUpperCase().slice(0, 6)}`;
  return {
    id: idempotencyKey,
    idempotencyKey,
    type: "general-agent-task",
    agent: agentKey,
    agentName: dispatchAgentMap[agentKey] || agentKey,
    agentLabel: labelForAgent(agentKey),
    taskId,
    taskTitle: title,
    taskCategory: agentKey === "taylor" ? "Ops / DevOps" : "General",
    instruction,
    prompt: buildGeneralTaskPrompt(agentKey, title, instruction),
    createdAt: new Date().toISOString(),
  };
}

function normalizeDispatchText(value) {
  return String(value || "").trim().replace(/\s+/g, " ").toLowerCase();
}

function stableHash(value) {
  let hash = 2166136261;
  const text = String(value || "");
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0).toString(36);
}

function buildDispatchPrompt(ticket, agentKey, instruction) {
  const notesContext = ticketAgentNotesContext(ticket);
  const developmentServiceRule = developmentServiceCompletionRule(ticket);
  return [
    `Work Salesforce ticket ${ticket.number}.`,
    `Assigned agent: ${labelForAgent(agentKey)}.`,
    `Salesforce URL: ${ticket.url || "not available"}.`,
    `Account: ${ticket.account || "No account linked"}.`,
    `Opened by: ${ticket.openedBy || "Unknown"}.`,
    `Record type: ${ticket.recordType || "Unknown"}.`,
    `Main issue: ${ticket.mainIssue || "Unclassified"}.`,
    `Technical issue: ${ticket.technicalIssue || "No technical issue selected"}.`,
    operatorInstructionLine(instruction, "Review the ticket, use the technical notes, and prepare the next safe support action."),
    steeringRuleLine(instruction),
    notesContext ? `Technical notes / Chatter context:\n${notesContext}` : "",
    "Ticket evidence note: linked Zoom Contact Center session history, Smart Notes, call transcript/recording metadata, Chatter, and Technical Notes may be attached to this Salesforce ticket. Use them when relevant without pasting full transcripts into routine ticket updates.",
    developmentServiceRule,
  ].filter(Boolean).join("\n");
}

function developmentServiceCompletionRule(ticket) {
  if (normalizedText(ticket?.mainIssue) !== "development service" || !isSupportTicket(ticket)) return "";
  return [
    "Development Service completion rule:",
    "- This is a Nova Classic/Wave ticket with Main Issue = Development Service. If the live Salesforce work is completed and you are closing or marking the ticket complete, also set the Salesforce field labeled `Development Service Status` to `Completed`.",
    "- Use Salesforce describe metadata/readback to confirm the exact API field name and allowed picklist value before writing; do not guess if the field or value is not available.",
    "- When possible, set the ticket close/status fields and Development Service Status in the same Salesforce update. After the write, read back both the ticket status and Development Service Status.",
  ].join("\n");
}

function buildGeneralTaskPrompt(agentKey, taskTitle, instruction) {
  return [
    `Work this Nova Ops Command Center general task.`,
    `Assigned agent: ${labelForAgent(agentKey)}.`,
    `Task title: ${taskTitle || "General task"}.`,
    operatorInstructionLine(instruction, taskTitle || "Handle the requested operational task."),
    steeringRuleLine(instruction),
    "This task is not tied to a Salesforce ticket unless the operator explicitly says otherwise.",
    isQualityOnlyAgentKey(agentKey)
      ? "Thor boundary: perform only read-only support-quality analysis with the configured Zoom/Rescue quality tools. Do not access Salesforce or Gmail, create or update tickets, resolve recipients, send messages, administer Zoom, mutate Rescue, or persist raw customer/chat/transcript data. This is an admitted general quality task, so begin the normal sanitized answer with exactly one of COMPLETED, COMPLETED_WITH_ISSUES, or BLOCKED. Do not emit the managed weekly THOR_SUPPORT_QUALITY_RESULT marker."
      : "",
    "Use your own sandbox for files, scripts, or app changes. Other repos may be read for guidance, but do not write outside your sandbox unless the operator explicitly asks for that repo change.",
    "When finished, reply in chat with the useful answer, outcome, or next action in plain terms. Do not list specific file changes, verification pass messages, or routine sync details unless the operator asks or something failed. Do not create markdown handoff files unless a durable record is specifically needed.",
  ].join("\n");
}

async function sendDispatchPayload(payload) {
  try {
    const health = await fetchCommandCenterHealth();
    if (!health.ok) {
      throw new Error(health.message);
    }
    const response = await fetch(dispatchEndpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok || body.accepted === false) {
      const message = body.message || response.statusText || "task was not accepted";
      const retryable = response.status === 408
        || response.status === 429
        || response.status >= 500
        || (response.ok && body.accepted === false && message === "runtime_paused");
      if (retryable) queueDispatchPayload(payload);
      return { accepted: false, message, retryable, status: response.status };
    }
    return { accepted: true, message: body.message || "queued", ...body };
  } catch (error) {
    queueDispatchPayload(payload);
    return {
      accepted: false,
      message: error?.message || "command center gateway unavailable",
      retryable: true,
      status: 0,
    };
  }
}

async function fetchCommandCenterHealth() {
  try {
    const response = await fetch(healthEndpoint, { method: "GET" });
    const body = await response.json().catch(() => ({}));
    if (!response.ok || body.ok === false) {
      return { ok: false, message: body.message || response.statusText || "command center health check failed" };
    }
    if (body.service !== "nova-ops-command-center") {
      return {
        ok: false,
        message: `wrong service on ${commandCenterBaseUrl}; expected nova-ops-command-center`,
      };
    }
    applyRuntimeSecurityState(body);
    return { ok: true, ...body };
  } catch (error) {
    return { ok: false, message: error?.message || "command center gateway unavailable" };
  }
}

function applyRuntimeSecurityState(health) {
  const shadow = health?.runtimeMode === "shadow" || health?.externalWritesEnabled === false;
  document.body.classList.toggle("shadow-runtime", shadow);
  if (runtimeSecurityBadge) runtimeSecurityBadge.hidden = !shadow;
}

async function loadAuthenticationContext() {
  try {
    const response = await fetch(authSessionEndpoint, { method: "GET" });
    const body = await response.json().catch(() => ({}));
    if (!response.ok || body.ok === false) throw new Error(body.message || response.statusText);
    const identity = body.identity || {};
    if (operatorIdentity) {
      operatorIdentity.textContent = identity.email || "Local authenticated operator";
    }
    if (operatorLogout) operatorLogout.hidden = identity.mode !== "google_session";
  } catch (error) {
    if (operatorIdentity) operatorIdentity.textContent = "Authentication unavailable";
    if (operatorLogout) operatorLogout.hidden = true;
    console.info("Command Center authentication context unavailable:", error?.message || error);
  }
}

if (operatorLogout) {
  operatorLogout.addEventListener("click", async () => {
    operatorLogout.disabled = true;
    try {
      const response = await fetch(authLogoutEndpoint, { method: "POST" });
      if (!response.ok) throw new Error(response.statusText || "sign-out failed");
      window.location.replace("/auth/google/login");
    } catch (error) {
      operatorLogout.disabled = false;
      showToast(`Sign out failed: ${error?.message || "authentication unavailable"}.`);
    }
  });
}

function buildLocalJobFromDispatchResult(result, payload, sourceType = "dispatch") {
  const now = new Date().toISOString();
  return {
    id: result.job_id || result.id || payload.id,
    bridgeJobId: result.bridge_job_id || result.bridgeJobId || "",
    status: result.status || "queued",
    agentName: result.agentName || payload.agentName || "",
    sourceType,
    createdAtUtc: now,
    updatedAtUtc: now,
    payload,
  };
}

function upsertActiveJob(job) {
  const ticketNumber = getJobTicketNumber(job);
  state.activeAssignmentsLoaded = true;
  state.activeJobs = [
    job,
    ...state.activeJobs.filter((existing) => {
      if (existing.id && existing.id === job.id) return false;
      return ticketNumber ? getJobTicketNumber(existing) !== ticketNumber : true;
    }),
  ];
}

function upsertDispatchJob(job) {
  const nextId = jobIdentity(job);
  state.dispatchJobsLoaded = true;
  state.dispatchJobs = sortJobsNewestFirst([
    job,
    ...state.dispatchJobs.filter((existing) => {
      const existingId = jobIdentity(existing);
      return nextId ? existingId !== nextId : existing !== job;
    }),
  ]).slice(0, 200);
  renderAgentUpdateSummary();
}

function upsertActivityJob(job) {
  const nextId = jobIdentity(job);
  state.activityJobsLoaded = true;
  state.activityJobs = sortJobsNewestFirst([
    job,
    ...state.activityJobs.filter((existing) => {
      const existingId = jobIdentity(existing);
      return nextId ? existingId !== nextId : existing !== job;
    }),
  ]).slice(0, 200);
  renderAgentList();
  renderActivity();
  syncOfficeAgentStates();
}

function queueDispatchPayload(payload) {
  try {
    const key = "novaOpsAgentDispatchQueue";
    const existing = JSON.parse(localStorage.getItem(key) || "[]");
    const next = [
      payload,
      ...existing.filter((item) => String(item?.idempotencyKey || item?.id || "") !== String(payload.idempotencyKey || payload.id || "")),
    ].slice(0, 100);
    localStorage.setItem(key, JSON.stringify(next));
  } catch {
    // Local fallback is best effort only.
  }
}

function applyJobsSnapshot(body, options = {}) {
  if (!body || body.ok === false) return false;
  const jobs = Array.isArray(body.jobs) ? body.jobs : [];
  const includeActive = options.active !== false;
  const includeDispatch = options.dispatch !== false;
  const includeActivity = options.activity !== false;

  if (includeActive) {
    const nextJobs = jobs.filter((job) => activeSourceTypes.has(jobSourceType(job))
      && activeJobStatuses.has(normalizedJobStatus(job)));
    const nextFingerprint = stableDataFingerprint(nextJobs);
    if (nextFingerprint !== state.activeJobsFingerprint || !state.activeAssignmentsLoaded) {
      state.activeJobs = nextJobs;
      state.activeJobsFingerprint = nextFingerprint;
    }
    state.activeAssignmentsLoaded = true;
    renderStats();
    renderKanban();
    renderAnalytics();
  }

  if (includeDispatch) {
    state.dispatchJobs = jobs.filter((job) => ticketReplySourceTypes.has(jobSourceType(job)));
    state.dispatchJobsLoaded = true;
    preserveScrollPositions(() => {
      renderAgentUpdateSummary();
      if (state.selectedTicket) {
        document.querySelector("#detailNotes").textContent = ticketNotesWithAgentUpdates(state.selectedTicket);
      }
    });
    if (options.manual) showToast("Agent replies refreshed.");
  }

  if (includeActivity) {
    state.activityJobs = jobs.filter((job) => {
      const sourceType = jobSourceType(job);
      return !sourceType || activitySourceTypes.has(sourceType);
    });
    state.activityJobsLoaded = true;
    if (activityStatus) {
      const activeCount = state.activityJobs.filter((job) => activeJobStatuses.has(normalizedJobStatus(job))).length;
      activityStatus.textContent = `${activeCount} active command-center job${activeCount === 1 ? "" : "s"}; refreshed ${formatCompactDate(new Date().toISOString())}.`;
    }
    renderAgentList();
    renderActivity();
    syncOfficeAgentStates();
  }
  return true;
}

function dashboardPollDelay() {
  const base = document.hidden ? dashboardPollHiddenMs : dashboardPollVisibleMs;
  if (!state.dashboardPollFailures) return base;
  return Math.min(
    dashboardMaxBackoffMs,
    base * (2 ** Math.min(state.dashboardPollFailures, 3)),
  );
}

function scheduleDashboardPoll(delayMs = dashboardPollDelay()) {
  if (state.dashboardPollHalted) return;
  if (state.dashboardPollTimer) window.clearTimeout(state.dashboardPollTimer);
  state.dashboardPollTimer = window.setTimeout(() => {
    state.dashboardPollTimer = null;
    loadDashboardState();
  }, Math.max(250, Number(delayMs) || dashboardPollVisibleMs));
}

function setRuntimeAvailability(available, message = "") {
  if (!runtimeAlert) return;
  runtimeAlert.hidden = Boolean(available);
  if (!available && runtimeAlertMessage) {
    const lastSuccess = state.dashboardLastSuccessAt
      ? ` Last live update ${formatTimeAgo(state.dashboardLastSuccessAt)}.`
      : " No live dashboard update has completed in this tab.";
    runtimeAlertMessage.textContent = `${message || "The private Nova runtime did not answer."}${lastSuccess} The board remains read-only until live data returns.`;
  }
}

function applyDashboardState(snapshot) {
  if (!snapshot || snapshot.ok === false) return false;
  if (snapshot.health) applyRuntimeSecurityState(snapshot.health);
  if (snapshot.jobs) applyJobsSnapshot(snapshot.jobs);
  if (snapshot.reviewPackets) applyReviewPacketsSnapshot(snapshot.reviewPackets);
  if (snapshot.agentChat) applyAgentChatSnapshot(snapshot.agentChat);
  if (snapshot.tickets) applyTicketSnapshot(snapshot.tickets);
  if (snapshot.kpiDashboard) applyKpiDashboardSnapshot(snapshot.kpiDashboard);
  if (snapshot.emailWatch) applyEmailWatchSnapshot(snapshot.emailWatch);
  if (snapshot.schedule) applyScheduleSnapshot(snapshot.schedule);
  return true;
}

function handleAuthRejected(httpStatus) {
  // A stale tab with an expired session must not keep waking the Cloud Run
  // service every 60 seconds. Halt the poll loop and hand control back to the
  // app's own sign-in flow instead of hammering /ops/dashboard-state.
  if (state.dashboardPollHalted) return;
  state.dashboardPollHalted = true;
  if (state.dashboardPollTimer) {
    window.clearTimeout(state.dashboardPollTimer);
    state.dashboardPollTimer = null;
  }
  const lastRedirect = Number(sessionStorage.getItem("novaOpsAuthRedirectAt") || 0);
  const now = Date.now();
  if (now - lastRedirect > 60000) {
    sessionStorage.setItem("novaOpsAuthRedirectAt", String(now));
    setRuntimeAvailability(false, `Nova session expired (HTTP ${httpStatus}). Signing in again.`);
    updateTicketSyncStatus("Session expired. Redirecting to sign-in...");
    window.location.replace("/auth/google/login");
  } else {
    setRuntimeAvailability(false, "Nova session expired. Reload the page to sign in again.");
    updateTicketSyncStatus("Session expired. Reload the page to sign in again.");
  }
}

async function loadDashboardState(options = {}) {
  if (state.dashboardPollInFlight) {
    if (options.full) scheduleDashboardPoll(500);
    return false;
  }
  state.dashboardPollInFlight = true;
  const now = Date.now();
  const includeSlow = Boolean(options.full) || now - state.dashboardLastSlowAt >= dashboardSlowPollMs;
  const includeKpi = Boolean(options.full) || now - state.dashboardLastKpiAt >= dashboardKpiPollMs;
  const query = new URLSearchParams({
    slow: includeSlow ? "1" : "0",
    kpi: includeKpi ? "1" : "0",
  });
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), dashboardRequestTimeoutMs);
  try {
    const response = await fetch(`${dashboardStateEndpoint}?${query}`, {
      method: "GET",
      signal: controller.signal,
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok || body.ok === false) {
      const error = new Error(body.message || response.statusText || `HTTP ${response.status}`);
      if (response.status === 401 || response.status === 403) {
        error.authRejected = true;
        error.httpStatus = response.status;
      }
      throw error;
    }
    if (!applyDashboardState(body)) {
      throw new Error("Nova returned an unusable dashboard state");
    }
    const completedAt = new Date().toISOString();
    state.dashboardLastSuccessAt = completedAt;
    state.dashboardPollFailures = 0;
    if (includeSlow) state.dashboardLastSlowAt = now;
    if (includeKpi) state.dashboardLastKpiAt = now;
    setRuntimeAvailability(true);
    return true;
  } catch (error) {
    if (error?.authRejected) {
      handleAuthRejected(error.httpStatus);
      return false;
    }
    state.dashboardPollFailures += 1;
    const reason = error?.name === "AbortError"
      ? `The private Nova runtime exceeded the ${Math.round(dashboardRequestTimeoutMs / 1000)}-second dashboard deadline.`
      : `Live dashboard request failed: ${error?.message || "gateway unavailable"}.`;
    setRuntimeAvailability(false, reason);
    updateTicketSyncStatus(`Live Nova runtime unavailable. Showing the last verified Salesforce cache.`);
    if (!options.silent) console.info(reason);
    return false;
  } finally {
    window.clearTimeout(timeout);
    state.dashboardPollInFlight = false;
    if (options.schedule !== false) scheduleDashboardPoll();
  }
}

async function loadActiveAssignments(options = {}) {
  try {
    const response = await fetch(`${jobsEndpoint}?active=1&limit=100`, { method: "GET" });
    const body = await response.json();
    if (!response.ok || body.ok === false) {
      throw new Error(body.message || response.statusText);
    }
    applyJobsSnapshot(body, { dispatch: false, activity: false });
    return;
  } catch (error) {
    if (!state.activeAssignmentsLoaded) return;
    state.activeJobs = [];
    state.activeJobsFingerprint = "";
    state.activeAssignmentsLoaded = false;
    if (!options.silent) {
      console.info("Command center active assignments unavailable:", error?.message || error);
    }
  }
  renderStats();
  renderKanban();
  renderAnalytics();
}

async function loadDispatchUpdates(options = {}) {
  try {
    const response = await fetch(`${jobsEndpoint}?limit=200`, { method: "GET" });
    const body = await response.json();
    if (!response.ok || body.ok === false) {
      throw new Error(body.message || response.statusText);
    }
    applyJobsSnapshot(body, { active: false, activity: false, manual: options.manual });
    return;
  } catch (error) {
    state.dispatchJobsLoaded = false;
    preserveScrollPositions(() => renderAgentUpdateSummary(error?.message || "gateway unavailable"));
    if (options.manual) {
      showToast(`Agent replies unavailable: ${error?.message || "gateway unavailable"}.`);
    } else if (!options.silent) {
      console.info("Command center agent replies unavailable:", error?.message || error);
    }
  }
}

async function loadActivityJobs(options = {}) {
  try {
    const response = await fetch(`${jobsEndpoint}?limit=200`, { method: "GET" });
    const body = await response.json();
    if (!response.ok || body.ok === false) {
      throw new Error(body.message || response.statusText);
    }
    applyJobsSnapshot(body, { active: false, dispatch: false });
    return;
  } catch (error) {
    state.activityJobs = [];
    state.activityJobsLoaded = false;
    if (activityStatus) {
      activityStatus.textContent = `Live activity unavailable: ${error?.message || "gateway unavailable"}.`;
    }
    if (!options.silent) {
      console.info("Command center activity unavailable:", error?.message || error);
    }
  }
  renderAgentList();
  renderActivity();
  syncOfficeAgentStates();
}

function setEmailDrawerOpen(open) {
  rightPanel?.classList.toggle("email-open", Boolean(open));
  if (emailDrawer) {
    emailDrawer.setAttribute("aria-hidden", open ? "false" : "true");
  }
}

function applyEmailWatchSnapshot(body) {
  const fallback = data.opsEmailWatch || {
    status: "not_loaded",
    summary: "No ops email scan has been loaded yet.",
    emails: [],
  };
  state.emailWatch = !body || body.ok === false ? fallback : body;
  renderEmailWatch();
  return Boolean(body && body.ok !== false);
}

async function loadEmailWatch() {
  try {
    const response = await fetch(emailWatchEndpoint, { method: "GET" });
    const body = await response.json();
    applyEmailWatchSnapshot(body);
    return;
  } catch {
    applyEmailWatchSnapshot(null);
  }
}

async function requestEmailScan() {
  setEmailWatchStatusText("Queueing Taylor inbox scan...");
  try {
    const response = await fetch(emailScanEndpoint, { method: "POST" });
    const body = await response.json().catch(() => ({}));
    if (!response.ok || body.accepted === false) {
      throw new Error(body.message || response.statusText);
    }
    showToast(`Taylor email scan queued: ${body.job_id || body.bridge_job_id || "job"}.`);
    await loadEmailWatch({ silent: true });
    setEmailWatchStatusText("Scan queued. Refresh after Taylor finishes.");
  } catch (error) {
    showToast(`Email scan not queued: ${error?.message || "gateway unavailable"}.`);
    setEmailWatchStatusText("Gateway unavailable. Start the command center gateway to scan.");
  }
}

function setEmailWatchStatusText(message) {
  [emailWatchStatus, emailPageStatus].filter(Boolean).forEach((target) => {
    target.textContent = message;
  });
}

function setEmailWatchSummaryText(message) {
  [emailSummary, emailPageSummary].filter(Boolean).forEach((target) => {
    target.textContent = message;
  });
}

function emailWatchLists() {
  return [emailWatchList, emailPageList].filter(Boolean);
}

function verifiedPendingEmailWatchEmails(watch = state.emailWatch) {
  const emails = Array.isArray(watch?.emails) ? watch.emails : [];
  return emails.filter((email) => email?.gmailState?.verified === true && email.gmailState.pending === true);
}

function emailWatchReconciliationStatus(watch = state.emailWatch) {
  return String(watch?.reconciliation?.status || "").trim().toLowerCase();
}

function emailWatchIsVisible() {
  const emailSurface = document.querySelector('.view-surface[data-view="email"]');
  const drawerOpen = emailDrawer?.getAttribute("aria-hidden") === "false" || rightPanel?.classList.contains("email-open");
  return Boolean(emailSurface?.classList.contains("active") || drawerOpen);
}

function renderEmailWatch() {
  preserveScrollPositions(() => {
    const watch = state.emailWatch || {};
    const emails = verifiedPendingEmailWatchEmails(watch);
    const updated = watch.updatedAtUtc ? `Updated ${formatCompactDate(watch.updatedAtUtc)}` : "No scan loaded";
    setEmailWatchStatusText(watch.status && watch.status !== "ok" ? `${updated} - ${watch.status}` : updated);
    const reconciliationStatus = emailWatchReconciliationStatus(watch);
    const emptySummary = reconciliationStatus === "ok"
      ? "There are no current unread, unanswered action emails."
      : "Gmail verification is pending; unverified cached messages are hidden.";
    setEmailWatchSummaryText(emails.length ? (watch.summary || "Taylor can scan inbox context and recommend body-only replies.") : emptySummary);
    emailWatchLists().forEach((list, listIndex) => renderEmailWatchList(list, emails, listIndex === 0 ? "emailDrawer" : "emailPage", reconciliationStatus));
  });
}

function renderEmailWatchList(list, emails, listKey, reconciliationStatus) {
  if (!list) return;
  if (!emails.length) {
    const reconciliationComplete = reconciliationStatus === "ok";
    list.innerHTML = `
        <article class="email-card">
          <header><strong>${reconciliationComplete ? "No current action emails" : "Gmail verification pending"}</strong><span>${reconciliationComplete ? "Clear" : "Verifying"}</span></header>
          <p>${reconciliationComplete ? "There are no current unread, unanswered action emails." : `Mail Watch is waiting for a verified Gmail reconciliation${reconciliationStatus ? ` (${escapeText(reconciliationStatus)})` : ""}. Unverified, read, and already-answered messages are not shown.`}</p>
        </article>
      `;
    return;
  }
  list.innerHTML = emails.map((email, index) => {
    const urgency = String(email.urgency || email.priority || "normal").toLowerCase();
    const cardClass = urgency.includes("urgent") ? "urgent" : urgency.includes("follow") ? "follow-up" : "";
    const template = email.templateSuggestion || email.template || {};
    const emailKey = emailDraftKey(email, index);
    const originalBody = email.recommendedReplyBody || email.recommendedReply || email.replyBody || "";
    const body = state.emailDrafts.has(emailKey) ? state.emailDrafts.get(emailKey) : originalBody;
    const threadId = email.threadId || email.thread_id || "";
    const messageId = email.id || email.messageId || email.message_id || "";
    const canSend = Boolean(threadId || messageId);
    const isSalesforceNotice = isSalesforceNotificationEmail(email);
    const markReadPending = state.emailMarkReadPendingKeys.has(emailMarkReadIdempotencyKey(email));
    const editorId = `${listKey}-emailReply-${index}`;
    if (isSalesforceNotice) {
      return `
      <article class="email-card salesforce-notification ${cardClass}">
        <header>
          <strong>${escapeText(email.subject || "Salesforce notification")}</strong>
          <span>Salesforce</span>
        </header>
        <p><b>${escapeText(email.from || email.sender || "Salesforce Notification")}</b> ${escapeText(formatCompactDate(email.receivedAt || email.date || ""))}</p>
        <p>${escapeText(email.snippet || email.summary || "")}</p>
        <dl>
          <div><dt>Ticket context</dt><dd>${escapeText(email.recommendedAction || email.action || "Already tracked under Support or Billing tickets.")}</dd></div>
        </dl>
        <div class="email-thread-lock">
          <span>Cached notification</span>
          <code>${escapeText(threadId || messageId || "missing thread id")}</code>
        </div>
        <div class="email-card-actions">
          <button class="email-mark-read" type="button" data-email-mark-read="${index}" ${markReadPending ? "disabled" : ""}>${markReadPending ? "Marking..." : "Mark read / no action"}</button>
        </div>
        <p class="email-send-status" data-email-mark-read-status="${index}">No reply needed here. This is a Salesforce notification for ticket context already visible on the board.</p>
      </article>
    `;
    }
    return `
      <article class="email-card ${cardClass}">
        <header>
          <strong>${escapeText(email.subject || "No subject")}</strong>
          <span>${escapeText(email.urgency || email.priority || "Review")}</span>
        </header>
        <p><b>${escapeText(email.from || email.sender || "Unknown sender")}</b> ${escapeText(formatCompactDate(email.receivedAt || email.date || ""))}</p>
        <p>${escapeText(email.snippet || email.summary || "")}</p>
        <dl>
          <div><dt>Recommended action</dt><dd>${escapeText(email.recommendedAction || email.action || "Review message.")}</dd></div>
          <div><dt>Template</dt><dd>${escapeText(template.name || template.subject || "No template match")}${template.reason ? ` - ${escapeText(template.reason)}` : ""}</dd></div>
        </dl>
        <div class="email-thread-lock">
          <span>Locked Gmail thread</span>
          <code>${escapeText(threadId || messageId || "missing thread id")}</code>
        </div>
        <label class="email-editor-label" for="${editorId}">Editable reply body</label>
        <textarea class="email-reply-editor" id="${editorId}" data-email-edit="${index}" rows="7" spellcheck="true">${escapeText(body || "")}</textarea>
        <label class="email-send-confirm">
          <input type="checkbox" data-email-confirm="${index}" ${canSend ? "" : "disabled"}>
          <span>I verified this is the correct thread and want Reply All to use its exact live recipients, with this inserted above my existing Gmail signature.</span>
        </label>
        <div class="email-card-actions">
          <button class="email-copy" type="button" data-email-copy="${index}">Copy Body</button>
          <button class="email-send" type="button" data-email-send="${index}" disabled>${canSend ? "Send Reply All" : "Missing Thread"}</button>
          <button class="email-mark-read" type="button" data-email-mark-read="${index}" ${markReadPending ? "disabled" : ""}>${markReadPending ? "Marking..." : "Mark read / no action"}</button>
        </div>
        <p class="email-send-status" data-email-status="${index}">${canSend ? "Send derives Reply All only from the locked thread's live headers and reads the account's current native signature before delivery." : "Copy only: this item has no Gmail thread/message id."}</p>
        <p class="email-send-status" data-email-mark-read-status="${index}">Use Mark read / no action when Taylor should clear this email without replying.</p>
      </article>
    `;
  }).join("");
  list.querySelectorAll("[data-email-edit]").forEach((editor) => {
    editor.addEventListener("input", () => {
      const index = Number(editor.dataset.emailEdit);
      const email = emails[index];
      if (!email) return;
      state.emailDrafts.set(emailDraftKey(email, index), editor.value);
      syncEmailEditors(index, editor.value, editor);
      updateEmailSendButton(index);
    });
  });
  list.querySelectorAll("[data-email-confirm]").forEach((checkbox) => {
    checkbox.addEventListener("change", () => updateEmailSendButton(Number(checkbox.dataset.emailConfirm)));
  });
  list.querySelectorAll("[data-email-copy]").forEach((button) => {
    button.addEventListener("click", async () => {
      const email = emails[Number(button.dataset.emailCopy)];
      const body = emailEditedBody(Number(button.dataset.emailCopy), email);
      if (!body) {
        showToast("No reply body available to copy.");
        return;
      }
      try {
        await navigator.clipboard.writeText(body);
        showToast("Body copied. Paste above the existing Gmail signature.");
      } catch {
        showToast("Clipboard unavailable; select the body text manually.");
      }
    });
  });
  list.querySelectorAll("[data-email-send]").forEach((button) => {
    button.addEventListener("click", () => submitEmailReply(Number(button.dataset.emailSend)));
  });
  list.querySelectorAll("[data-email-mark-read]").forEach((button) => {
    button.addEventListener("click", () => submitEmailMarkRead(Number(button.dataset.emailMarkRead)));
  });
  emails.forEach((_, index) => updateEmailSendButton(index));
}

function syncEmailEditors(index, value, sourceEditor) {
  emailWatchLists().forEach((list) => {
    list.querySelectorAll(`[data-email-edit="${index}"]`).forEach((editor) => {
      if (editor !== sourceEditor && editor.value !== value) {
        editor.value = value;
      }
    });
  });
}

function emailDraftKey(email, index) {
  return String(email?.threadId || email?.thread_id || email?.id || email?.messageId || email?.message_id || index);
}

function emailEditedBody(index, email) {
  const key = emailDraftKey(email, index);
  if (state.emailDrafts.has(key)) return String(state.emailDrafts.get(key) || "").trim();
  for (const list of emailWatchLists()) {
    const editor = list.querySelector(`[data-email-edit="${index}"]`);
    if (editor) return String(editor.value || "").trim();
  }
  return String(email?.recommendedReplyBody || email?.recommendedReply || email?.replyBody || "").trim();
}

function updateEmailSendButton(index) {
  emailWatchLists().forEach((list) => updateEmailSendButtonForList(list, index));
}

function updateEmailSendButtonForList(list, index) {
  const emails = verifiedPendingEmailWatchEmails();
  const email = emails[index];
  const button = list.querySelector(`[data-email-send="${index}"]`);
  const confirm = list.querySelector(`[data-email-confirm="${index}"]`);
  if (!button || !email) return;
  const body = emailEditedBody(index, email);
  const hasThread = Boolean(email.threadId || email.thread_id || email.id || email.messageId || email.message_id);
  const pending = state.emailSendPendingKeys.has(emailSendIdempotencyKey(email, body));
  button.disabled = !hasThread || !body || !confirm?.checked || pending;
  button.textContent = pending ? "Sending Reply All..." : hasThread ? "Reply All With Signature" : "Missing Thread";
}

function setEmailReplyStatus(index, message) {
  emailWatchLists().forEach((list) => {
    const status = list.querySelector(`[data-email-status="${index}"]`);
    if (status) status.textContent = message;
  });
}

function setEmailMarkReadStatus(index, message) {
  emailWatchLists().forEach((list) => {
    const status = list.querySelector(`[data-email-mark-read-status="${index}"]`);
    if (status) status.textContent = message;
  });
}

async function submitEmailReply(index) {
  const emails = verifiedPendingEmailWatchEmails();
  const email = emails[index];
  if (!email) return;
  const body = emailEditedBody(index, email);
  const idempotencyKey = emailSendIdempotencyKey(email, body);
  if (!body) {
    showToast("Reply body is empty.");
    return;
  }
  if (state.emailSendPendingKeys.has(idempotencyKey)) {
    showToast("This exact reply is already being sent.");
    return;
  }
  const payload = {
    idempotencyKey,
    type: "gmail-thread-reply",
    emailIndex: index,
    emailId: email.id || email.messageId || email.message_id || "",
    threadId: email.threadId || email.thread_id || "",
    from: email.from || email.sender || "",
    subject: email.subject || "",
    receivedAt: email.receivedAt || email.date || "",
    body,
  };
  state.emailSendPendingKeys.add(idempotencyKey);
  updateEmailSendButton(index);
  setEmailReplyStatus(index, "Validating the live thread and current Gmail signature...");
  try {
    const health = await fetchCommandCenterHealth();
    if (!health.ok) {
      throw new Error(health.message);
    }
    const response = await fetch(emailSendEndpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok || result.accepted === false) {
      throw new Error(emailSendErrorMessage(response, result));
    }
    const sentStatus = result.duplicate
      ? "This exact reply was already sent and verified in the Gmail thread."
      : "Sent and verified with the account's current Gmail signature.";
    setEmailReplyStatus(index, sentStatus);
    showToast(sentStatus);
    await loadEmailWatch({ silent: true });
    const refreshedIndex = verifiedPendingEmailWatchEmails().findIndex(
      (candidate, candidateIndex) => emailDraftKey(candidate, candidateIndex) === emailDraftKey(email, index),
    );
    if (refreshedIndex >= 0) setEmailReplyStatus(refreshedIndex, sentStatus);
  } catch (error) {
    state.emailSendPendingKeys.delete(idempotencyKey);
    setEmailReplyStatus(index, `Send not confirmed: ${error?.message || "gateway unavailable"}.`);
    showToast(`Email send not confirmed: ${error?.message || "gateway unavailable"}.`);
  } finally {
    updateEmailSendButton(index);
  }
}

async function submitEmailMarkRead(index) {
  const emails = verifiedPendingEmailWatchEmails();
  const email = emails[index];
  if (!email) return;
  const idempotencyKey = emailMarkReadIdempotencyKey(email);
  if (state.emailMarkReadPendingKeys.has(idempotencyKey)) {
    showToast("That email is already being marked read.");
    return;
  }
  const payload = {
    idempotencyKey,
    type: "gmail-no-action-mark-read",
    emailIndex: index,
    emailId: email.id || email.messageId || email.message_id || "",
    threadId: email.threadId || email.thread_id || "",
    from: email.from || email.sender || "",
    subject: email.subject || "",
    receivedAt: email.receivedAt || email.date || "",
  };
  state.emailMarkReadPendingKeys.add(idempotencyKey);
  renderEmailWatch();
  setEmailMarkReadStatus(index, "Validating cached email and queueing mark-read / no action...");
  try {
    const health = await fetchCommandCenterHealth();
    if (!health.ok) {
      throw new Error(health.message);
    }
    const response = await fetch(emailMarkReadEndpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok || result.accepted === false) {
      throw new Error(emailMarkReadErrorMessage(response, result));
    }
    state.emailMarkReadPendingKeys.delete(idempotencyKey);
    state.emailWatch.emails = (Array.isArray(state.emailWatch?.emails) ? state.emailWatch.emails : [])
      .filter((candidate) => candidate !== email);
    state.emailDrafts.delete(emailDraftKey(email, index));
    showToast("Email mark-read queued and removed from the list.");
    renderEmailWatch();
    await loadDashboardState({ full: true, silent: true });
  } catch (error) {
    state.emailMarkReadPendingKeys.delete(idempotencyKey);
    renderEmailWatch();
    setEmailMarkReadStatus(index, `Mark read not queued: ${error?.message || "gateway unavailable"}.`);
    showToast(`Mark read not queued: ${error?.message || "gateway unavailable"}.`);
  }
}

function emailSendErrorMessage(response, result) {
  const raw = String(result?.message || response?.statusText || "gateway unavailable").trim();
  if (response?.status === 404 || /^not found$/i.test(raw)) {
    return `email send endpoint not found on ${commandCenterBaseUrl}. Reload the dashboard and verify the Nova Ops Command Center gateway is running on 17866.`;
  }
  if (/wrong service/i.test(raw)) {
    return raw;
  }
  return raw || "gateway unavailable";
}

function emailMarkReadErrorMessage(response, result) {
  const raw = String(result?.message || response?.statusText || "gateway unavailable").trim();
  if (response?.status === 404 || /^not found$/i.test(raw)) {
    return `email mark-read / no-action endpoint not found on ${commandCenterBaseUrl}. Reload the dashboard and restart the command-center gateway after jobs finish.`;
  }
  return raw || "gateway unavailable";
}

function emailSendIdempotencyKey(email, body) {
  const fingerprint = [
    "email-send",
    email?.threadId || email?.thread_id || "",
    email?.id || email?.messageId || email?.message_id || "",
    email?.subject || "",
    normalizeDispatchText(body || ""),
  ].join("|");
  return `email-send-${stableHash(fingerprint)}`;
}

function emailMarkReadIdempotencyKey(email) {
  const fingerprint = [
    "email-mark-read",
    email?.threadId || email?.thread_id || "",
    email?.id || email?.messageId || email?.message_id || "",
    email?.subject || "",
    email?.from || email?.sender || "",
  ].join("|");
  return `email-mark-read-${stableHash(fingerprint)}`;
}

function isSalesforceNotificationEmail(email) {
  const sender = normalizeDispatchText(email?.from || email?.sender || "");
  const subject = normalizeDispatchText(email?.subject || "");
  if (sender.includes("salesforce") && (sender.includes("notification") || sender.includes("salesforce@") || sender.includes("noreply"))) {
    return true;
  }
  return subject.includes("novapos ticket") && sender.includes("salesforce") && (subject.includes("mentioned") || subject.includes("commented") || subject.includes("comment"));
}

function applyScheduleSnapshot(body) {
  const fallback = data.opsSchedule || {
    status: "not_loaded",
    meetings: [],
  };
  state.schedule = !body || body.ok === false ? fallback : body;
  renderSchedule();
  return Boolean(body && body.ok !== false);
}

async function loadSchedule() {
  try {
    const response = await fetch(scheduleEndpoint, { method: "GET" });
    const body = await response.json();
    applyScheduleSnapshot(body);
    return;
  } catch {
    applyScheduleSnapshot(null);
  }
}

async function requestScheduleScan() {
  if (meetingList) meetingList.innerHTML = "<p>Queueing meeting scan...</p>";
  try {
    const response = await fetch(scheduleScanEndpoint, { method: "POST" });
    const body = await response.json().catch(() => ({}));
    if (!response.ok || body.accepted === false) {
      throw new Error(body.message || response.statusText);
    }
    showToast(`Taylor meeting scan queued: ${body.job_id || body.bridge_job_id || "job"}.`);
    renderScheduleMessage("Scan queued. Sync again after Taylor finishes.");
  } catch (error) {
    showToast(`Meeting scan not queued: ${error?.message || "gateway unavailable"}.`);
    renderScheduleMessage("Gateway unavailable. Start the command center gateway to scan meetings.");
  }
}

function renderSchedule() {
  preserveScrollPositions(() => {
    const schedule = state.schedule || {};
    const meetings = Array.isArray(schedule.meetings) ? schedule.meetings : Array.isArray(schedule.items) ? schedule.items : [];
    if (!meetingList) return;
    if (!meetings.length) {
      renderScheduleMessage(schedule.summary || "No upcoming Zoom or calendar meetings loaded.");
      return;
    }
    meetingList.innerHTML = meetings.slice(0, 4).map((meeting) => `
      <article class="meeting-item">
        <strong>${escapeText(meeting.title || meeting.summary || "Scheduled meeting")}</strong>
        <span>${escapeText(formatMeetingTime(meeting))}</span>
        <span>${escapeText(meeting.source || meeting.calendar || "Calendar")}${meeting.location ? ` - ${escapeText(meeting.location)}` : ""}</span>
      </article>
    `).join("");
  });
}

function renderScheduleMessage(message) {
  preserveScrollPositions(() => {
    if (meetingList) {
      meetingList.innerHTML = `<p>${escapeText(message)}</p>`;
    }
  });
}

function initTicketBoardResize() {
  if (!kanbanSurface || !kanbanBoard || !ticketResizeHandle) return;
  const saved = Number(localStorage.getItem(ticketBoardHeightKey));
  window.requestAnimationFrame(() => {
    applyTicketBoardHeight(Number.isFinite(saved) && saved > 0 ? saved : defaultTicketBoardHeight(), false);
  });
  ticketResizeHandle.addEventListener("pointerdown", startTicketResize);
  ticketResizeHandle.addEventListener("keydown", handleTicketResizeKeydown);
  ticketResizeHandle.addEventListener("dblclick", resetTicketBoardHeight);
  window.addEventListener("resize", () => {
    const current = currentTicketBoardHeight();
    applyTicketBoardHeight(current, false);
  });
}

function startTicketResize(event) {
  if (!kanbanSurface || !ticketResizeHandle) return;
  event.preventDefault();
  ticketResizeHandle.setPointerCapture?.(event.pointerId);
  kanbanSurface.classList.add("resizing-tickets");
  const move = (moveEvent) => {
    const surfaceRect = kanbanSurface.getBoundingClientRect();
    const nextHeight = surfaceRect.bottom - moveEvent.clientY - 7;
    applyTicketBoardHeight(nextHeight, true);
  };
  const end = () => {
    kanbanSurface.classList.remove("resizing-tickets");
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", end);
    window.removeEventListener("pointercancel", end);
  };
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", end);
  window.addEventListener("pointercancel", end);
  move(event);
}

function handleTicketResizeKeydown(event) {
  const step = event.shiftKey ? 80 : 32;
  if (event.key === "ArrowUp") {
    event.preventDefault();
    applyTicketBoardHeight(currentTicketBoardHeight() + step, true);
  } else if (event.key === "ArrowDown") {
    event.preventDefault();
    applyTicketBoardHeight(currentTicketBoardHeight() - step, true);
  } else if (event.key === "Home") {
    event.preventDefault();
    applyTicketBoardHeight(ticketBoardBounds().min, true);
  } else if (event.key === "End") {
    event.preventDefault();
    applyTicketBoardHeight(ticketBoardBounds().max, true);
  } else if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    resetTicketBoardHeight();
  }
}

function resetTicketBoardHeight() {
  applyTicketBoardHeight(defaultTicketBoardHeight(), true);
  showToast("Ticket board height reset.");
}

function defaultTicketBoardHeight() {
  const bounds = ticketBoardBounds();
  return Math.round(Math.min(bounds.max, Math.max(bounds.min, bounds.total * 0.36)));
}

function currentTicketBoardHeight() {
  const rect = kanbanBoard?.getBoundingClientRect();
  return rect?.height || defaultTicketBoardHeight();
}

function applyTicketBoardHeight(height, persist) {
  if (!kanbanSurface || !ticketResizeHandle) return;
  const bounds = ticketBoardBounds();
  const clamped = Math.round(Math.min(bounds.max, Math.max(bounds.min, height)));
  kanbanSurface.style.setProperty("--ticket-board-height", `${clamped}px`);
  ticketResizeHandle.setAttribute("aria-valuemin", String(bounds.min));
  ticketResizeHandle.setAttribute("aria-valuemax", String(bounds.max));
  ticketResizeHandle.setAttribute("aria-valuenow", String(clamped));
  if (persist) {
    localStorage.setItem(ticketBoardHeightKey, String(clamped));
  }
}

function ticketBoardBounds() {
  const surfaceRect = kanbanSurface?.getBoundingClientRect();
  const total = surfaceRect?.height || Math.max(520, window.innerHeight - 60);
  const handleHeight = ticketResizeHandle?.getBoundingClientRect().height || 14;
  const minOffice = 0;
  const minTickets = 220;
  const maxTickets = Math.max(minTickets, total - minOffice - handleHeight - 2);
  return { total, min: minTickets, max: maxTickets };
}

function formatCompactDate(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

function formatMeetingTime(meeting) {
  const start = meeting.startLocal || meeting.start || meeting.startTime || meeting.when;
  const end = meeting.endLocal || meeting.end || meeting.endTime;
  if (!start) return "Time not available";
  const startText = formatCompactDate(start);
  const endDate = end ? new Date(end) : null;
  if (!endDate || Number.isNaN(endDate.getTime())) return startText;
  return `${startText} - ${endDate.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`;
}

function renderActivity() {
  preserveScrollPositions(() => {
    const items = currentAgentActivityItems();
    document.querySelector("#activityGrid").innerHTML = items.map((item) => `
      <article class="activity-card ${escapeText(item.color)}">
        <header>
          <strong>${escapeText(item.agent)}</strong>
          <span>${escapeText(String(item.state).toUpperCase())}</span>
        </header>
        <p><b>Working on:</b> ${escapeText(item.workingOn)}</p>
        <p>${escapeText(item.activity)}</p>
        <div>
          <strong>Work note</strong>
          ${escapeText(item.reasoning)}
          ${item.updatedAt ? `<small>${escapeText(formatTimeAgo(item.updatedAt))}</small>` : ""}
        </div>
      </article>
    `).join("");
  });
}

async function refreshUsageAnalytics(force = false) {
  if (state.usageLoading || (!force && Date.now() - state.usageLoadedAt < 30000)) return;
  state.usageLoading = true;
  try {
    const response = await fetch(`${usageHistoryEndpoint}?limit=200`, { method: "GET" });
    if (!response.ok) throw new Error(`usage history ${response.status}`);
    state.usageHistory = await response.json();
    state.usageLoadedAt = Date.now();
  } catch (error) {
    state.usageHistory = { ok: false, error: error.message, rows: [], total: {} };
  } finally {
    state.usageLoading = false;
    renderUsageAnalytics();
  }
}

function usageNumber(value) { return Number(value || 0).toLocaleString(); }
function usageCost(value) { return `$${Number(value || 0).toFixed(4)}`; }
function renderUsageAnalytics() {
  const history = state.usageHistory || { rows: [], total: {} };
  const rows = Array.isArray(history.rows) ? history.rows : [];
  const total = history.total || {};
  const status = document.querySelector("#usageAnalyticsStatus");
  const metrics = document.querySelector("#usageMetrics");
  const body = document.querySelector("#usageRows");
  if (!status || !metrics || !body) return;
  status.textContent = history.ok === false ? `Usage history unavailable: ${history.error || "retry shortly"}` : `${history.durable ? "Durable Firestore history" : "Live instance history"} · ${rows.length} task${rows.length === 1 ? "" : "s"}`;
  metrics.innerHTML = [
    ["Total tokens", usageNumber(total.total_tokens)], ["Input tokens", usageNumber(total.input_tokens)],
    ["Output tokens", usageNumber(total.output_tokens)], ["Estimated cost", usageCost(total.estimated_cost_usd)],
  ].map(([label, value]) => `<div class="metric-card neutral"><span>${label}</span><strong>${value}</strong><small>Codex usage</small></div>`).join("");
  body.innerHTML = rows.length ? rows.slice().reverse().map((row) => {
    const task = row.taskLabel || row.sourceType || row.job_id || "Task";
    const ticket = row.ticketNumber ? `#${row.ticketNumber}` : "—";
    return `<tr><td class="usage-task">${escapeText(String(task))}</td><td>${escapeText(ticket)}</td><td>${escapeText(row.agentName || "—")}</td><td>${usageNumber(row.total_tokens)}</td><td>${usageNumber(row.input_tokens)}</td><td>${usageNumber(row.output_tokens)}</td><td>${usageCost(row.estimated_cost_usd)}</td><td>${escapeText(formatTimeAgo(row.recorded_at || row.completedAtUtc || ""))}</td></tr>`;
  }).join("") : '<tr><td colspan="8">No Codex task usage recorded yet. Deterministic refreshes intentionally use zero tokens.</td></tr>';
}

function renderAnalytics() {
  preserveScrollPositions(() => {
    const dashboard = state.kpiDashboard || {};
    const metrics = normalizedKpiMetrics(dashboard);
    const sections = normalizedKpiSections(dashboard);
    updateKpiStatus();
    renderUsageAnalytics();
    refreshUsageAnalytics();
    if (analyticsSummary) {
      analyticsSummary.textContent = dashboard.summary || "No Google KPI cache is loaded yet. Ticket metrics below are from the local Salesforce board cache.";
    }
    document.querySelector("#analyticsMetrics").innerHTML = metrics.map((metric) => `
      <div class="metric-card ${escapeText(metric.status || "neutral")}">
        <span>${escapeText(metric.label)}</span>
        <strong>${escapeText(metric.value)}</strong>
        <small>${escapeText([metric.period, metric.trend].filter(Boolean).join(" - ") || metric.source || "")}</small>
        ${metric.note ? `<p>${escapeText(metric.note)}</p>` : ""}
      </div>
    `).join("");
    if (!kpiSections) { renderUsageAnalytics(); refreshUsageAnalytics(); return; }
    if (!sections.length) {
      kpiSections.innerHTML = `
        <article class="kpi-section-card">
          <header><strong>KPI Detail</strong><span>Waiting</span></header>
          <p>Run SYNC KPI to let Taylor refresh the compact Google KPI dashboard cache in the background.</p>
        </article>
      `;
      return;
    }
    kpiSections.innerHTML = sections.slice(0, 6).map((section) => `
      <article class="kpi-section-card">
        <header><strong>${escapeText(section.title || "KPI Section")}</strong><span>${escapeText(`${section.rows.length} rows`)}</span></header>
        <dl>
          ${section.rows.slice(0, 8).map((row) => `
            <div class="${escapeText(row.status || "neutral")}">
              <dt>${escapeText(row.label || "Metric")}</dt>
              <dd><strong>${escapeText(row.value ?? "-")}</strong>${row.note ? `<span>${escapeText(row.note)}</span>` : ""}</dd>
            </div>
          `).join("")}
        </dl>
      </article>
    `).join("");
  });
}

function normalizedKpiMetrics(dashboard) {
  const metrics = Array.isArray(dashboard?.metrics) ? dashboard.metrics : [];
  if (metrics.length) {
    return metrics.slice(0, 8).map((metric) => ({
      label: metric.label || metric.name || "KPI",
      value: metric.value ?? metric.current ?? "-",
      period: metric.period || metric.window || "",
      trend: metric.trend || "",
      status: metric.status || "neutral",
      note: metric.note || metric.summary || "",
      source: "Google KPI",
    }));
  }
  const analytics = data.analytics || {};
  return [
    { label: "Open Tickets", value: analytics.openTickets ?? getAllTickets().length, status: "neutral", source: "Salesforce cache" },
    { label: "Stale 3+ Days", value: analytics.staleTickets ?? getAllTickets().filter((ticket) => Number(ticket.daysActive) >= 3).length, status: "warn", source: "Salesforce cache" },
    { label: "Missing Account", value: analytics.missingAccount ?? getAllTickets().filter((ticket) => !ticket.account).length, status: "neutral", source: "Salesforce cache" },
    { label: "Assigned / In Progress", value: state.activeJobs.length, status: state.activeJobs.length ? "warn" : "good", source: "Gateway jobs" },
  ];
}

function normalizedKpiSections(dashboard) {
  const sections = Array.isArray(dashboard?.sections) ? dashboard.sections : [];
  return sections.map((section) => ({
    title: section.title || section.name || "KPI Section",
    rows: Array.isArray(section.rows) ? section.rows.map((row) => ({
      label: row.label || row.name || row.metric || "Metric",
      value: row.value ?? row.current ?? "-",
      status: row.status || "neutral",
      note: row.note || row.summary || row.trend || "",
    })) : [],
  })).filter((section) => section.rows.length);
}

function readLocalValue(key) {
  try {
    return localStorage.getItem(key) || "";
  } catch {
    return "";
  }
}

function writeLocalValue(key, value) {
  try {
    localStorage.setItem(key, value);
  } catch {
    // Local persistence is optional for file previews and locked-down browsers.
  }
}

function initLeftRailToggle() {
  setLeftRailCollapsed(readLocalValue(leftRailCollapsedKey) === "true", { persist: false, silent: true });
  leftRailToggle?.addEventListener("click", () => {
    setLeftRailCollapsed(!state.leftRailCollapsed);
  });
}

function setLeftRailCollapsed(collapsed, options = {}) {
  state.leftRailCollapsed = Boolean(collapsed);
  appShell?.classList.toggle("left-rail-collapsed", state.leftRailCollapsed);
  if (leftRailToggle) {
    const expanded = !state.leftRailCollapsed;
    leftRailToggle.setAttribute("aria-expanded", expanded ? "true" : "false");
    leftRailToggle.setAttribute("aria-label", expanded ? "Hide left panel" : "Show left panel");
    leftRailToggle.title = expanded ? "Hide left panel" : "Show left panel";
    leftRailToggle.style.left = expanded ? "calc(var(--left-rail-width) - 8px)" : "0px";
  }
  if (options.persist !== false) {
    writeLocalValue(leftRailCollapsedKey, state.leftRailCollapsed ? "true" : "false");
  }
  if (!options.silent) {
    showToast(state.leftRailCollapsed ? "Left panel hidden. Detail panel expanded." : "Left panel shown.");
  }
}

const drawingBoardLanes = [
  { key: "todo", title: "To do", subtitle: "Ready to start", statuses: ["drawing", "ready"], tone: "violet" },
  { key: "doing", title: "In progress", subtitle: "Actively moving", statuses: ["in_progress"], tone: "cyan" },
  { key: "waiting", title: "Waiting", subtitle: "Waiting on someone or proof", statuses: ["waiting", "evidence_required"], tone: "amber" },
  { key: "done", title: "Done", subtitle: "Checked off", statuses: ["verified_complete"], tone: "green" },
];

const drawingAgentLabels = {
  tickets_agent: "Alex - Tickets",
  billing_agent: "Jamie - Billing",
  coding_agent: "Taylor - Engineering",
  claude_agent: "Thor",
};

function drawingTaskFlags(task) {
  const now = Date.now();
  const due = task.due_at ? Date.parse(task.due_at) : NaN;
  const updated = task.updated_at ? Date.parse(task.updated_at) : NaN;
  const tracked = task.actionable === true && ["ready", "in_progress", "waiting", "evidence_required"].includes(task.status);
  return {
    overdue: tracked && Number.isFinite(due) && due < now,
    dueSoon: tracked && Number.isFinite(due) && due >= now && due <= now + 86400000,
    stale: tracked && Number.isFinite(updated) && now - updated >= 172800000,
  };
}

function drawingTaskLane(task) {
  if (task.status === "verified_complete") return "done";
  if (["waiting", "evidence_required"].includes(task.status)) return "waiting";
  if (task.status === "in_progress") return "doing";
  return "todo";
}

function drawingDateLabel(value) {
  if (!value) return "No due date";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "No due date";
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }).format(date);
}

const drawingBriefFieldLabels = {
  task_summary: "task summary",
  business_request: "support / business request",
  requested_outcome: "concrete outcome",
  next_action: "immediate next action",
  assignee_action: "assignee's expected action",
  assignee: "assigned responsibility",
  source_or_evidence: "source / evidence",
  completion_criteria: "completion criteria",
};

function drawingTaskActionability(task) {
  const missing = Array.isArray(task.missing_actionability_fields) ? task.missing_actionability_fields : [];
  return {
    actionable: task.actionable === true,
    missing,
    labels: missing.map((field) => drawingBriefFieldLabels[field] || field.replaceAll("_", " ")),
  };
}

function drawingTaskSourceReference(task) {
  const linked = (task.sources || []).find((item) => item.source_url || item.source_id || item.excerpt);
  return {
    url: task.source_url || linked?.source_url || "",
    label: task.source_id || task.source_thread_id || task.source_url || linked?.source_id || linked?.excerpt || "",
  };
}

function drawingTaskIsOperatorOwned(task) {
  return task?.operator_owned === true || task?.operatorOwned === true;
}

function drawingActionButtons(task) {
  const pending = state.drawingBoardPending.has(task.id);
  const brief = drawingTaskActionability(task);
  const operatorOwned = drawingTaskIsOperatorOwned(task);
  const actions = [];
  if (["drawing", "ready", "in_progress", "waiting", "evidence_required"].includes(task.status)) {
    actions.push(["edit", operatorOwned ? "EDIT" : brief.actionable ? "EDIT BRIEF" : "ADD DETAILS"]);
  }
  if (operatorOwned && ["drawing", "ready", "in_progress", "waiting", "evidence_required"].includes(task.status)) {
    actions.push(["complete", "CHECK OFF"]);
  }
  if (operatorOwned && task.status === "ready") {
    actions.push(["start", "START"]);
  }
  if (task.status === "ready" && brief.actionable && task.agent_name && !operatorOwned) {
    actions.push(["dispatch", `SEND BRIEF TO ${drawingAgentLabels[task.agent_name] || "AGENT"}`]);
  }
  const hasAgentResult = (task.evidence_records || []).some((item) => item.evidence_kind === "agent_report");
  if (["waiting", "evidence_required"].includes(task.status) && hasAgentResult && !operatorOwned) {
    actions.push(["verify", "MARK DONE"]);
  }
  if (brief.actionable && ["ready", "in_progress"].includes(task.status)) {
    actions.push(["waiting", "WAITING"]);
  }
  if (["in_progress", "waiting", "evidence_required", "verified_complete"].includes(task.status)) {
    actions.push(["ready", "RETURN TO TODO"]);
  }
  if (task.status !== "archived") {
    actions.push(["archived", task.status === "verified_complete" ? "ARCHIVE" : "DISMISS"]);
  }
  return actions.map(([action, label]) => (
    `<button type="button" data-drawing-action="${escapeText(action)}" data-task-id="${escapeText(task.id)}" ${pending ? "disabled" : ""}${action === "dispatch" ? ' title="Starts a read-only agent job using the exact brief shown on this card."' : ""}>${escapeText(label)}</button>`
  )).join("");
}

function drawingAgentWorkMarkup(task) {
  const evidence = Array.isArray(task.evidence_records) ? task.evidence_records : [];
  const reports = evidence.filter((item) => item.evidence_kind === "agent_report" && item.summary);
  const workProducts = evidence.filter((item) => item.evidence_kind === "work_product" && item.source_url);
  if (!reports.length && !workProducts.length) return "";
  const latest = reports.at(-1);
  return `<details class="drawing-agent-work"${task.status === "waiting" ? " open" : ""}>
    <summary><span>AGENT UPDATE</span><b>${reports.length} note${reports.length === 1 ? "" : "s"}${workProducts.length ? ` · ${workProducts.length} file${workProducts.length === 1 ? "" : "s"}` : ""}</b></summary>
    ${latest ? `<div class="drawing-agent-note">${escapeText(latest.summary).replaceAll("\n", "<br>")}</div>` : ""}
    ${workProducts.length ? `<div class="drawing-work-products"><strong>WORK PRODUCTS</strong>${workProducts.map((item) => `<a href="${escapeText(item.source_url)}" target="_blank" rel="noreferrer" download>${escapeText(item.summary || "Download attachment")}</a>`).join("")}</div>` : ""}
  </details>`;
}

function drawingCardMarkup(task) {
  const flags = drawingTaskFlags(task);
  const source = drawingTaskSourceReference(task);
  const brief = drawingTaskActionability(task);
  const classes = ["drawing-task-card", `priority-${task.priority || "normal"}`];
  if (task.priority === "urgent") classes.push("is-urgent");
  if (flags.overdue) classes.push("is-overdue");
  if (flags.stale) classes.push("is-stale");
  const terminal = task.status === "verified_complete";
  const operatorOwned = drawingTaskIsOperatorOwned(task);
  if (!brief.actionable && !terminal && !operatorOwned) classes.push("brief-incomplete");
  const owner = task.owner || (operatorOwned ? "Darius" : "Unassigned");
  const agent = operatorOwned ? "Darius - Operator" : drawingAgentLabels[task.agent_name] || "No responsibility selected";
  const actionHeading = operatorOwned ? "YOUR ACTION" : `${agent.toUpperCase()} DOES`;
  const proofCount = (task.evidence_records || []).length;
  const criteria = task.completion_criteria || (task.checklist || []).join("; ");
  const tags = [
    ...(operatorOwned ? ["Operator-owned"] : []),
    ...(task.recurrence ? [task.recurrence] : []),
    ...(flags.overdue ? ["Overdue"] : flags.dueSoon ? ["Due soon"] : []),
    ...(flags.stale ? ["Stale"] : []),
  ];
  return `
    <article class="${classes.join(" ")}" data-task-id="${escapeText(task.id)}">
      <div class="drawing-task-topline">
        <span class="drawing-task-priority">${escapeText(task.priority || "normal")}</span>
        <span>${escapeText(task.status.replaceAll("_", " "))}</span>
      </div>
      <h3 class="drawing-task-title">${escapeText(task.title)}</h3>
      ${task.description ? `<p class="drawing-task-next">${escapeText(task.description)}</p>` : ""}
      ${task.next_action ? `<p class="drawing-task-next"><strong>Next:</strong> ${escapeText(task.next_action)}</p>` : ""}
      <div class="drawing-task-meta"><span>${escapeText(owner)}</span><span>${escapeText(agent)}</span><span>${escapeText(drawingDateLabel(task.due_at))}</span></div>
      ${tags.length ? `<div class="drawing-task-tags">${tags.map((tag) => `<span class="drawing-task-tag">${escapeText(tag)}</span>`).join("")}</div>` : ""}
      ${!operatorOwned && !brief.actionable && !terminal ? `<div class="drawing-brief-state is-draft">NEEDS DETAILS - ${escapeText(brief.labels.join(", ") || "required details missing")}</div>` : ""}
      ${!operatorOwned && brief.actionable && !terminal ? '<div class="drawing-brief-state is-actionable">READY FOR AGENT</div>' : ""}
      ${terminal ? '<div class="drawing-brief-state is-actionable">COMPLETED</div>' : ""}
      ${!operatorOwned && (task.requested_outcome || task.assignee_action || criteria || source.label) ? `<details class="drawing-task-details"><summary>DETAILS</summary><dl class="drawing-task-brief">
        ${task.requested_outcome ? `<div><dt>OUTCOME</dt><dd>${escapeText(task.requested_outcome)}</dd></div>` : ""}
        ${task.assignee_action ? `<div><dt>${escapeText(actionHeading)}</dt><dd>${escapeText(task.assignee_action)}</dd></div>` : ""}
        ${criteria ? `<div><dt>DONE WHEN</dt><dd>${escapeText(criteria)}</dd></div>` : ""}
        ${source.label ? `<div><dt>SOURCE</dt><dd>${escapeText(source.label)}</dd></div>` : ""}
      </dl></details>` : ""}
      ${drawingAgentWorkMarkup(task)}
      ${proofCount ? `<div class="drawing-task-proof">${proofCount} evidence item${proofCount === 1 ? "" : "s"}</div>` : ""}
      <div class="drawing-task-actions">${drawingActionButtons(task)}</div>
      ${source.url ? `<a class="drawing-task-source" href="${escapeText(source.url)}" target="_blank" rel="noreferrer">OPEN SOURCE</a>` : ""}
    </article>`;
}

function renderDrawingBoard() {
  if (!drawingBoardColumns) return;
  const tasks = state.drawingBoard.filter((task) => task.status !== "archived");
  drawingBoardColumns.innerHTML = drawingBoardLanes.map((lane) => {
    const unique = tasks.filter((task) => drawingTaskLane(task) === lane.key);
    return `<section class="drawing-lane drawing-board-lane" data-lane="${lane.key}" data-tone="${lane.tone}">
      <header class="drawing-lane-header drawing-board-lane-head"><div><strong>${lane.title}</strong><span>${lane.subtitle}</span></div><b class="drawing-lane-count drawing-board-lane-count">${unique.length}</b></header>
      <div class="drawing-lane-list">${unique.length ? unique.map(drawingCardMarkup).join("") : `<p class="drawing-lane-empty">Clear for now.</p>`}</div>
    </section>`;
  }).join("");
  const counts = state.drawingBoardBriefing?.counts || {};
  if (drawingActiveCount) drawingActiveCount.textContent = counts.active ?? tasks.filter((task) => ["ready", "in_progress", "waiting", "evidence_required"].includes(task.status) && task.actionable === true).length;
  if (drawingDraftCount) drawingDraftCount.textContent = counts.drafts ?? tasks.filter((task) => task.status === "drawing").length;
  if (drawingDueCount) drawingDueCount.textContent = counts.due_soon ?? 0;
  if (drawingStaleCount) drawingStaleCount.textContent = counts.stale ?? 0;
  if (drawingWaitingCount) drawingWaitingCount.textContent = counts.waiting ?? 0;
  if (drawingProofCount) drawingProofCount.textContent = counts.verified_complete ?? tasks.filter((task) => task.status === "verified_complete").length;
  if (drawingBoardStatus) drawingBoardStatus.textContent = tasks.length ? `${counts.active ?? 0} open task${counts.active === 1 ? "" : "s"}; ${counts.drafts ?? 0} need${counts.drafts === 1 ? "s" : ""} more detail.` : "No tasks yet. Add a reminder, follow-up, or agent-assisted task.";
}

async function loadDrawingBoard(options = {}) {
  if (state.drawingBoardLoading) return;
  state.drawingBoardLoading = true;
  drawingBoardColumns?.classList.add("loading");
  if (!options.silent && drawingBoardStatus) drawingBoardStatus.textContent = "Syncing the Drawing Board...";
  try {
    const response = await fetch(drawingBoardEndpoint, { method: "GET" });
    const payload = await response.json();
    if (!response.ok || !payload.ok) throw new Error(payload.error || `HTTP ${response.status}`);
    state.drawingBoard = Array.isArray(payload.tasks) ? payload.tasks : [];
    state.drawingBoardBriefing = payload.briefing || null;
    state.drawingBoardLoaded = true;
    renderDrawingBoard();
  } catch (error) {
    if (drawingBoardStatus) drawingBoardStatus.textContent = `Drawing Board unavailable: ${error.message}`;
    drawingBoardColumns?.classList.add("error");
  } finally {
    state.drawingBoardLoading = false;
    drawingBoardColumns?.classList.remove("loading");
  }
}

async function drawingBoardPost(endpoint, body, taskId = "") {
  if (taskId) state.drawingBoardPending.add(taskId);
  renderDrawingBoard();
  try {
    const response = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const payload = await response.json();
    if (!response.ok || !payload.ok) throw new Error(payload.error || `HTTP ${response.status}`);
    return payload;
  } finally {
    if (taskId) state.drawingBoardPending.delete(taskId);
  }
}

async function updateDrawingTask(taskId, patch) {
  try {
    await drawingBoardPost(drawingBoardUpdateEndpoint, { taskId, patch, actor: "Darius" }, taskId);
    await loadDrawingBoard({ silent: true });
  } catch (error) {
    showToast(`Drawing Board update failed: ${error.message}`);
    renderDrawingBoard();
  }
}

function drawingLocalDateTimeValue(value) {
  const date = value ? new Date(value) : null;
  if (!date || Number.isNaN(date.getTime())) return "";
  const pad = (part) => String(part).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function resetDrawingBriefForm() {
  state.drawingBoardEditingTaskId = null;
  drawingBoardCreate?.reset();
  if (drawingTaskMode) drawingTaskMode.value = "personal";
  if (drawingTaskOwner) drawingTaskOwner.value = "Darius";
  setDrawingTaskMode("personal");
  if (drawingBoardFormTitle) drawingBoardFormTitle.textContent = "Add a task";
  if (drawingBoardSaveBrief) drawingBoardSaveBrief.textContent = "ADD TASK";
}

function setDrawingTaskMode(mode) {
  const agentMode = mode === "agent";
  if (drawingAdvancedFields) {
    drawingAdvancedFields.hidden = !agentMode;
    drawingAdvancedFields.open = agentMode;
  }
  if (drawingTaskOwner) drawingTaskOwner.closest("label").hidden = agentMode;
  if (drawingBoardSaveBrief && !state.drawingBoardEditingTaskId) {
    drawingBoardSaveBrief.textContent = agentMode ? "SAVE AGENT TASK" : "ADD TASK";
  }
}

function closeDrawingBriefForm() {
  resetDrawingBriefForm();
  if (drawingBoardCreate) drawingBoardCreate.hidden = true;
}

function openDrawingBriefForm(task = null) {
  resetDrawingBriefForm();
  if (task) {
    state.drawingBoardEditingTaskId = task.id;
    const source = drawingTaskSourceReference(task);
    const mode = drawingTaskIsOperatorOwned(task) ? "personal" : "agent";
    if (drawingTaskMode) drawingTaskMode.value = mode;
    setDrawingTaskMode(mode);
    if (drawingTaskTitle) drawingTaskTitle.value = task.title || "";
    if (drawingTaskRequest) drawingTaskRequest.value = task.description || "";
    if (drawingTaskOutcome) drawingTaskOutcome.value = task.requested_outcome || "";
    if (drawingTaskNext) drawingTaskNext.value = task.next_action || "";
    if (drawingTaskAssigneeAction) drawingTaskAssigneeAction.value = task.assignee_action || "";
    if (drawingTaskSource) drawingTaskSource.value = source.url || source.label || "";
    if (drawingTaskCriteria) drawingTaskCriteria.value = task.completion_criteria || (task.checklist || []).join("; ");
    if (drawingTaskOwner) drawingTaskOwner.value = task.owner || "Darius";
    if (drawingTaskAgent) drawingTaskAgent.value = task.agent_name || "";
    if (drawingTaskPriority) drawingTaskPriority.value = task.priority || "normal";
    if (drawingTaskDue) drawingTaskDue.value = drawingLocalDateTimeValue(task.due_at);
    if (drawingBoardFormTitle) drawingBoardFormTitle.textContent = mode === "personal" ? "Edit task" : "Edit agent brief";
    if (drawingBoardSaveBrief) drawingBoardSaveBrief.textContent = "SAVE CHANGES";
  }
  if (drawingBoardCreate) {
    drawingBoardCreate.hidden = false;
    drawingTaskTitle?.focus();
  }
}

drawingBoardColumns?.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-drawing-action]");
  if (!button) return;
  const taskId = button.dataset.taskId;
  const action = button.dataset.drawingAction;
  if (action === "edit") {
    const task = state.drawingBoard.find((item) => item.id === taskId);
    if (task) openDrawingBriefForm(task);
    return;
  }
  if (action === "dispatch") {
    try {
      const payload = await drawingBoardPost(drawingBoardDispatchEndpoint, { taskId }, taskId);
      showToast(`${drawingAgentLabels[payload.task?.agent_name] || "Agent"} is working. This card will move to Waiting with the result and any attached files.`);
      await loadDrawingBoard({ silent: true });
    } catch (error) {
      showToast(`Dispatch failed: ${error.message}`);
      renderDrawingBoard();
    }
    return;
  }
  if (action === "verify") {
    if (!window.confirm("Mark this task Done? Its agent notes and work products will remain attached, and you can return it to Todo later.")) return;
    await updateDrawingTask(taskId, { status: "verified_complete", humanVerified: true });
    return;
  }
  if (action === "complete") {
    await updateDrawingTask(taskId, { status: "verified_complete", humanVerified: true });
    return;
  }
  if (action === "start") {
    await updateDrawingTask(taskId, { status: "in_progress" });
    return;
  }
  await updateDrawingTask(taskId, { status: action });
});

drawingBoardNew?.addEventListener("click", () => openDrawingBriefForm());
drawingTaskMode?.addEventListener("change", () => setDrawingTaskMode(drawingTaskMode.value));
drawingBoardCreateClose?.addEventListener("click", closeDrawingBriefForm);
drawingBoardCancel?.addEventListener("click", closeDrawingBriefForm);
drawingBoardBriefClose?.addEventListener("click", () => { if (drawingBoardBriefing) drawingBoardBriefing.hidden = true; });
drawingBoardRefresh?.addEventListener("click", () => loadDrawingBoard());

drawingBoardCreate?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const agentMode = drawingTaskMode?.value === "agent";
  const dueLocal = drawingTaskDue?.value || "";
  const sourceReference = drawingTaskSource?.value.trim() || "";
  if (agentMode) {
    const required = [drawingTaskAgent, drawingTaskRequest, drawingTaskOutcome, drawingTaskNext, drawingTaskAssigneeAction, drawingTaskCriteria];
    const missing = required.find((field) => !field?.value.trim());
    if (missing) {
      if (drawingAdvancedFields) drawingAdvancedFields.open = true;
      missing.focus();
      showToast("Agent-assisted tasks need an agent, request, outcome, next action, expected action, and completion criteria.");
      return;
    }
  }
  const body = {
    title: drawingTaskTitle?.value.trim() || "",
    description: drawingTaskRequest?.value.trim() || (agentMode ? "" : "Personal task or reminder assigned to Darius."),
    requestedOutcome: agentMode ? (drawingTaskOutcome?.value.trim() || "") : "The task is completed and checked off by Darius.",
    nextAction: agentMode ? (drawingTaskNext?.value.trim() || "") : "Darius begins or schedules the task.",
    assigneeAction: agentMode ? (drawingTaskAssigneeAction?.value.trim() || "") : "Darius completes this task or reminder.",
    completionCriteria: agentMode ? (drawingTaskCriteria?.value.trim() || "") : "Darius confirms that the task is complete.",
    sourceType: "operator_reference",
    sourceId: sourceReference || (agentMode ? "" : "operator-created-task"),
    sourceUrl: /^https?:\/\//i.test(sourceReference) ? sourceReference : "",
    owner: agentMode ? (drawingAgentLabels[drawingTaskAgent?.value] || drawingTaskAgent?.value || "") : (drawingTaskOwner?.value.trim() || "Darius"),
    operatorOwned: !agentMode,
    agentName: agentMode ? (drawingTaskAgent?.value || "") : "",
    priority: drawingTaskPriority?.value || "normal",
    dueAt: dueLocal ? new Date(dueLocal).toISOString() : null,
  };
  try {
    if (state.drawingBoardEditingTaskId) {
      const taskId = state.drawingBoardEditingTaskId;
      await drawingBoardPost(
        drawingBoardUpdateEndpoint,
        { taskId, patch: body, actor: "Darius" },
        taskId,
      );
      showToast("Actionable brief updated.");
    } else {
      await drawingBoardPost(drawingBoardCreateEndpoint, { ...body, requester: "Darius", status: "ready" });
      showToast(agentMode ? "Agent task added and ready to dispatch." : "Task added to To do.");
    }
    closeDrawingBriefForm();
    await loadDrawingBoard({ silent: true });
  } catch (error) {
    showToast(`Brief was not saved: ${error.message}`);
  }
});

drawingBoardBrief?.addEventListener("click", () => {
  const brief = state.drawingBoardBriefing || { counts: {}, due_soon: [], stale: [] };
  if (drawingBoardBriefContent) {
    const urgent = state.drawingBoard.filter((task) => ["urgent", "high"].includes(task.priority) && task.status !== "verified_complete").slice(0, 8);
    drawingBoardBriefContent.innerHTML = `
      <p><strong>${brief.counts?.active || 0} active</strong>, ${brief.counts?.due_soon || 0} due soon, ${brief.counts?.stale || 0} stale, ${brief.counts?.evidence_required || 0} awaiting proof.</p>
      <h3>What I am actively correcting or moving</h3>
      ${urgent.length ? `<ul>${urgent.map((task) => `<li><strong>${escapeText(task.title)}</strong> - ${escapeText(task.next_action || "next action pending")}</li>`).join("")}</ul>` : "<p>No high-priority commitments are open.</p>"}
      <p class="drawing-brief-note">Draft only. Nothing is sent to Yaron from this board.</p>`;
  }
  if (drawingBoardBriefing) drawingBoardBriefing.hidden = false;
});

drawingBoardDigest?.addEventListener("click", async () => {
  drawingBoardDigest.disabled = true;
  try {
    await drawingBoardPost(drawingBoardDigestEndpoint, {});
    showToast("Taylor is preparing one quiet internal brief.");
  } catch (error) {
    showToast(`Taylor brief failed: ${error.message}`);
  } finally {
    drawingBoardDigest.disabled = false;
  }
});

const voiceRoomCopy = {
  idle: ["Ready when you are", "Open an agent chat and press Call. Nothing is listening yet."],
  connecting: ["Opening a private audio channel", "Connecting your microphone to the realtime agent..."],
  listening: ["I am listening", "Speak naturally. You can interrupt the agent at any time."],
  transcribing: ["Transcribing locally", "Whisper is turning your audio into text on this computer..."],
  thinking: ["Agent is thinking", "Your selected agent is working through the request..."],
  speaking: ["Agent is speaking", "You can talk over the response to interrupt."],
  failed: ["Voice Room could not connect", "Review the error below, then try joining again."],
};

function voiceRoomIsActive() {
  return Boolean(state.voiceRoom.stream || state.voiceRoom.peer || state.voiceRoom.audioContext);
}

function setVoiceRoomProvider(provider) {
  if (voiceRoomIsActive()) return;
  const normalized = provider === "api" ? "api" : "local";
  state.voiceRoom.provider = normalized;
  voiceRoomProviderButtons.forEach((button) => {
    const selected = button.dataset.voiceProvider === normalized;
    button.setAttribute("aria-checked", String(selected));
    button.classList.toggle("active", selected);
  });
  if (voiceRoomPrivacy) {
    voiceRoomPrivacy.lastChild.textContent = normalized === "local"
      ? " Local mode sends audio only to services on this computer. It never falls back to OpenAI, ElevenLabs, or Microsoft voices."
      : " OpenAI API mode sends audio only during an active WebRTC room. Agent tasks keep their normal approval gates.";
  }
  setVoiceRoomPhase("idle", normalized === "local"
    ? "Local Whisper and Kokoro are selected. Press Join when you want the microphone to start."
    : "OpenAI Realtime WebRTC is selected. Press Join when you want the microphone to start.");
}

function renderVoiceAgentIdentity() {
  const agentKey = state.voiceRoom.agentKey;
  const profile = voiceProfileForAgent(agentKey);
  const label = agentKey ? labelForAgent(agentKey) : "No call selected";
  if (voiceRoomAgentIdentity) voiceRoomAgentIdentity.dataset.agent = agentKey || "none";
  if (voiceRoomAgentAvatar) voiceRoomAgentAvatar.textContent = agentKey ? label.slice(0, 1).toUpperCase() : "—";
  if (voiceRoomAgentName) voiceRoomAgentName.textContent = label;
  if (voiceRoomAgentVoice) voiceRoomAgentVoice.textContent = agentKey ? `${profile.label} · local Kokoro` : "Open chat to call";
}

function currentVoiceAgentKey() {
  return state.voiceRoom.agentKey || "taylor";
}

function currentAttachedVoice() {
  return state.voiceRoom.voice || voiceProfileForAgent(currentVoiceAgentKey()).voice;
}

function setVoiceRoomPhase(phase, detail = "") {
  const normalized = Object.prototype.hasOwnProperty.call(voiceRoomCopy, phase) ? phase : "failed";
  state.voiceRoom.phase = normalized;
  if (voiceRoomShell) voiceRoomShell.dataset.voiceState = normalized;
  if (voiceRoomStateLabel) voiceRoomStateLabel.textContent = normalized.toUpperCase();
  if (voiceRoomPrompt) voiceRoomPrompt.textContent = voiceRoomCopy[normalized][0];
  if (voiceRoomDetail) voiceRoomDetail.textContent = detail || voiceRoomCopy[normalized][1];
  const active = voiceRoomIsActive();
  if (voiceRoomMute) voiceRoomMute.disabled = !active || normalized === "connecting";
  if (voiceRoomEnd) voiceRoomEnd.disabled = !active;
  voiceRoomProviderButtons.forEach((button) => { button.disabled = active || normalized === "connecting"; });
}

function voiceRoomClock() {
  return new Intl.DateTimeFormat([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(new Date());
}

function addVoiceRoomEvent(message, tone = "info") {
  if (!voiceRoomEvents) return;
  const row = document.createElement("div");
  row.className = `voice-event-row ${tone}`;
  const time = document.createElement("time");
  time.textContent = voiceRoomClock();
  const copy = document.createElement("span");
  copy.textContent = String(message || "Session event");
  row.append(time, copy);
  voiceRoomEvents.prepend(row);
  while (voiceRoomEvents.children.length > 40) voiceRoomEvents.lastElementChild?.remove();
}

function ensureVoiceTranscriptEntry(role, id) {
  const key = `${role}:${id || "current"}`;
  let entry = state.voiceRoom.transcriptEntries.get(key);
  if (entry?.isConnected) return entry;
  voiceRoomTranscript?.querySelector(".voice-empty-state")?.remove();
  entry = document.createElement("article");
  entry.className = `voice-transcript-entry ${role}`;
  entry.dataset.transcriptKey = key;
  const meta = document.createElement("header");
  const speaker = document.createElement("strong");
  speaker.textContent = role === "assistant" ? "AGENT" : role === "user" ? "YOU" : "VOICE ROOM";
  const stamp = document.createElement("time");
  stamp.textContent = voiceRoomClock();
  const copy = document.createElement("p");
  meta.append(speaker, stamp);
  entry.append(meta, copy);
  voiceRoomTranscript?.append(entry);
  state.voiceRoom.transcriptEntries.set(key, entry);
  voiceRoomTranscript?.scrollTo({ top: voiceRoomTranscript.scrollHeight, behavior: "smooth" });
  return entry;
}

function updateVoiceTranscript(role, id, text, append = false) {
  const value = String(text || "").trimStart();
  if (!value) return;
  const entry = ensureVoiceTranscriptEntry(role, id);
  const copy = entry.querySelector("p");
  if (!copy) return;
  copy.textContent = append ? `${copy.textContent}${text}` : text;
  voiceRoomTranscript?.scrollTo({ top: voiceRoomTranscript.scrollHeight, behavior: "smooth" });
}

function holdVoiceToolRequest(event) {
  const item = event.item || {};
  const callId = event.call_id || item.call_id || event.item_id || item.id || `tool-${Date.now()}`;
  if (state.voiceRoom.heldToolCalls.has(callId)) return;
  state.voiceRoom.heldToolCalls.add(callId);
  const toolName = event.name || item.name || "agent tool";
  addVoiceRoomEvent(`${toolName} requested. Held for text review; nothing was executed.`, "guarded");
  updateVoiceTranscript("system", callId, `${toolName} request held for text approval. Voice Room cannot execute tools.`, false);
}

function sendVoiceFunctionOutput(callId, result) {
  const channel = state.voiceRoom.channel;
  if (!channel || channel.readyState !== "open") return;
  channel.send(JSON.stringify({
    type: "conversation.item.create",
    item: {
      type: "function_call_output",
      call_id: callId,
      output: JSON.stringify(result),
    },
  }));
  channel.send(JSON.stringify({ type: "response.create" }));
}

function normalizeVoiceAgentKey(value) {
  const key = String(value || "").trim().toLowerCase().replace(/\s+/g, "_");
  return {
    alex: "alex",
    tickets_agent: "alex",
    support: "alex",
    jamie: "jamie",
    billing_agent: "jamie",
    billing: "jamie",
    taylor: "taylor",
    coding_agent: "taylor",
    ops: "taylor",
  }[key] || "";
}

async function executeVoiceAgentSend(event) {
  const item = event.item || {};
  const callId = String(item.call_id || event.call_id || item.id || "").trim();
  if (!callId || state.voiceRoom.heldToolCalls.has(callId)) return;
  state.voiceRoom.heldToolCalls.add(callId);
  let args = {};
  try {
    args = typeof item.arguments === "string" ? JSON.parse(item.arguments) : (item.arguments || {});
  } catch (_error) {
    const result = { ok: false, error: "send_to_agent arguments were not valid JSON" };
    addVoiceRoomEvent(result.error, "error");
    sendVoiceFunctionOutput(callId, result);
    return;
  }
  const agentKey = normalizeVoiceAgentKey(args.agent);
  const message = String(args.message || "").trim();
  if (!agentKey || !message || message.length > 12000) {
    const result = { ok: false, error: !agentKey ? "unknown agent" : !message ? "message is required" : "message is too long" };
    addVoiceRoomEvent(`Agent message was not queued: ${result.error}.`, "error");
    sendVoiceFunctionOutput(callId, result);
    return;
  }
  const idempotencyKey = `voice-chat-${stableHash([callId, agentKey, normalizeDispatchText(message)].join("|"))}`;
  const payload = {
    id: idempotencyKey,
    idempotencyKey,
    type: "agent-direct-chat",
    agent: agentKey,
    agentName: agentNameForKey(agentKey),
    agentLabel: labelForAgent(agentKey),
    message,
    instruction: message,
    createdAt: new Date().toISOString(),
    source: "voice-room",
  };
  addVoiceRoomEvent(`Sending a text task to ${labelForAgent(agentKey)}...`, "guarded");
  try {
    const response = await fetch(agentChatSendEndpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok || body.accepted === false) throw new Error(body.message || `HTTP ${response.status}`);
    const result = { ok: true, status: body.message || "queued", agent: labelForAgent(agentKey), job_id: body.job_id || "" };
    addVoiceRoomEvent(`Text task queued for ${labelForAgent(agentKey)}.`, "success");
    updateVoiceTranscript("system", callId, `Text task queued for ${labelForAgent(agentKey)}.`, false);
    sendVoiceFunctionOutput(callId, result);
  } catch (error) {
    const result = { ok: false, error: error?.message || "agent queue unavailable", agent: labelForAgent(agentKey) };
    addVoiceRoomEvent(`Could not queue ${labelForAgent(agentKey)}: ${result.error}.`, "error");
    sendVoiceFunctionOutput(callId, result);
  }
}

function handleVoiceRoomEvent(raw) {
  let event;
  try {
    event = typeof raw === "string" ? JSON.parse(raw) : raw;
  } catch (_error) {
    addVoiceRoomEvent("Received a non-JSON realtime event.", "muted");
    return;
  }
  const type = String(event?.type || "event");
  if (type === "input_audio_buffer.speech_started") {
    setVoiceRoomPhase("listening", state.voiceRoom.muted ? "Your microphone is muted." : "I hear you. Keep going.");
    return;
  }
  if (type === "input_audio_buffer.speech_stopped") {
    addVoiceRoomEvent("Your turn was sent to the agent.", "success");
    return;
  }
  if (["output_audio_buffer.started", "response.audio.started"].includes(type) || type === "response.audio.delta") {
    setVoiceRoomPhase("speaking");
    return;
  }
  if (["output_audio_buffer.stopped", "response.audio.done", "response.done"].includes(type)) {
    setVoiceRoomPhase("listening", state.voiceRoom.muted ? "Your microphone is muted." : "Speak naturally. You can interrupt the agent at any time.");
  }
  if (["response.audio_transcript.delta", "response.output_audio_transcript.delta"].includes(type)) {
    updateVoiceTranscript("assistant", event.item_id || event.response_id || "assistant-current", event.delta || "", true);
    return;
  }
  if (["response.audio_transcript.done", "response.output_audio_transcript.done"].includes(type)) {
    updateVoiceTranscript("assistant", event.item_id || event.response_id || "assistant-current", event.transcript || "", false);
    return;
  }
  if (type === "conversation.item.input_audio_transcription.completed") {
    updateVoiceTranscript("user", event.item_id || `user-${Date.now()}`, event.transcript || "", false);
    return;
  }
  if (type === "conversation.item.created" && event.item?.type === "message") {
    const text = (event.item.content || []).map((part) => part.transcript || part.text || "").join(" ").trim();
    if (text) updateVoiceTranscript(event.item.role === "assistant" ? "assistant" : "user", event.item.id, text, false);
  }
  if (type === "response.output_item.done" && event.item?.type === "function_call" && event.item?.name === "send_to_agent") {
    executeVoiceAgentSend(event);
    return;
  }
  if (type.includes("function_call") || event.item?.type === "function_call") {
    holdVoiceToolRequest(event);
    return;
  }
  if (type === "error") {
    const message = event.error?.message || event.message || "Realtime service reported an error.";
    addVoiceRoomEvent(message, "error");
  }
}

function waitForIceGathering(peer, timeoutMs = 5000) {
  if (peer.iceGatheringState === "complete") return Promise.resolve();
  return new Promise((resolve) => {
    const timeout = window.setTimeout(done, timeoutMs);
    function done() {
      window.clearTimeout(timeout);
      peer.removeEventListener("icegatheringstatechange", changed);
      resolve();
    }
    function changed() {
      if (peer.iceGatheringState === "complete") done();
    }
    peer.addEventListener("icegatheringstatechange", changed);
  });
}

function voiceRoomErrorMessage(error) {
  if (error?.name === "NotAllowedError" || error?.name === "SecurityError") return "Microphone permission was denied. Allow microphone access for this local page, then try again.";
  if (error?.name === "NotFoundError") return "No microphone was found. Connect one and try again.";
  if (error?.name === "NotReadableError") return "The microphone is busy or unavailable to this browser.";
  if (error?.name === "AbortError") return "Microphone startup was interrupted. Try joining again.";
  return error?.message || "The realtime voice session could not be started.";
}

function resetLocalVoiceBuffers() {
  const room = state.voiceRoom;
  room.pcmChunks = [];
  room.preRollChunks = [];
  room.speechStarted = false;
  room.speechStartedAt = 0;
  room.lastVoiceAt = 0;
  room.bargeFrames = 0;
}

function stopLocalVoicePlayback(message = "") {
  const room = state.voiceRoom;
  if (voiceRoomAudio) {
    voiceRoomAudio.pause();
    voiceRoomAudio.currentTime = 0;
    voiceRoomAudio.removeAttribute("src");
    voiceRoomAudio.load();
  }
  if (room.playbackUrl) URL.revokeObjectURL(room.playbackUrl);
  room.playbackUrl = "";
  if (message) addVoiceRoomEvent(message, "guarded");
}

function mergeFloat32Chunks(chunks) {
  const size = chunks.reduce((total, chunk) => total + chunk.length, 0);
  const merged = new Float32Array(size);
  let offset = 0;
  chunks.forEach((chunk) => {
    merged.set(chunk, offset);
    offset += chunk.length;
  });
  return merged;
}

function downsampleVoicePcm(input, sourceRate, targetRate = 16000) {
  if (sourceRate === targetRate) return input;
  if (sourceRate < targetRate) throw new Error(`Microphone sample rate ${sourceRate} Hz is below the required ${targetRate} Hz.`);
  const ratio = sourceRate / targetRate;
  const output = new Float32Array(Math.round(input.length / ratio));
  for (let i = 0; i < output.length; i += 1) {
    const start = Math.floor(i * ratio);
    const end = Math.min(input.length, Math.floor((i + 1) * ratio));
    let sum = 0;
    for (let j = start; j < end; j += 1) sum += input[j];
    output[i] = sum / Math.max(1, end - start);
  }
  return output;
}

function pcm16WavBlob(samples, sampleRate = 16000) {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const writeText = (offset, text) => [...text].forEach((character, index) => view.setUint8(offset + index, character.charCodeAt(0)));
  writeText(0, "RIFF");
  view.setUint32(4, 36 + samples.length * 2, true);
  writeText(8, "WAVE");
  writeText(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeText(36, "data");
  view.setUint32(40, samples.length * 2, true);
  samples.forEach((sample, index) => {
    const clamped = Math.max(-1, Math.min(1, sample));
    view.setInt16(44 + index * 2, clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff, true);
  });
  return new Blob([buffer], { type: "audio/wav" });
}

function localVoiceReplyForSpeech(reply, maxLength = 2000) {
  const text = String(reply || "").trim();
  if (text.length <= maxLength) return text;
  const candidate = text.slice(0, maxLength);
  const sentenceEnd = Math.max(candidate.lastIndexOf(". "), candidate.lastIndexOf("! "), candidate.lastIndexOf("? "));
  return sentenceEnd >= Math.floor(maxLength * 0.6) ? candidate.slice(0, sentenceEnd + 1) : `${candidate.trimEnd()}...`;
}

async function parseVoiceJson(response) {
  const body = await response.json().catch(() => ({}));
  if (!response.ok || body.ok === false) throw new Error(body.message || body.error || `Voice service returned HTTP ${response.status}.`);
  return body;
}

function voiceAbortableDelay(milliseconds, signal) {
  return new Promise((resolve, reject) => {
    if (signal.aborted) {
      reject(new DOMException("Voice room closed", "AbortError"));
      return;
    }
    const aborted = () => {
      window.clearTimeout(timer);
      reject(new DOMException("Voice room closed", "AbortError"));
    };
    const timer = window.setTimeout(() => {
      signal.removeEventListener("abort", aborted);
      resolve();
    }, milliseconds);
    signal.addEventListener("abort", aborted, { once: true });
  });
}

async function waitForLocalVoiceJob(jobId, signal) {
  const startedAt = Date.now();
  let updatedAt = "";
  while (Date.now() - startedAt < 12 * 60 * 1000) {
    if (signal.aborted) throw new DOMException("Voice room closed", "AbortError");
    const query = new URLSearchParams({ timeout: "20" });
    if (updatedAt) query.set("updated_at", updatedAt);
    const response = await fetch(`${jobsEndpoint}/${encodeURIComponent(jobId)}/wait?${query}`, { signal });
    const body = await parseVoiceJson(response);
    const job = body.job || {};
    updatedAt = String(job.updatedAtUtc || updatedAt);
    const status = String(job.status || "").toLowerCase();
    if (["completed", "completed_with_issues", "blocked", "unclassified", "interrupted", "recovery_review_required"].includes(status)) {
      return String(job.result || job.reviewReason || `The agent ended with status ${status}.`).trim();
    }
    if (["failed", "cancelled", "canceled", "superseded"].includes(status)) {
      throw new Error(job.error || `The agent job ended with status ${status}.`);
    }
  }
  throw new Error("The agent took longer than 12 minutes to respond.");
}

async function playLocalVoiceReply(audioBlob, sessionId, finalChunk = true) {
  const room = state.voiceRoom;
  if (sessionId !== room.localSessionId || !voiceRoomAudio) return;
  stopLocalVoicePlayback();
  room.playbackUrl = URL.createObjectURL(audioBlob);
  voiceRoomAudio.srcObject = null;
  voiceRoomAudio.src = room.playbackUrl;
  setVoiceRoomPhase("speaking", "Talk over the reply to stop playback and begin a new turn.");
  await voiceRoomAudio.play();
  await new Promise((resolve) => {
    const done = () => {
      voiceRoomAudio.removeEventListener("ended", done);
      voiceRoomAudio.removeEventListener("pause", done);
      resolve();
    };
    voiceRoomAudio.addEventListener("ended", done, { once: true });
    voiceRoomAudio.addEventListener("pause", done, { once: true });
  });
  if (finalChunk && sessionId === room.localSessionId && voiceRoomIsActive()) {
    stopLocalVoicePlayback();
    room.localBusy = false;
    resetLocalVoiceBuffers();
    setVoiceRoomPhase("listening");
  }
}

async function processLocalVoiceTurn(chunks, sampleRate, sessionId) {
  const room = state.voiceRoom;
  const controller = room.localAbortController;
  if (!controller || sessionId !== room.localSessionId) return;
  try {
    const turnStartedAt = performance.now();
    setVoiceRoomPhase("transcribing");
    addVoiceRoomEvent("Speech ended. Sending one local WAV turn to Whisper...", "info");
    const merged = mergeFloat32Chunks(chunks);
    const wav = pcm16WavBlob(downsampleVoicePcm(merged, sampleRate));
    const transcriptionResponse = await fetch(voiceRoomLocalTranscribeEndpoint, {
      method: "POST",
      headers: { "Content-Type": "audio/wav" },
      body: wav,
      signal: controller.signal,
    });
    const transcription = await parseVoiceJson(transcriptionResponse);
    const text = String(transcription.transcript || transcription.text || "").trim();
    if (!text) throw new Error("Whisper returned an empty transcript. Please try that turn again.");
    if (sessionId !== room.localSessionId) return;
    const turnId = `local-user-${Date.now()}`;
    updateVoiceTranscript("user", turnId, text, false);
    addVoiceRoomEvent(`Got it — local transcription completed in ${Math.round(performance.now() - turnStartedAt)} ms. Audio was not sent to a cloud voice provider.`, "success");

    const agentKey = normalizeVoiceAgentKey(currentVoiceAgentKey()) || "taylor";
    const idempotencyKey = `local-voice-${stableHash([sessionId, turnId, agentKey, normalizeDispatchText(text)].join("|"))}`;
    const agentPayload = {
      id: idempotencyKey,
      idempotencyKey,
      type: "agent-direct-chat",
      agent: agentKey,
      agentName: agentNameForKey(agentKey),
      agentLabel: labelForAgent(agentKey),
      message: text,
      instruction: text,
      createdAt: new Date().toISOString(),
      source: "voice-room-local",
    };
    setVoiceRoomPhase("thinking", `${labelForAgent(agentKey)} is working through your request...`);
    addVoiceRoomEvent(`Sending the transcript to ${labelForAgent(agentKey)} through the existing agent queue...`, "guarded");
    const agentResponse = await fetch(agentChatSendEndpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(agentPayload),
      signal: controller.signal,
    });
    const queued = await parseVoiceJson(agentResponse);
    if (queued.accepted === false || !queued.job_id) throw new Error(queued.message || "The agent task was not queued.");
    addVoiceRoomEvent(`Agent dispatched after ${Math.round(performance.now() - turnStartedAt)} ms.`, "info");
    const reply = await waitForLocalVoiceJob(queued.job_id, controller.signal);
    if (!reply) throw new Error(`${labelForAgent(agentKey)} completed without a text reply.`);
    if (sessionId !== room.localSessionId) return;
    updateVoiceTranscript("assistant", `local-assistant-${queued.job_id}`, reply, false);
    addVoiceRoomEvent(`${labelForAgent(agentKey)} replied after ${Math.round(performance.now() - turnStartedAt)} ms. Synthesizing the first sentence first...`, "success");
    const speech = localVoiceReplyForSpeech(reply);
    const firstEnd = speech.search(/[.!?](?:\s|$)/);
    const chunksToSpeak = firstEnd >= 0 && firstEnd + 1 < speech.length
      ? [speech.slice(0, firstEnd + 1), speech.slice(firstEnd + 1).trim()].filter(Boolean)
      : [speech];
    for (let index = 0; index < chunksToSpeak.length; index += 1) {
      const synthesisResponse = await fetch(voiceRoomLocalSynthesizeEndpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: chunksToSpeak[index], voice: currentAttachedVoice() }),
        signal: controller.signal,
      });
      if (!synthesisResponse.ok) {
        const failure = await synthesisResponse.json().catch(() => ({}));
        throw new Error(failure.message || failure.error || `Local synthesis returned HTTP ${synthesisResponse.status}.`);
      }
      const audio = await synthesisResponse.blob();
      if (!audio.size) throw new Error("Kokoro returned no audio.");
      if (index === 0) addVoiceRoomEvent(`Playback started after ${Math.round(performance.now() - turnStartedAt)} ms.`, "success");
      await playLocalVoiceReply(audio, sessionId, index === chunksToSpeak.length - 1);
    }
  } catch (error) {
    if (error?.name === "AbortError" || sessionId !== room.localSessionId) return;
    room.localBusy = false;
    resetLocalVoiceBuffers();
    setVoiceRoomPhase("failed", error?.message || "The local voice turn failed.");
    addVoiceRoomEvent(error?.message || "The local voice turn failed.", "error");
  }
}

function handleLocalVoiceAudio(event) {
  const room = state.voiceRoom;
  if (room.provider !== "local" || room.muted || !room.stream) return;
  const input = event.inputBuffer.getChannelData(0);
  const copy = new Float32Array(input);
  let energy = 0;
  for (let i = 0; i < copy.length; i += 1) energy += copy[i] * copy[i];
  const rms = Math.sqrt(energy / Math.max(1, copy.length));
  const now = performance.now();
  const threshold = 0.018;

  if (room.phase === "speaking") {
    room.bargeFrames = rms >= 0.032 ? room.bargeFrames + 1 : 0;
    if (room.bargeFrames >= 3) {
      stopLocalVoicePlayback("Barge-in detected. Local playback stopped.");
      room.localBusy = false;
      resetLocalVoiceBuffers();
      setVoiceRoomPhase("listening", "I stopped the reply. Keep speaking to start a new turn.");
    }
    return;
  }
  if (room.localBusy) return;

  if (!room.speechStarted) {
    room.preRollChunks.push(copy);
    const maxPreRoll = Math.max(2, Math.ceil((room.audioContext?.sampleRate || 48000) * 0.35 / copy.length));
    while (room.preRollChunks.length > maxPreRoll) room.preRollChunks.shift();
    if (rms < threshold) return;
    room.speechStarted = true;
    room.speechStartedAt = now;
    room.lastVoiceAt = now;
    room.pcmChunks = room.preRollChunks.splice(0);
    setVoiceRoomPhase("listening", "I hear you. Pause for a moment when your turn is complete.");
    return;
  }

  room.pcmChunks.push(copy);
  if (rms >= threshold) room.lastVoiceAt = now;
  const speechMs = now - room.speechStartedAt;
  if (speechMs >= 30000 || (speechMs >= 350 && now - room.lastVoiceAt >= 600)) {
    const turnChunks = room.pcmChunks.splice(0);
    const sampleRate = room.audioContext?.sampleRate || event.inputBuffer.sampleRate || 48000;
    room.localBusy = true;
    resetLocalVoiceBuffers();
    processLocalVoiceTurn(turnChunks, sampleRate, room.localSessionId);
  }
}

async function joinLocalVoiceRoom() {
  const room = state.voiceRoom;
  if (voiceRoomIsActive() || room.phase === "connecting") return;
  if (!navigator.mediaDevices?.getUserMedia || !(window.AudioContext || window.webkitAudioContext)) {
    closeVoiceRoom({ failed: true, message: "This browser does not support local microphone capture." });
    return;
  }
  setVoiceRoomPhase("connecting", "Opening the microphone for local Whisper capture...");
  addVoiceRoomEvent("Checking the local Whisper and Kokoro runtime...", "info");
  try {
    const statusResponse = await fetch(voiceRoomLocalStatusEndpoint, { method: "GET" });
    const status = await parseVoiceJson(statusResponse);
    if (!status.ready) {
      const missing = Array.isArray(status.missing) && status.missing.length ? ` Missing: ${status.missing.join(", ")}.` : "";
      throw new Error(`Local voice is not ready yet.${missing}`);
    }
    setVoiceRoomPhase("connecting", "Warming Whisper and Kokoro while opening the microphone...");
    const warmupPromise = fetch(voiceRoomLocalWarmupEndpoint, { method: "POST" }).then(parseVoiceJson);
    addVoiceRoomEvent("Local runtime is ready. Warming both speech models now...", "success");
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
      video: false,
    });
    const warmup = await warmupPromise;
    const device = [warmup.whisperActiveDevice, warmup.whisperActiveComputeType].filter(Boolean).join("-");
    const fallback = warmup.whisperFallbackUsed ? " (CPU fallback active)" : "";
    addVoiceRoomEvent(`Speech models ready${device ? ` on ${device}` : ""}${fallback} in ${warmup.gatewayWarmupMs || warmup.warmupMs || 0} ms.`, warmup.whisperFallbackUsed ? "guarded" : "success");
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    const context = new AudioContextClass();
    await context.resume();
    const source = context.createMediaStreamSource(stream);
    const processor = context.createScriptProcessor(4096, 1, 1);
    const silentGain = context.createGain();
    silentGain.gain.value = 0;
    processor.addEventListener("audioprocess", handleLocalVoiceAudio);
    source.connect(processor);
    processor.connect(silentGain);
    silentGain.connect(context.destination);
    room.stream = stream;
    room.audioContext = context;
    room.sourceNode = source;
    room.processorNode = processor;
    room.silentGainNode = silentGain;
    room.localAbortController = new AbortController();
    room.localSessionId += 1;
    room.localBusy = false;
    resetLocalVoiceBuffers();
    setVoiceRoomPhase("listening", "Local microphone is live. Pause briefly when your turn is complete.");
    addVoiceRoomEvent("Local room joined. Whisper and Kokoro will stay on this computer.", "success");
  } catch (error) {
    closeVoiceRoom({ failed: true, message: voiceRoomErrorMessage(error) });
  }
}

function closeVoiceRoom({ failed = false, message = "" } = {}) {
  const room = state.voiceRoom;
  room.localSessionId += 1;
  room.localAbortController?.abort();
  room.localAbortController = null;
  stopLocalVoicePlayback();
  try { room.channel?.close(); } catch (_error) { /* already closed */ }
  try { room.peer?.close(); } catch (_error) { /* already closed */ }
  try { room.sourceNode?.disconnect(); } catch (_error) { /* already disconnected */ }
  try { room.processorNode?.disconnect(); } catch (_error) { /* already disconnected */ }
  try { room.silentGainNode?.disconnect(); } catch (_error) { /* already disconnected */ }
  try { room.audioContext?.close(); } catch (_error) { /* already closed */ }
  room.stream?.getTracks().forEach((track) => track.stop());
  room.peer = null;
  room.channel = null;
  room.stream = null;
  room.audioContext = null;
  room.sourceNode = null;
  room.processorNode = null;
  room.silentGainNode = null;
  room.localBusy = false;
  resetLocalVoiceBuffers();
  room.muted = false;
  if (voiceRoomAudio) {
    voiceRoomAudio.srcObject = null;
    voiceRoomAudio.removeAttribute("src");
  }
  if (voiceRoomMute) {
    voiceRoomMute.setAttribute("aria-pressed", "false");
    voiceRoomMute.classList.remove("muted");
    const label = voiceRoomMute.querySelector("strong");
    if (label) label.textContent = "MUTE";
  }
  if (failed) {
    setVoiceRoomPhase("failed", message || voiceRoomCopy.failed[1]);
    addVoiceRoomEvent(message || "Voice connection failed.", "error");
  } else {
    setVoiceRoomPhase("idle");
    if (message) addVoiceRoomEvent(message, "muted");
  }
}

async function joinVoiceRoom() {
  if (state.voiceRoom.provider === "local") {
    await joinLocalVoiceRoom();
    return;
  }
  if (state.voiceRoom.peer || state.voiceRoom.phase === "connecting") return;
  if (!navigator.mediaDevices?.getUserMedia || typeof RTCPeerConnection === "undefined") {
    closeVoiceRoom({ failed: true, message: "This browser does not support secure WebRTC microphone sessions." });
    return;
  }
  setVoiceRoomPhase("connecting");
  addVoiceRoomEvent("Requesting microphone permission...", "info");
  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      video: false,
    });
    const peer = new RTCPeerConnection();
    const channel = peer.createDataChannel("oai-events");
    state.voiceRoom.stream = stream;
    state.voiceRoom.peer = peer;
    state.voiceRoom.channel = channel;
    stream.getTracks().forEach((track) => peer.addTrack(track, stream));
    peer.addEventListener("track", (event) => {
      if (!voiceRoomAudio) return;
      voiceRoomAudio.srcObject = event.streams[0] || new MediaStream([event.track]);
      voiceRoomAudio.play().catch(() => addVoiceRoomEvent("Press the page once if browser audio remains paused.", "guarded"));
    });
    peer.addEventListener("connectionstatechange", () => {
      addVoiceRoomEvent(`WebRTC connection: ${peer.connectionState}.`, peer.connectionState === "connected" ? "success" : "info");
      if (peer.connectionState === "connected") setVoiceRoomPhase("listening");
      if (["failed"].includes(peer.connectionState)) closeVoiceRoom({ failed: true, message: "The realtime audio connection failed. You can safely try joining again." });
    });
    channel.addEventListener("open", () => {
      addVoiceRoomEvent("Realtime event channel is open.", "success");
      setVoiceRoomPhase("listening");
    });
    channel.addEventListener("message", (event) => handleVoiceRoomEvent(event.data));
    channel.addEventListener("close", () => addVoiceRoomEvent("Realtime event channel closed.", "muted"));
    channel.addEventListener("error", () => addVoiceRoomEvent("Realtime event channel reported an error.", "error"));

    const offer = await peer.createOffer();
    await peer.setLocalDescription(offer);
    await waitForIceGathering(peer);
    const selectedVoice = currentAttachedVoice();
    const voice = ["marin", "coral", "shimmer", "cedar"].includes(selectedVoice) ? selectedVoice : "marin";
    addVoiceRoomEvent(`Connecting with the ${voice} voice...`, "info");
    const response = await fetch(`${voiceRoomSessionEndpoint}?voice=${encodeURIComponent(voice)}`, {
      method: "POST",
      headers: { "Content-Type": "application/sdp", Accept: "application/sdp, application/json" },
      body: peer.localDescription?.sdp || offer.sdp,
    });
    const contentType = response.headers.get("content-type") || "";
    let answerSdp = "";
    let errorDetail = "";
    if (contentType.includes("application/json")) {
      const payload = await response.json();
      answerSdp = payload.sdp || payload.answerSdp || payload.answer_sdp || "";
      errorDetail = payload.error || payload.message || "";
    } else {
      answerSdp = await response.text();
    }
    if (!response.ok) throw new Error(errorDetail || answerSdp || `Voice service returned HTTP ${response.status}.`);
    if (!answerSdp.trim()) throw new Error("Voice service returned no WebRTC answer. Check the local API configuration.");
    await peer.setRemoteDescription({ type: "answer", sdp: answerSdp });
    addVoiceRoomEvent("Secure audio negotiation completed.", "success");
  } catch (error) {
    closeVoiceRoom({ failed: true, message: voiceRoomErrorMessage(error) });
  }
}

async function startAgentVoiceCall(agentKey) {
  const normalized = normalizeVoiceAgentKey(agentKey);
  if (!normalized) return;
  if (voiceRoomIsActive()) {
    if (state.voiceRoom.agentKey !== normalized) {
      showToast(`End the current ${labelForAgent(state.voiceRoom.agentKey)} call before calling ${labelForAgent(normalized)}.`);
      return;
    }
    activateView("voice-room");
    closeAgentChat();
    return;
  }
  const profile = voiceProfileForAgent(normalized);
  state.voiceRoom.agentKey = normalized;
  state.voiceRoom.voice = profile.voice;
  setVoiceRoomProvider("local");
  renderVoiceAgentIdentity();
  activateView("voice-room");
  closeAgentChat();
  addVoiceRoomEvent(`${labelForAgent(normalized)} selected with the attached ${profile.label} voice.`, "info");
  await joinLocalVoiceRoom();
  renderAgentChatCall();
}

voiceRoomProviderButtons.forEach((button) => button.addEventListener("click", () => setVoiceRoomProvider(button.dataset.voiceProvider)));
voiceRoomMute?.addEventListener("click", () => {
  const room = state.voiceRoom;
  if (!room.stream) return;
  room.muted = !room.muted;
  room.stream.getAudioTracks().forEach((track) => { track.enabled = !room.muted; });
  voiceRoomMute.setAttribute("aria-pressed", String(room.muted));
  voiceRoomMute.classList.toggle("muted", room.muted);
  const label = voiceRoomMute.querySelector("strong");
  if (label) label.textContent = room.muted ? "UNMUTE" : "MUTE";
  const keepWorkingPhase = room.provider === "local" && room.localBusy && ["transcribing", "thinking", "speaking"].includes(room.phase);
  setVoiceRoomPhase(keepWorkingPhase ? room.phase : "listening", room.muted ? "Your microphone is muted. Agent audio remains on." : "Microphone is live again.");
  addVoiceRoomEvent(room.muted ? "Microphone muted." : "Microphone unmuted.", room.muted ? "guarded" : "success");
});
voiceRoomEnd?.addEventListener("click", () => closeVoiceRoom({ message: "You left the Voice Room. Microphone is off." }));
voiceRoomClear?.addEventListener("click", () => {
  state.voiceRoom.transcriptEntries.clear();
  if (voiceRoomTranscript) voiceRoomTranscript.innerHTML = '<div class="voice-empty-state"><strong>No conversation yet</strong><span>Your transcript will appear here after you start a call from agent chat.</span></div>';
});
window.addEventListener("beforeunload", () => closeVoiceRoom());
setVoiceRoomProvider("local");
renderVoiceAgentIdentity();

function activateView(view) {
  document.querySelectorAll("[data-view-button]").forEach((item) => item.classList.toggle("active", item.dataset.viewButton === view));
  document.querySelectorAll("[data-view]").forEach((surface) => surface.classList.toggle("active", surface.dataset.view === view));
  if (view === "email") loadEmailWatch();
  if (view === "drawing-board") loadDrawingBoard({ silent: state.drawingBoardLoaded });
}

document.querySelectorAll("[data-view-button]").forEach((button) => {
  button.addEventListener("click", () => activateView(button.dataset.viewButton));
});

document.addEventListener("pointerdown", (event) => {
  const target = event.target;
  if (state.agentChatOpen && agentChatDrawer && !agentChatDrawer.contains(target) && !target.closest?.("[data-agent-link]")) {
    closeAgentChat();
  }
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && state.agentChatOpen) closeAgentChat();
});

function showToast(message) {
  const toast = document.createElement("div");
  toast.className = "toast";
  toast.textContent = message;
  toastStack.prepend(toast);
  window.setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transform = "translateY(8px)";
    window.setTimeout(() => toast.remove(), 250);
  }, 3000);
}

loadAgentChatLastSeen();
loadAuthenticationContext();
initLeftRailToggle();
renderStats();
renderAgentList();
renderKanban();
renderActivity();
renderAnalytics();
loadDashboardState({ full: true });
refreshUsageAnalytics(true);
document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    scheduleDashboardPoll(dashboardPollHiddenMs);
  } else {
    loadDashboardState({ full: true });
  }
});
bootstrapOffice();

function point(nameOrPoint) {
  return typeof nameOrPoint === "string" ? officeNodes[nameOrPoint] : nameOrPoint;
}

function routePoints(names) {
  return names.map(point).filter(Boolean);
}

function currentPoint(agentKey) {
  return state.agentLocations[agentKey] || point(agentConfig[agentKey]?.home);
}

function namedRoute(agentKey, destinationName) {
  const config = agentConfig[agentKey];
  if (!config) return [];
  const destination = point(destinationName);
  const base = routePoints(config.route);
  if (!destination) return base;
  const route = [currentPoint(agentKey), ...base.slice(1)];
  const last = route[route.length - 1];
  if (!last || last.x !== destination.x || last.y !== destination.y) {
    route.push(destination);
  }
  return dedupeRoute(route);
}

function homeRoute(agentKey) {
  const config = agentConfig[agentKey];
  if (!config) return [];
  return dedupeRoute([currentPoint(agentKey), ...routePoints(config.route).reverse().slice(1), point(config.home)]);
}

function waitRoute(agentKey) {
  const config = agentConfig[agentKey];
  if (!config) return [];
  return dedupeRoute([currentPoint(agentKey), ...routePoints(config.waitRoute || [config.home, config.wait]).slice(1)]);
}

function deskToDeskRoute(fromAgent, toAgent) {
  const fromConfig = agentConfig[fromAgent];
  const toConfig = agentConfig[toAgent];
  if (!fromConfig || !toConfig) return [];
  return dedupeRoute([
    currentPoint(fromAgent),
    ...routePoints(fromConfig.route).slice(1),
    ...routePoints(toConfig.route).reverse().slice(1),
  ]);
}

function dedupeRoute(route) {
  return route.filter((item, index) => {
    const prev = route[index - 1];
    return item && (!prev || item.x !== prev.x || item.y !== prev.y);
  });
}

function setAgentPosition(agentKey, nextPoint, instant = false) {
  const element = agentElements[agentKey] || (agentKey === "you" ? youElement : null);
  if (!element || !nextPoint) return;
  if (instant) {
    element.style.transitionDuration = "0ms";
  } else {
    const previous = currentPoint(agentKey);
    const distance = Math.hypot(nextPoint.x - previous.x, nextPoint.y - previous.y);
    const duration = Math.max(360, Math.min(1150, distance * 42));
    element.style.transitionDuration = `${duration}ms`;
  }
  element.style.left = `${nextPoint.x}%`;
  element.style.top = `${nextPoint.y}%`;
  element.style.zIndex = String(20 + Math.round(nextPoint.y));
  state.agentLocations[agentKey] = { ...nextPoint };
}

function sleep(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function queueAgentMove(agentKey, task) {
  const current = state.agentMoves[agentKey] || Promise.resolve();
  state.agentMoves[agentKey] = current.then(task).catch(() => undefined);
  return state.agentMoves[agentKey];
}

async function moveAgent(agentKey, route, finalState = "working") {
  const element = agentElements[agentKey];
  if (!element || route.length < 1) return;
  drawRoute(agentKey, route);
  element.classList.add("walking");
  element.dataset.state = "working";
  for (const next of route) {
    setAgentPosition(agentKey, next);
    await sleep(620);
  }
  element.classList.remove("walking");
  element.dataset.state = finalState;
  clearRoute(agentKey);
}

function drawRoute(agentKey, route) {
  const line = document.querySelector(`#route-${agentKey}`);
  if (!line) return;
  line.setAttribute("points", route.map((item) => `${item.x},${item.y}`).join(" "));
  line.classList.add("active");
}

function clearRoute(agentKey) {
  const line = document.querySelector(`#route-${agentKey}`);
  if (!line) return;
  line.classList.remove("active");
  line.setAttribute("points", "");
}

function receiveTask(agentKey, ticketId) {
  queueAgentMove(agentKey, async () => {
    await moveAgent(agentKey, namedRoute(agentKey, "handoff"), "working");
    await sleep(350);
    await moveAgent(agentKey, homeRoute(agentKey), "working");
    showToast(`${ticketId || "Task"} is now being worked at ${labelForAgent(agentKey)}'s desk.`);
  });
}

function handoffTask(fromAgent, toAgent, ticketId) {
  queueAgentMove(fromAgent, async () => {
    await moveAgent(fromAgent, deskToDeskRoute(fromAgent, toAgent), "working");
    await sleep(450);
    await moveAgent(fromAgent, homeRoute(fromAgent), "working");
    agentElements[toAgent].dataset.state = "working";
    showToast(`${labelForAgent(fromAgent)} handed ${ticketId || "the task"} to ${labelForAgent(toAgent)}.`);
  });
}

function completeAgentWork(agentKey, reason) {
  queueAgentMove(agentKey, async () => {
    await moveAgent(agentKey, namedRoute(agentKey, "handoff"), "complete");
    await sleep(650);
    await moveAgent(agentKey, homeRoute(agentKey), "complete");
    showToast(`${labelForAgent(agentKey)} delivered completed work${reason ? ` (${reason})` : ""}.`);
  });
}

function waitForFeedback(agentKey) {
  queueAgentMove(agentKey, async () => {
    await moveAgent(agentKey, waitRoute(agentKey), "waiting");
    showToast(`${labelForAgent(agentKey)} is waiting near you for feedback.`);
  });
}

function updateOfficeAgentPresentation(agentKey, mode, decision = "") {
  const element = agentElements[agentKey];
  if (!element) return;
  const label = labelForAgent(agentKey);
  const icon = element.querySelector(".agent-status-icon");
  element.dataset.state = mode;
  if (mode === "waiting") {
    const safeDecision = truncateText(decision || "Operator decision required.", 180);
    element.title = `Waiting on Darius: ${safeDecision}`;
    element.setAttribute("aria-label", `${label} is waiting on Darius for a decision: ${safeDecision}`);
    if (icon) icon.title = `Waiting on Darius: ${safeDecision}`;
  } else if (element.dataset.qualityOnly === "true") {
    element.title = `${label} accepts read-only support-quality tasks, not Salesforce tickets.`;
    element.setAttribute(
      "aria-label",
      `${label} — Support Quality; accepts general quality tasks only`,
    );
    if (icon) icon.removeAttribute("title");
  } else {
    element.removeAttribute("title");
    element.setAttribute("aria-label", `Drop ticket on ${label}`);
    if (icon) icon.removeAttribute("title");
  }
}

function officeAgentMode(agentKey) {
  if (agentHasActiveJob(agentKey)) return { mode: "working", decision: "" };
  const decision = agentDecisionRequest(agentKey);
  return decision ? { mode: "waiting", decision } : { mode: "idle", decision: "" };
}

function syncOfficeAgentStates(options = {}) {
  const instant = options.instant === true;
  Object.keys(agentConfig).forEach((agentKey) => {
    const next = officeAgentMode(agentKey);
    const previous = state.officeAgentModes[agentKey] || "";
    state.officeAgentModes[agentKey] = next.mode;
    updateOfficeAgentPresentation(agentKey, next.mode, next.decision);
    if (previous === next.mode && !instant) return;
    const destination = next.mode === "waiting"
      ? point(agentConfig[agentKey].wait)
      : point(agentConfig[agentKey].home);
    if (instant) {
      setAgentPosition(agentKey, destination, true);
      return;
    }
    queueAgentMove(agentKey, async () => {
      if (state.officeAgentModes[agentKey] !== next.mode) return;
      const route = next.mode === "waiting" ? waitRoute(agentKey) : homeRoute(agentKey);
      await moveAgent(agentKey, route, next.mode);
      updateOfficeAgentPresentation(agentKey, next.mode, next.decision);
    });
  });
}

function labelForAgent(agentKey) {
  const label = agentElements[agentKey]?.querySelector(".agent-label")?.childNodes[0]?.textContent?.trim();
  return label || agentKey;
}

function bootstrapOffice() {
  Object.entries(agentConfig).forEach(([agentKey, config]) => {
    setAgentPosition(agentKey, point(config.home), true);
    updateOfficeAgentPresentation(agentKey, "idle");
  });
  setAgentPosition("you", point("leadDesk"), true);
  syncOfficeAgentStates({ instant: true });
}
