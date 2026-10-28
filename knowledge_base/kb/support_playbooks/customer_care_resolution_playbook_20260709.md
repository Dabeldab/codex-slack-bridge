<!-- AgentChat/coding_agent 2026-07-09T02:05:00Z -->

# Customer Care Resolution Playbook

Sources:
- Salesforce `NovaPOS_Ticket__c` Classic/Wave customer-care tickets from 2024-07-09 through 2026-07-09.
- LogMeIn Rescue API session/chat reports from 2025-07-08 through 2026-07-08.
- Selected Salesforce Chatter feed-elements for tickets where comments existed.

Do not count vague closures like "done", "solved", "fixed", or "see chat log" as playbook evidence unless the ticket or chat also shows the actual action taken and the customer-visible outcome.

## General Support Flow

1. Identify the customer, company/account, location, product lane, and exact symptom.
2. Capture the exact error text, screenshot, report name, invoice number, device model, user name, or location name before troubleshooting.
3. Reproduce or observe the issue when possible.
4. Apply the narrowest known fix.
5. Ask the customer to retry in Nova and confirm the outcome.
6. If unresolved, document attempted steps, current state, exact error, and the next owner. Do not write "resolved" without customer confirmation or working evidence.

## .NET, Telerik, JIT, and Exception Errors

Use the stack trace as the routing clue. Capture the full exception text and the first NovaPOS stack frame.

Observed flows:
- `.NET Framework` error during install or first launch: repair/install the required .NET Framework, reinstall Nova if needed, authorize the account with owner approval, then verify the customer can log in.
- `System.NullReferenceException` in `NovaPOS.NovaReports.Employee_ScoreCard.UpdateFigures`: treat as a report/scorecard data issue. Try re-index, restart/refresh Nova, retry the report, and verify the scorecard output. If still broken, escalate with the exact report, employee scope, and stack trace.
- `Telerik.WinControls.UI.RadSpinEditor` / `RadSpinElement.set_Value` with "'0.00' is not valid. Provide value between Minimum and Maximum" in `EmployeesManagement_Edit.set_Step2To`: do not claim a known fix. Prior evidence left this unresolved. Collect affected users, note whether User ID 1 Manager is unaffected, capture the full stack, and escalate for development/data review.
- Receipt email errors or Microsoft/.NET popup during email send: verify the location email settings. Support examples consistently recommend Gmail for receipt sending. Update to a Gmail sending account when appropriate, send a test receipt, wait for delivery, and confirm receipt.

Bad resolution pattern:
- "Darius fixed it" or "fixed after restart" without what changed is not enough for the support agent. Record the stack and actual fix.

## Re-index, Reports, and Scorecards

Observed flows:
- Customer requests re-index: perform re-index, have the customer restart or refresh Nova, and retry the failed screen/report.
- Employee scorecards showing only one employee: re-index plus retry resolved at least one example after the customer confirmed "It worked."
- Product sold reports: show the customer how to generate the report for the requested date range, verify the correct columns/product names, then export to Excel if requested.
- Commission/report visibility: adjust user/report permissions, then have the customer verify the employee can see the report.

Escalate when:
- The same report fails after re-index/restart.
- The ticket lacks the report name, date range, affected location, or exact error.

## Receipt Printers, Labels, and Cash Drawer

Required intake:
- Printer make/model.
- Connection type: USB, network, Wi-Fi, or shared printer.
- Whether Windows test print works.
- Whether Nova print works.
- Whether the cash drawer should open from the receipt printer.

Observed flows:
- Rongta receipt printer: install/send the Rongta driver package, sign into Nova, print a receipt, and ask "Did it print?"
- Star TSP100: install/send the TSP100 driver package, test Windows print, then test Nova print.
- Epson/POS80-style printer: install the matching receipt-printer driver package, test print, then test from Nova.
- Printer stopped working: power cycle or restart PC when appropriate, clear the print spooler if jobs are stuck, reinstall/repair driver, then test print.
- Microsoft Print to PDF missing: use BackOffice/browser invoice print as a workaround when the customer needs a PDF.

