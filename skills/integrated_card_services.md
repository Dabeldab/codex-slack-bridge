# Integrated Card Services Onboarding

Use for PropelrPay/NMI integrated-card-services signup emails and their guarded
Salesforce setup-ticket workflow.

- Automatic scans run every two hours, Monday-Friday, 9:00 AM-7:00 PM in
  `America/New_York`; routine/no-match results remain silent.
- Search only the trusted sender/query and process only unread messages that
  contain a clear setup intent plus API/security/tokenization key fields.
- Keep raw keys only in the intended private Salesforce technical field. Never
  place them in chat, logs, Chatter, cache JSON, or artifacts.
- Resolve the Salesforce Account read-only. Ambiguous account means no ticket and
  the source stays unread. Location is optional when the account is unique.
- Use stable message/ticket idempotency, create at most one ticket per source,
  read it back, then mark the exact source message read.
