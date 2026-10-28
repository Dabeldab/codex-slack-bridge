# Hardware Cash Drawer AI Knowledge Source V 1

Source: Zoom Knowledge Library browser export
KB ID: ij7dmuquz1v7s5k2wef44sq1
Article ID: cmp1bi5vo0040rc07g8xpxays
Product lane: General
Source URL: https://novapointofsale.zoom.us/ai-studio/kb/kbs/ij7dmuquz1v7s5k2wef44sq1/articles/cmp1bi5vo0040rc07g8xpxays
Updated: 05/18/2026, 06:20 PM

Hardware — Cash Drawer — Knowledge Source
How Cash Drawers Connect in Nova

In Nova, the cash drawer connects to the receipt printer, not directly to the computer. The drawer uses a cable that looks like a phone cord and plugs into the RJ11 port on the back of the receipt printer. When Nova prints a receipt, the printer sends an electrical signal through that RJ11 cable to pop the drawer.

This is important to understand because almost every "drawer won't open" issue traces back to either (a) the cable being plugged into the wrong port, (b) the receipt printer not being installed or set as the Windows default printer/default device, or (c) the printer driver's drawer trigger settings being misconfigured.

Cash Drawer Will Not Open After a Sale

Work through these checks in order — the simplest fixes are listed first:

Confirm the cash drawer cable is plugged into the receipt printer's RJ11 port (not directly into the computer or another port).
Confirm the receipt printer is installed in Windows and set as the Windows default printer/default device.
Print a receipt from Nova Wave. If the receipt prints but the drawer doesn't pop, reseat the RJ11 cable on both ends. If the cable looks damaged or has bent pins, replace it.
Check the printer driver's cash-drawer/peripheral setting. The drawer kick command normally comes from the receipt printer driver.
Try the manual key on the front of the drawer. The key bypasses the electrical trigger entirely — if the key won't open the drawer, the drawer mechanism itself may be stuck or locked.
If steps 1–5 check out and the drawer still won't open, the drawer hardware may need replacement.
Escalation

Escalate to Nova support if the cable, Windows default printer, driver drawer setting, and manual key all check out but the drawer still won't open after a test receipt. This usually requires hands-on review or replacement.

Cash Drawer Opens When It Shouldn't

This issue is almost always a trigger configuration problem — the drawer-open command is firing on print events other than the intended sale receipt. Common patterns are the drawer opening on end-of-day reports, opening twice on a single sale, or opening on test prints.

Steps to Fix
Open the printer preferences or printer driver utility in Windows.
Set the peripheral / drawer trigger to fire only on the intended sale receipt event — not on every print job, not on reports, and not on test prints.
Save the settings.
Run a test sale and confirm the drawer opens. Then run an end-of-day report or test print and confirm the drawer does NOT open.
Escalation

Escalate to Nova support if the drawer still opens on the wrong events after the trigger settings are corrected.

Common Wiring Mistakes
Drawer plugged into the computer instead of the printer: Move the RJ11 cable to the printer's RJ11 port.
RJ11 cable plugged into the printer's network port: The network port (RJ45) is wider and has 8 pins. The RJ11 cash drawer port is narrower and has 6 pins. They look similar but are not interchangeable.
Multiple printers, drawer cabled to the wrong one: If the workstation has two receipt printers, the drawer needs to be plugged into the printer Windows uses as the default printer/default device for Nova Wave receipts.
Safety

Do not instruct customers to open the cash drawer hardware, attempt internal wiring repair, or bypass the locking mechanism. Manual key issues and physical damage are an escalation to support.
