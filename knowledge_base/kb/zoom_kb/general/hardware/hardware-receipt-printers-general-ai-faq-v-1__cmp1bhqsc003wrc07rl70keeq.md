# Hardware Receipt Printers General AI FAQ V 1

Source: Zoom Knowledge Library browser export
KB ID: ij7dmuquz1v7s5k2wef44sq1
Article ID: cmp1bhqsc003wrc07rl70keeq
Product lane: General
Source URL: https://novapointofsale.zoom.us/ai-studio/kb/kbs/ij7dmuquz1v7s5k2wef44sq1/articles/cmp1bhqsc003wrc07rl70keeq
Updated: 05/18/2026, 06:20 PM

Hardware — Receipt Printers (General) — FAQ
Q: My receipt printer isn't printing after a sale. What do I check?

A: Confirm the printer is powered on and has paper loaded, and the status light is solid (not blinking). If blinking, open the cover, reseat the paper, and close it firmly. Unplug the USB cable for 5 seconds and plug it back in. In Windows Settings > Bluetooth & devices > Printers & scanners, confirm the receipt printer is installed and set as the Windows default printer/default device. Print a Windows test page, then close and reopen Nova Wave and test another receipt. Nova Wave does not have a separate Back Office printer-selection page; if Windows cannot print, fix the Windows driver/cable/connection first.

Q: I want to install a printer.

A: First confirm the exact printer before giving steps: is it a receipt printer or label printer, what brand/model is it, and is it connected by USB, Ethernet, Wi-Fi, or Bluetooth? Do not use a generic printer-install script because the correct driver and setup path depend on the device. Once the model and connection are known, use the matching Star, Epson, Citizen, Rongta, MUNBYN, Volcora, BIXOLON, or label-printer article.

Q: How do I select an already installed receipt printer in Nova Wave?

A: Nova Wave does not use a Back Office receipt-printer dropdown. Install the receipt printer in Windows, open Windows Settings > Bluetooth & devices > Printers & scanners, set the printer as the Windows default printer/default device, print a Windows test page, then close and reopen Nova Wave and test a receipt.

Q: My printer is not listed in the Nova settings menu. How can I use it?

A: In Nova Wave, that is expected: receipt printers are not chosen from a Nova printer list. Install the printer in Windows, confirm it appears online in Printers & scanners, set it as the Windows default printer/default device, print a Windows test page, then test a receipt from Nova Wave. If Windows does not show or print to the device, use the exact brand/model article to install the correct driver first.

Q: Nova shows the same printer twice. How do I remove the duplicate?

A: Duplicates usually appear after a reconnect. In Windows, open Settings > Bluetooth & devices > Printers & scanners, find the duplicate, right-click the one you don't want, and select Remove device. Set the correct remaining printer as the Windows default printer/default device, print a Windows test page, then test a receipt in Nova Wave.

Q: My receipts are blank. What's wrong?

A: Blank receipts are almost always a paper-orientation issue. Thermal paper only prints on one side. Pull a strip and scratch it with your fingernail — if one side turns dark, that's the side that goes up against the print head. Reload the roll with the correct side facing the print head. If neither side darkens when scratched, the paper isn't thermal receipt paper — buy the correct thermal paper for your printer.

Q: My receipts are smudged. How do I fix that?

A: Smudging means the print head needs cleaning. Power the printer off, and use a cotton swab with isopropyl alcohol to gently wipe the print head. Let it dry fully before printing again.

Q: My receipts are printing garbled or as gibberish. What's the cause?

A: Garbled text usually means the wrong printer driver is installed. Check the recommended driver for your specific printer model on the manufacturer's site and reinstall the correct one. Then in Windows Settings > Bluetooth & devices > Printers & scanners, confirm the correct printer queue is installed and set as the Windows default printer/default device. Restart the printer after any change.

Q: Which receipt printer should I buy for Nova?

A: For new installs, Nova recommends the Star Micronics TSP100 series. Supported Epson models include the TM-T20 and TM-T88IV. If you want the simplest setup, choose Star Micronics. If you already own a printer and aren't sure about compatibility, contact Nova support before installing.

Q: Can I print two receipts for every sale (a customer copy and a store copy)?

A: This is receipt behavior, not a printer-device setup page. First check whether Nova Wave prompts for an extra/merchant copy during checkout or receipt reprint. If the option is not visible, contact Nova support so the receipt behavior can be reviewed for that account. Printer setup is still handled in Windows: Nova Wave prints to the Windows default printer/default device.

Q: Why are my receipts getting cut off?

A: This is usually a paper-size or receipt-length mismatch in the printer driver. Open the printer preferences in Windows, set the correct paper width (typically 58 mm or 80 mm depending on your printer and paper roll), and set the receipt or paper length to the correct value or max length. Run a Windows test page, then a Nova Wave receipt test. If receipts are still cut off after that, call Nova support.

Q: The signature printout isn't working / Nova prints without showing a printer prompt. How do I fix it?

A: Multiple saved printers can cause output to go to the wrong device automatically. In Windows, remove any unused or duplicate printers, confirm the intended printer is installed and set as the Windows default printer/default device, print a Windows test page, then retry the print flow in Nova Wave.

Q: My printer shows as offline in Windows. What now?

A: Try setting the printer as the default printer in Windows (Settings > Bluetooth & devices > Printers & scanners), then try the print again. If the printer is still offline, unplug the USB cable for 5 seconds, plug it back in, and reboot the workstation if needed.

Q: Where do I select my receipt printer in Nova Wave?

A: You do not select receipt printers inside Nova Wave Back Office. Install the printer in Windows and set it as the Windows default printer/default device. Nova Wave prints to that default device.
