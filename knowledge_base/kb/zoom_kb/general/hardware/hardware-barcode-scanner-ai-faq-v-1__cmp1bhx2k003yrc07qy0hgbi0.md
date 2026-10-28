# Hardware Barcode Scanner AI FAQ V 1

Source: Zoom Knowledge Library browser export
KB ID: ij7dmuquz1v7s5k2wef44sq1
Article ID: cmp1bhx2k003yrc07qy0hgbi0
Product lane: General
Source URL: https://novapointofsale.zoom.us/ai-studio/kb/kbs/ij7dmuquz1v7s5k2wef44sq1/articles/cmp1bhx2k003yrc07qy0hgbi0
Updated: 05/18/2026, 06:20 PM

Hardware — Barcode Scanner — FAQ
Q: How do I set up a barcode scanner?

A: First confirm the scanner brand/model and whether it is USB or Bluetooth. The scanner must be in HID keyboard mode and must be programmed with a tilde (~) prefix for Nova. Use the manufacturer's programming barcodes for that exact model, then test in Notepad — you should see "~" followed by the barcode number before testing in Nova. Do not use a programming sheet from another scanner model.

Q: My scanner isn't scanning anything. What do I check?

A: Try a different USB port first. Confirm the scanner is in USB HID mode (check its manual). If it scans into Notepad but Nova doesn't pull up the product, the tilde (~) prefix likely isn't programmed — scan the manufacturer's programming barcodes to add it.

Q: Which barcode scanner works with Nova?

A: Most USB HID-mode barcode scanners work with Nova as long as they can be programmed with a tilde (~) prefix. Common compatible brands include Inateck and other standard USB scanners. If you're unsure about a specific model, contact Nova support to verify compatibility before purchasing.

Q: How do I program my barcode scanner for Nova?

A: Use the manufacturer's quick-start guide that came with the scanner. Look for the programming barcodes that add a tilde (~) prefix. Scan those programming barcodes in the order specified, then test in Notepad to confirm the prefix appears before the barcode number.

Q: Can Nova process variable-weight barcodes?

A: Yes, Nova reads price-embedded barcodes from compatible scales and scanners. The scanner still needs the tilde (~) prefix programmed for Nova to recognize the scan input.

Q: I have an Inateck scanner — how do I connect it to Nova?

A: Inateck USB scanners follow the same setup as any USB HID barcode scanner. Plug it in, wait for Windows to detect it, scan the Inateck programming barcodes to add the tilde (~) prefix, test in Notepad, then test at the Nova register.

Q: How do I add a barcode scanner to Nova?

A: The scanner doesn't need to be added inside Nova — it works through Windows as a keyboard input device. Once it's plugged in, programmed with the tilde prefix, and showing the prefix in Notepad, Nova will read scans automatically at the register screen.
