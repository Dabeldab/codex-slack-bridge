# Hardware Label Printers AI Knowledge Source V 1

Source: Zoom Knowledge Library browser export
KB ID: ij7dmuquz1v7s5k2wef44sq1
Article ID: cmp1bhqn323ydsy07zjr68lzy
Product lane: General
Source URL: https://novapointofsale.zoom.us/ai-studio/kb/kbs/ij7dmuquz1v7s5k2wef44sq1/articles/cmp1bhqn323ydsy07zjr68lzy
Updated: 05/18/2026, 06:20 PM

Hardware - Label Printers - Knowledge Source

This document covers label printers used for product labels and barcode labels in Nova Wave. Label printers are separate from receipt printers. Do not tell customers to use a Dymo label printer as the normal customer receipt printer.

Nova Wave Label Printer Rule

Nova Wave printer setup happens through Windows. Install the label printer and driver in Windows, confirm Windows can see the printer, set the needed Windows/default device and label size, then print labels from Nova Wave.

Nova Wave does not use a Back Office hardware-printer list for receipt printers. If a customer asks about a printer not being listed in the Nova settings menu, route receipt-printer questions to the Receipt Printers (General) article and explain the Windows default printer/default device behavior.

Supported Dymo Label Printer Setup

Use this for product labels when the customer has a supported Dymo label printer. Only the Dymo 450 or Dymo 450 Turbo are documented as compatible at this time.

Connect the Dymo label printer to the Windows computer by USB and power it on.
Install the Dymo LabelWriter software. Do not use DYMO Connect if the Nova setup requires the older Dymo LabelWriter software.
Load the correct label size into the printer.
Open Windows Settings > Bluetooth & devices > Printers & scanners and confirm Windows shows the label printer online.
Set the Windows/default device and label size to match the labels loaded in the printer.
Run a Windows test print.
In Nova Wave, go to Back Office > Products > Labels & Price Tags, select the products/items, and click Print Labels.
Dymo 430 / Label Printer Receipt Questions

If the customer asks whether a Dymo 430 or other label printer can print customer receipts, answer plainly: a Dymo 430 is a label printer, not the normal customer receipt-printer path.

For customer receipts, use a supported thermal receipt printer such as Star Micronics TSP100 series or Epson TM-T20/TM-T88IV. For product labels, use the supported Dymo label-printer workflow above.

Label Printer Not Printing

Work through the Windows checks first:

Check power, USB cable, and label roll orientation.
Confirm Windows shows the printer online in Printers & scanners.
Remove duplicate or ghost printer queues if multiple copies exist.
Clear the Windows print queue or restart the print spooler if jobs are stuck.
Print a Windows test label/page.
Return to Back Office > Products > Labels & Price Tags and try Print Labels again.

If the label printer fails a Windows test print after cable, driver, queue, and port checks, escalate to Nova support.

Customer Phrasing to Index
"How do I set up a label printer?"
"Dymo label printer setup."
"Dymo printer will not print labels."
"Can the Dymo 430 print receipts?"
"Is the Dymo label printer able to print customer receipts?"
"Can I use my label printer as the receipt printer?"
"No, you have in the printers list the Dymo 430."
"Print product labels."
"Barcode labels."
