# Hardware Cash Drawer AI FAQ V 1

Source: Zoom Knowledge Library browser export
KB ID: ij7dmuquz1v7s5k2wef44sq1
Article ID: cmp1bi4sw0lawr20763xsz2hj
Product lane: General
Source URL: https://novapointofsale.zoom.us/ai-studio/kb/kbs/ij7dmuquz1v7s5k2wef44sq1/articles/cmp1bi4sw0lawr20763xsz2hj
Updated: 05/18/2026, 06:20 PM

Hardware — Cash Drawer — FAQ
Q: Why won't my cash drawer pop open after a sale?

A: Cash drawers connect through the receipt printer, not the computer. First, confirm the drawer is plugged into the receipt printer's RJ11 port (the phone-cord-looking jack), not directly into the workstation. Confirm the receipt printer is installed in Windows and set as the Windows default printer/default device, then print a receipt from Nova Wave. If the receipt prints but the drawer doesn't pop, check the RJ11 cable and the printer driver's cash-drawer/peripheral setting. Also try the manual key on the front of the drawer to confirm it's not stuck or locked.

Q: My cash drawer is plugged in but still won't open. What now?

A: If the cable is connected to the printer's RJ11 port, the printer is set as the Windows default printer/default device, the manual key works, and a receipt prints but the drawer still doesn't pop, the drawer itself or the printer driver drawer-kick setting may need hands-on review. Give Nova support a call for next steps.

Q: Why does my cash drawer open when it shouldn't?

A: This usually means the drawer trigger settings are firing on the wrong print events — for example, opening on every print job or on end-of-day reports instead of only on sales. Review the drawer trigger settings in the receipt-printer driver so the drawer command runs only on the intended receipt event, then run a test sale and an end-of-day report to confirm.

Q: My drawer pops twice after a single sale. Why?

A: Most often a duplicate trigger configuration or duplicate printer queues. Open the printer preferences or driver utility in Windows, confirm only one drawer-open trigger is set for the receipt event, remove duplicate printer queues if needed, save, and run a test sale.

Q: My cash drawer opens during an end-of-day report. How do I stop that?

A: The drawer trigger is set to fire on every print event instead of just sales. Open the printer preferences or driver utility in Windows, restrict the drawer trigger to the sale receipt event only, save, then re-run an end-of-day report to confirm the drawer stays closed.

Q: The drawer is plugged directly into the computer — why doesn't that work?

A: Cash drawers don't connect directly to the computer in Nova setups. They connect to the receipt printer's RJ11 port, and the printer sends the open command when it prints a receipt. If the drawer is currently plugged into the workstation, move the RJ11 cable to the back of the receipt printer instead.
