// AgentChat/coding_agent 2026-07-10T01:09:00Z
// Sanitized offline fallback only. Live data is loaded from the local command-center gateway.
window.NOVA_OPS_TICKET_DATA = {
  generatedAt: "2026-07-10T01:09:00Z",
  source: "Sanitized local fallback data; live dashboard uses http://127.0.0.1:17866/ops/tickets.",
  total: 3,
  columns: [
    {
      key: "support",
      label: "Support Tickets",
      tickets: [
        {
          id: "fallback-support-001",
          number: "SUP-001",
          url: "#",
          createdAt: "2026-07-09T14:00:00Z",
          updatedAt: "2026-07-09T16:30:00Z",
          daysActive: 1,
          account: "Harbor Salon",
          contact: "Operations Contact",
          openedBy: "Support Desk",
          owner: "Alex",
          recordType: "1. NOVA Classic",
          status: "Open",
          isClosed: false,
          closedAt: "",
          mainIssue: "Hardware",
          technicalIssue: "Receipt Printer",
          priority: "Medium",
          notesPreview: "Printer is not responding after a workstation restart.",
          notesFull: "Technical Notes:\nPrinter is not responding after a workstation restart. Verify Windows printer status, power, USB/network connection, and default printer mapping before escalating.",
          sessionHistorySummary: "",
          sessionHistoryItems: [],
          chatterSummary: "No live Chatter in sanitized fallback data.",
          chatterItems: [],
          lane: "support"
        }
      ]
    },
    {
      key: "billing",
      label: "Billing Tickets",
      tickets: [
        {
          id: "fallback-billing-001",
          number: "BIL-001",
          url: "#",
          createdAt: "2026-07-08T18:00:00Z",
          updatedAt: "2026-07-09T15:20:00Z",
          daysActive: 2,
          account: "Northline Spa",
          contact: "Billing Contact",
          openedBy: "Customer Care",
          owner: "Jamie",
          recordType: "3. Billing",
          status: "Open",
          isClosed: false,
          closedAt: "",
          mainIssue: "Billing",
          technicalIssue: "Invoice Question",
          priority: "Low",
          notesPreview: "Customer requested clarification on a monthly invoice line item.",
          notesFull: "Technical Notes:\nCustomer requested clarification on a monthly invoice line item. Review Maxio readback before drafting the customer update.",
          sessionHistorySummary: "",
          sessionHistoryItems: [],
          chatterSummary: "No live Chatter in sanitized fallback data.",
          chatterItems: [],
          lane: "billing"
        }
      ]
    },
    {
      key: "review",
      label: "Needs Review",
      tickets: [
        {
          id: "fallback-review-001",
          number: "REV-001",
          url: "#",
          createdAt: "2026-07-09T12:00:00Z",
          updatedAt: "2026-07-09T17:15:00Z",
          daysActive: 1,
          account: "Metro Beauty",
          contact: "Store Manager",
          openedBy: "Ops",
          owner: "Taylor",
          recordType: "2. Nova Wave",
          status: "Needs Review",
          isClosed: false,
          closedAt: "",
          mainIssue: "Operations",
          technicalIssue: "Follow-up",
          priority: "Medium",
          notesPreview: "Agent result is waiting for operator review.",
          notesFull: "Technical Notes:\nAgent result is waiting for operator review. Use live data before taking action.",
          sessionHistorySummary: "",
          sessionHistoryItems: [],
          chatterSummary: "No live Chatter in sanitized fallback data.",
          chatterItems: [],
          lane: "review"
        }
      ]
    }
  ],
  agentActivity: [
    { agent: "alex", name: "Alex", role: "Tech Support · Tickets", state: "working", load: 1 },
    { agent: "jamie", name: "Jamie", role: "Tech Support · Billing", state: "working", load: 1 },
    { agent: "taylor", name: "Taylor", role: "Tech Support · Engineering", state: "idle", load: 0 },
  ],
  analytics: {
    openTickets: 3,
    staleTickets: 0,
    missingAccount: 0
  }
};
