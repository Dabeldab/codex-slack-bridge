<!-- AgentChat/coding_agent 2026-07-09T02:05:00Z -->

# Good Customer Care Training Examples

Source bundle: `data/agent_sandboxes/tickets_agent/support_resolution_research_20260709`

Use these as examples of actionable support notes or agent behavior.

## Report / Re-index

Source: Salesforce ticket 347048 and matching Rescue chat pattern.

Problem: Customer requested re-index, then employee scorecards showed only the first employee.

Action/outcome: Support performed re-index, had the customer restart/refresh Nova, investigated the scorecard issue, asked the customer to retry, and the customer confirmed it worked.

Training value: This is a good resolution because it records the action, the affected report, and customer confirmation.

## .NET Framework During Install

Source: Salesforce ticket 346640.

Problem: Customer installing Nova on a new laptop encountered a .NET Framework error.

Action/outcome: Support connected remotely, addressed the .NET Framework issue, installed Nova, obtained account-owner approval, configured the account, and confirmed the customer could log in.

Training value: Good because it includes prerequisite repair, authorization, setup, and verification.

## Receipt Printer Setup

Source: Rescue confirmed printer examples.

Problem: Customer needed receipt printer connected to Nova.

Action/outcome: Support asked for the printer make/model, sent or installed the matching driver package, had the customer sign into Nova, ran test prints, and confirmed receipt printing worked.

Training value: Good because the steps are reproducible and end with a Nova print test, not just driver installation.

## Printer Spooler / PDF Workaround

Source: Salesforce printer examples.

Problem: Customer could not print a receipt as PDF or printer output was stuck.

Action/outcome: Support used a workaround through BackOffice/browser invoice print when Microsoft Print to PDF was unavailable, and in other cases cleared spooler/driver state before retrying print.

Training value: Good when it states the actual workaround and final output.

## Invoice Barcode Missing

Source: Salesforce tickets 346573/346574 and Chatter follow-up.

Problem: One invoice printed without a barcode while other invoices printed correctly.

Action/outcome: Support reproduced the issue on a test machine, generated a PDF with the barcode as a workaround, sent it to the customer, and created follow-up for root-cause investigation.

Training value: Good because it separates customer workaround from unresolved root cause.

## Login / Authorization Credentials

Source: Salesforce and Rescue login examples.

Problem: Customer could not authorize or log into account.

Action/outcome: Support distinguished company credentials from user credentials, checked common character mistakes such as `O` vs `0` and `I` vs `l`, used registered-email credential source when appropriate, and verified login.

Training value: Good when no secret values are repeated and the customer verifies access.

## Salesperson Missing From Sale Screen

Source: Salesforce ticket 346605 and Rescue scanner/user example.

Problem: Salesperson list was not showing at one location.

Action/outcome: Support explained that users must be clocked in to appear, showed clock-in/clock-out, explained one-location-at-a-time behavior, and pointed to the "Not on that list?" path.

Training value: Good because it converts a vague UI complaint into a specific rule.

## Layaway Setting

Source: Rescue layaway examples.

Problem: Customer could not create or update layaway because settings required a minimum payment.

Action/outcome: Support explained layaway cannot be edited directly, showed payment update from the sale screen using layaway code, adjusted minimum percentage when authorized, and had the customer retry.

Training value: Good because it documents both product limitation and permitted workaround.
