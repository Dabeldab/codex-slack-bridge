# Hardware General AI Knowledge Source V 1

Source: Zoom Knowledge Library browser export
KB ID: ij7dmuquz1v7s5k2wef44sq1
Article ID: cmp1bhn8z003urc07c7w34taw
Product lane: General
Source URL: https://novapointofsale.zoom.us/ai-studio/kb/kbs/ij7dmuquz1v7s5k2wef44sq1/articles/cmp1bhn8z003urc07c7w34taw
Updated: 05/18/2026, 06:20 PM

Hardware — General (Connectivity, Performance, Mac) — Knowledge Source

Covers general workstation issues that affect Nova across all hardware peripherals: internet connectivity, computer performance, and Nova running on Parallels on a Mac.

Unknown or Unlisted Hardware Devices

If the customer has an unknown, unlisted, or off-brand hardware device, do not assume Nova or Windows can use it.

Ask the customer to confirm the brand and model from the device label, box, receipt, or Windows device listing.
Confirm the device is compatible with Windows before walking through driver installation.
If Windows compatibility is confirmed, download the driver from the device manufacturer's official website for that exact model.
If the customer cannot confirm the model, Windows compatibility, or the correct manufacturer driver, escalate to Nova support.

Do not instruct customers to install drivers from random third-party driver sites.

Hardware Needed for Nova Wave

For a typical Nova Wave register setup, plan around a Windows computer first, then add only the peripherals the store needs.

Use a Windows 10 or Windows 11 computer with at least 4 GB RAM; an SSD is strongly recommended.
For receipts, use a supported thermal receipt printer such as Star Micronics TSP100 series or Epson TM-T20/TM-T88IV.
If the store uses a cash drawer, it usually plugs into the receipt printer's RJ11 drawer port.
Barcode scanners are usually USB plug-and-play, but the exact scanner model may still need setup help.
Card terminals depend on the merchant processor and must be configured under Back Office > Locations > Settings > Edit > Merchant Services.
Label printers are optional and are for product labels, not standard customer receipts.

If the customer is buying from Amazon or another third party, recommend they send the exact model links to Nova support before ordering so compatibility can be checked. Printer setup in Nova Wave happens through Windows: install the printer, set it as the Windows default printer/default device, then test in Nova Wave.

Nova Shows as Offline / No Internet Connection

When Nova reports it's offline, work through these steps:

Click Reload or Go Online if that button appears in Nova.
If that doesn't work, restart Nova and log back in.
If Nova still cannot connect, open a web browser and try loading any website (Google, your store's website, etc.) to confirm the internet itself is up.
Once the internet is working and websites load successfully, Nova will reconnect and come back online.
Offline Workflow

If the store needs to keep ringing sales while offline, route to Nova support so we can confirm the correct offline workflow for their setup.

Escalation

If websites load fine but Nova still says offline after a restart, the issue is on Nova's side or in the local network's connection to Nova's servers. Escalate to support.

Slow or Freezing Computer

When the register workstation runs Nova slowly or freezes, work through these in order — simplest first:

Restart the computer. This clears memory and almost always fixes basic slowness.
Close background programs. Browsers, video players, music apps, and other software running in the background consume RAM that Nova needs.
Check for Windows updates. Out-of-date Windows installs get slower over time. Apply pending updates from Settings > Windows Update.
Confirm at least 10 GB of free disk space. Windows and Nova both slow dramatically when the disk is near-full. Clear old files, downloads, and temp data if needed.
Run a quick antivirus scan. Malware is a common cause of unexpected slowness. Use Windows Defender or another reputable antivirus.
Recommended Specs

Nova runs best on:

Windows 10 or 11
At least 4 GB of RAM
An SSD (solid-state drive) rather than a mechanical hard drive

If the workstation is over 5 years old and still slow after the steps above, it may be time for a hardware upgrade.

Escalation

If the customer's computer is older than 5 years, slow even after a clean restart, or they want spec recommendations for a replacement, escalate to Nova support — an agent can recommend specs.

Nova on Parallels (Windows VM on a Mac)

Some customers run Nova on a Mac by installing Windows inside Parallels, then running Nova inside that Windows virtual machine. This setup works, but it has a few extra layers where things can go wrong.

Nova Stopped Working in Parallels

Restart the Nova application first, then restart the Windows session inside Parallels if needed.

Close Nova completely.
Reopen Nova.
If Nova still isn't working, restart Windows inside Parallels (Start menu > Restart).
After Windows comes back up, verify the printer or device appears inside Windows.
Peripherals Not Showing in Parallels

Peripherals connected to macOS still need to be passed through correctly to Windows in Parallels. This is a Parallels-side setting, not a Nova setting.

Open Parallels Control Center on macOS.
Open the device or USB settings for the Windows VM.
Confirm the printer, scanner, or terminal is set to connect to the Windows VM rather than being held by macOS.
Inside Windows, open Settings > Bluetooth & devices > Printers & scanners (or the relevant device area) and confirm the device appears.
If the device shows up in Windows, use the matching peripheral article. For printers, set the Windows default printer/default device before testing in Nova Wave.
Escalation

Escalate to Nova support if:

The device passes through to Windows correctly but Nova still cannot use it.
The Parallels configuration is unclear and the customer needs help with the pass-through setup.
The customer is troubleshooting a Mac-specific issue that requires hands-on review.
Safety and Hardware Rules
Never instruct the customer to disable Windows Defender, antivirus, or system firewall without a clear documented reason.
Never instruct the customer to download Windows updates from unofficial sources.
For unknown, unlisted, or off-brand devices, confirm Windows compatibility first and use the device manufacturer's official driver download page for the exact model.
For hardware specifications or replacement workstations, route customers to Nova support rather than recommending specific retailers or part numbers.
