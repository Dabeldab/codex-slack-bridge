# Hardware Barcode Scanner Tilde Prefix AI FAQ V 1

Source: Zoom Knowledge Library browser export
KB ID: ij7dmuquz1v7s5k2wef44sq1
Article ID: cmp2sne392dvrsy07uubsfy12
Product lane: General
Source URL: https://novapointofsale.zoom.us/ai-studio/kb/kbs/ij7dmuquz1v7s5k2wef44sq1/articles/cmp2sne392dvrsy07uubsfy12
Updated: 05/18/2026, 06:20 PM

Hardware - Barcode Scanner Tilde Prefix - FAQ
Q: Can I use any barcode scanner with Nova?

A: Usually yes, if the scanner supports USB HID keyboard mode and can be programmed with a custom prefix. Nova requires every scan to begin with a tilde (~). Test in Notepad first: when you scan a barcode, it should type ~ followed by the barcode number. If it only types the barcode number without ~, Nova may ignore it.

Q: Why does Nova need a tilde before barcode scans?

A: Nova uses the tilde (~) prefix to tell scanner input apart from normal keyboard typing. The scanner must send ~ before every barcode value. Example: Nova expects ~012345678905, not just 012345678905.

Q: How do I program the tilde prefix on a barcode scanner?

A: Use the programming manual for the exact scanner model. Put the scanner in USB HID keyboard mode, find Prefix, Preamble, Data Editing, or Prefix/Suffix, enable prefix output, and set the prefix to tilde (~). Some manuals call this ASCII decimal 126 or hex 7E. Save the setting, then test in Notepad before testing in Nova.

Q: My scanner works in Notepad but not Nova. What is wrong?

A: The tilde prefix is probably missing. Open Notepad, scan a product barcode, and check the first character. If it does not start with ~, program the scanner with a tilde prefix using the scanner manual. After Notepad shows ~ plus the barcode number, test in Nova again.

Q: My scanner types 7E before the barcode instead of ~.

A: The scanner was programmed with the literal characters 7 and E instead of entering 7E as a hex value. Repeat the prefix setup using the model manual's hex-entry sequence, or use the manual's direct barcode for the ~ character if it has one.

Q: How do I program a Symcode scanner for Nova?

A: Use the exact Symcode model manual. For MJ-9120/MJ-3300-style manuals, go to Prefix/Suffix Settings, scan Add Prefix, scan the all-code-type value 99, scan tilde as hex 7E, then scan Save. Test in Notepad; the scan must start with ~. For R40-style manuals, scan Allow for Prefix Adding, choose the tilde prefix from the appendix, then save or exit if required.

Q: The Symcode scanner adds a prefix only to some barcodes.

A: It was probably programmed by barcode type instead of all barcode types. Reprogram the prefix for all code types. In some Symcode manuals, all barcode types are represented by hex value 99. Then test UPC, Code 128, QR, or whichever barcode types the customer uses.

Q: My wireless barcode scanner stopped working after programming it.

A: The scanner may have left HID keyboard mode or lost its receiver/Bluetooth pairing. Re-pair the scanner, confirm it is in USB HID or Bluetooth HID keyboard mode, then test in Notepad. If it scans in Notepad without ~, reprogram the tilde prefix.

Q: Do I need a scanner driver for Nova?

A: Not if the scanner is in HID keyboard mode. It should behave like a keyboard and type into Notepad. If the scanner creates a COM port or requires OPOS/serial software, it may be in the wrong mode for Nova and should be switched to HID keyboard mode or escalated to Nova support.

Q: Should the scanner add Enter or Tab after the barcode?

A: Nova requires the tilde prefix. An Enter or Tab suffix is not the main requirement. If the scanner already has Enter enabled and Nova works, leave it alone. If Enter or Tab moves focus or causes unexpected behavior, remove the suffix and keep only the tilde prefix.

Q: The scanner adds two tildes before every barcode.

A: The prefix was programmed twice. Remove all prefixes or factory-reset the scanner, then program the tilde prefix once. Confirm in Notepad that the scan starts with one ~.

Q: My scanner reads the wrong characters or symbols.

A: Set the scanner keyboard language/country layout to US English, then test again in Notepad. Wrong keyboard layout can make ~ or other characters appear incorrectly.

Q: My MUNBYN scanner needs to work with Nova. What do I set?

A: Program it the same way: USB HID keyboard mode plus tilde (~) prefix. Use the exact MUNBYN scanner manual and look for prefix/suffix, data editing, or preamble. Test in Notepad until every scan begins with ~.

Q: Can Nova support QR codes and 2D barcodes?

A: Yes, if the scanner supports that symbology and still sends the Nova tilde prefix before the decoded value. Confirm the scanner is enabled for the barcode type being used, then test in Notepad for ~ plus the scanned value.

Q: I cannot find the scanner model or programming sheet.

A: Ask for the scanner brand/model from the label, box, cradle, or order listing. If the exact model cannot be identified, call Nova support before scanning random programming barcodes from another scanner brand.
