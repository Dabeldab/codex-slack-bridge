# Hardware Barcode Scanner AI Knowledge Source V 1

Source: Zoom Knowledge Library browser export
KB ID: ij7dmuquz1v7s5k2wef44sq1
Article ID: cmp1bi06p003zrc07x64okr85
Product lane: General
Source URL: https://novapointofsale.zoom.us/ai-studio/kb/kbs/ij7dmuquz1v7s5k2wef44sq1/articles/cmp1bi06p003zrc07x64okr85
Updated: 05/18/2026, 06:20 PM

Hardware — Barcode Scanner — Knowledge Source

For detailed Nova tilde-prefix programming, scanner customer phrasings, and Symcode-specific notes, also retrieve the Barcode Scanner Tilde Prefix knowledge source. Do not use this article by itself for vague requests such as "install scanner," "set up scanner," or "add barcode scanner" unless the customer has identified the scanner brand/model and whether it is USB or Bluetooth.

USB Barcode Scanner Setup

Setting up a USB barcode scanner for Nova is usually a plug-and-play process after the scanner brand/model and connection type are known. The scanner acts as a keyboard input device to Windows, and Nova reads scans from any input that starts with a tilde (~) character.

Setup Steps
Plug the scanner into an open USB port on the Nova workstation.
Wait for Windows to detect the device — this usually takes 10–30 seconds.
Program the scanner with a tilde (~) prefix by scanning the manufacturer's programming barcodes. These come in the scanner's quick-start guide and add the tilde prefix to all subsequent scans.
Test the scanner in Notepad — open Notepad, scan a product barcode, and confirm the output shows ~ followed by the barcode number.
Open Nova and scan a product barcode at the register to confirm Nova pulls up the product.
Troubleshooting
Nothing scans at all: Try a different USB port. Confirm the scanner is in USB HID mode (check the scanner's manual — some scanners ship in different modes).
Scans show in Notepad but Nova doesn't recognize them: The tilde (~) prefix is missing. Re-scan the manufacturer's programming barcodes to add the prefix, then test again in Notepad before testing in Nova.
Scanner powers on but Windows doesn't detect it: Try a different USB cable if removable, or a different workstation USB port. Confirm the scanner is fully powered (status light is on, not blinking).
Compatibility

Most standard USB HID-mode barcode scanners work with Nova. Compatibility requires:

USB HID mode (not Serial, not OPOS)
Ability to program a configurable prefix character (tilde / ~)
Standard 1D or 2D barcode reading depending on what symbology you scan

Common compatible brands include Inateck and similar standard USB scanners. Variable-weight and price-embedded barcodes (common in grocery and meat retail) are supported as long as the scanner reads the underlying symbology and is programmed with the tilde prefix.

If a customer is sourcing fresh hardware and is unsure about a specific model, Nova support can verify compatibility before purchase.

Why Nova Requires the Tilde Prefix

Nova uses the tilde (~) prefix to distinguish scanner input from keyboard input at the register. This prevents accidental keyboard entries from being interpreted as barcodes. Every supported scanner must therefore be programmed to emit ~ before each scanned barcode value.

Add to Nova

The scanner does not require adding inside the Nova application — Nova reads scanner input automatically at the register screen as long as the tilde prefix is configured at the scanner level. No driver install or settings change inside Nova is required.

Escalation

Escalate to Nova support if:

The scanner cannot be programmed with a tilde prefix (some older or non-HID scanners cannot)
The customer's barcodes use a symbology the scanner does not recognize
Windows cannot detect the scanner after trying multiple USB ports and cables
The scanner is for variable-weight or price-embedded barcodes and the customer needs help configuring the symbology