Bad resolution pattern:
- A remote session ending after "Printer fix.bat" or a reboot is not a resolution unless the customer confirms print output.

## Barcode Scanners and Invoice Barcodes

Scanner flow:
- Ask for scanner make/model.
- Confirm whether the customer is scanning into the Nova sales screen barcode field or expecting hands-free scanner input.
- If hands-free input is needed, configure the scanner prefix from the scanner manual. One observed Inateck case required setting a prefix symbol from the booklet; without that, the customer had to click the barcode area before scanning.
- Test by scanning a known product in the sales screen and inventory/product screen.

Invoice barcode flow:
- If a specific invoice prints without a barcode, test another invoice and reproduce on a test machine if possible.
- For a one-off invoice issue, generate/send a PDF with the barcode as a customer workaround.
- Create a follow-up for account manager/development root-cause review when the same invoice fails on a test machine.

Deleted invoice rule:
- Deleted invoices are generally not recoverable. If the customer asks for restoration, set expectation that recovery is not guaranteed and escalate only with invoice number, account, deletion date/time if known, and business impact.

## Credit Card Terminals and External Machines

Required intake:
- Terminal make/model.
- Exact error text on the terminal.
- Whether this is an integrated Nova device or an external credit card machine.
- Whether the issue blocks taking payment now.

Observed flows:
- External terminal receipt reprint: support can try manufacturer instructions, but if the terminal model menus do not match, set a clear boundary and refer/escalate to the payment provider or the internal owner of that terminal workflow.
- Location disabled from payment declines: update the payment method, then reactivate the location when authorized.
- Refund payment method entered wrong in New Nova: if the refund invoice payment method cannot be edited from support, escalate to development/account management, tell the customer it may take a few business days, and notify by email/phone when complete.

Bad resolution pattern:
- "Customer will contact WhatsApp" or "call later" is not a resolution. It is a follow-up state.

## Login, Account Authorization, Users, and Permissions

Observed flows:
- First-time PC login needs company account credentials once, then user credentials.
- Owner/manager consent is required before adding account credentials or authorizing a new machine.
- Common credential mistakes: uppercase `I` vs lowercase `l`, `O` vs `0`, extra spaces when copying from the registered email.
- If the customer has a screenshot/email with the password, copy/paste instead of retyping when possible.
- Duplicate user names can block login. Owner access may be required to rename one of the duplicate users.
- Salesperson missing from sale screen list: user must be clocked in. A user can only be clocked into one location at a time. Use the "Not on that list?" path to see users not clocked in.
- User/report visibility issues: verify permissions and location scope, then have the customer sign in as that user to confirm.

Never print, repeat, or store actual passwords in notes or training examples.

## Image Uploads

Observed flow:
- If image upload fails or the error flashes too quickly, check image dimensions.
- Examples resolved by resizing images to about 250x300 or 200x200 before upload.
- Confirm by uploading the resized image.

## Layaway

Observed flows:
- Layaway records can be deleted but not directly edited.
- To update payment, enter the layaway code from the sale screen and add the amount to pay.
- If the system requires a minimum payment percentage, adjust the layaway/down-payment setting in management when authorized, then retry.

## CRM and Location Data Mismatches

Observed flow:
- Missing or wrong location names in customer management/CRM often require internal review.
- Capture examples, affected customer profiles, expected location names, and whether the data used to be present.
- Create an internal follow-up for account manager/data review. Do not tell the customer it is fixed until the data is corrected and verified.

## Training Quality Rules

Good training examples must include:
- Problem statement.
- Specific action taken.
- Customer-visible verification or a clear follow-up owner.
- Source reference: Salesforce ticket number or hashed LogMeIn session record.

Bad training examples include:
- Only "done", "fixed", "solved", or "all set".
- Remote-control session with no support dialogue.
- Customer disconnects before confirmation.
- Escalation mentioned without what was collected or who owns the next step.
- Sensitive values such as passwords, raw phone numbers, emails, or company credentials.
