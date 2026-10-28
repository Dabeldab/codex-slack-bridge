<!-- AgentChat/coding_agent 2026-07-09T02:05:00Z -->

# Bad Customer Care Training Examples

Source bundle: `data/agent_sandboxes/tickets_agent/support_resolution_research_20260709`

Use these as examples of what not to count as resolution evidence.

## Generic Closure

Bad pattern: "Done", "fixed", "solved", "all set", or "Darius fixed it" with no technical step.

Why it is bad: The support agent cannot reuse the record because it does not say what changed.

Required replacement: State the exact action, system area, and verification.

## .NET Stack Without Fix

Source pattern: Telerik/.NET user settings error with `RadSpinEditor` and "'0.00' is not valid."

Bad pattern: Support pushed a setup file, customer said the error remained, and the ticket was left unresolved.

Why it is bad: This is not a playbook fix. It is an escalation pattern.

Required replacement: Capture affected users, whether manager User ID 1 is unaffected, full exception text, screenshot, and exact screen path, then escalate.

## Remote Session With No Dialogue

Bad pattern: Remote control started, ended, or customer disconnected with no issue details.

Why it is bad: No support action or outcome exists.

Required replacement: Mark as connection lost/no support dialogue, and do not close as resolved unless a later session confirms resolution.

## Printer Reboot Without Confirmation

Bad pattern: Rebooted PC, sent a printer-fix file, or cleared spooler, but no customer confirmation that Nova printed.

Why it is bad: Driver work is not the same as business workflow success.

Required replacement: Confirm Windows test print and Nova receipt print, then record the result.

## External Credit Card Machine Menu Mismatch

Bad pattern: Generic reprint instructions were provided, but the customer's terminal did not have the described buttons/menu.

Why it is bad: The support step failed and the issue remained unresolved.

Required replacement: Record terminal model, exact menu mismatch, provider boundary, and next owner.

## Refund Payment Method Change

Bad pattern: "Developer team will fix" without invoice context, current wrong payment method, requested payment method, and customer notification plan.

Why it is bad: The agent cannot act safely or communicate status.

Required replacement: Confirm original invoice, refund invoice, wrong/current payment method, requested corrected method, whether support can edit it, and who owns the correction.

## Passwords Or Company Credentials In Notes

Bad pattern: Actual passwords, company usernames, account names, or customer phone/email values are preserved in support notes or training examples.

Why it is bad: It creates a security and privacy issue.

Required replacement: Redact secrets and use placeholders such as `[company]`, `[password]`, `[phone]`, and `[email]`.
