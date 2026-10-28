# Hardware Card Terminals AI Knowledge Source V 1

Source: Zoom Knowledge Library browser export
KB ID: ij7dmuquz1v7s5k2wef44sq1
Article ID: cmp1bi2vn23yhsy07sjxi5p5r
Product lane: General
Source URL: https://novapointofsale.zoom.us/ai-studio/kb/kbs/ij7dmuquz1v7s5k2wef44sq1/articles/cmp1bi2vn23yhsy07sjxi5p5r
Updated: 05/18/2026, 06:20 PM

Hardware — Card Terminals — Knowledge Source
Supported Terminals and Processors

Nova supports the following payment terminals:

Ingenico Lane 3000, 3600, 5000, 7000 — Ethernet connection. Compatible with WorldPay or Creditcall/NMI (ChipDNA / GSPayTech).
Ingenico Link 2500 — Wi-Fi connection. Compatible with WorldPay.

Setup steps differ by terminal model AND by payment processor. Confirm both before starting setup.

General Card Terminal Troubleshooting (Will Not Connect)

Work through these checks in order before escalating:

Confirm the terminal is powered on and on the same network as the workstation. For Wi-Fi terminals, both devices must be on the same SSID.
Restart the terminal — hold the power button until it turns off, then power it back on. For terminals with no power button, unplug power and plug it back in.
Close and reopen Nova.
If the terminal has not been set up in Nova Wave yet, go to Back Office > Locations > Settings > Edit > Merchant Services and follow the on-screen pairing steps.
Enter the credentials provided by your merchant service provider and save.
Return to the sale screen and run a $0.01 test transaction to confirm the terminal is online and processing.
Escalation

If the terminal still won't connect after these steps, escalate to Nova support for a remote session.

Lane 3000 / 3600 / 5000 / 7000 Setup with WorldPay

This procedure is for WorldPay only.

Connect the terminal to an open Ethernet port until it displays an activation code on the screen.
In Nova Wave, go to Back Office > Locations > Settings > Edit > Merchant Services.
Choose WorldPay and select the correct EMV device model from the list (Lane 3000, 3600, 5000, or 7000).
Enter the merchant information provided by WorldPay.
Pair the device using the activation code shown on the terminal screen.
Save the settings.
Run a small test transaction to confirm the terminal is processing.
Prerequisites
An active WorldPay merchant account with the credentials provided to the customer.
An Ethernet port near the workstation with internet connectivity.
Escalation

If the terminal never displays an activation code, first confirm the Ethernet cable is firmly seated on both ends and the network port is active (check the link light on the back of the terminal). If still no activation code, call Nova support.

Link 2500 Setup with WorldPay

The Link 2500 uses Wi-Fi instead of Ethernet. Complete the Link 2500 Wi-Fi setup (see below) first, then follow the same Nova-side steps as the Lane series: Back Office > Locations > Settings > Edit > Merchant Services > WorldPay > pair with activation code.

Link 2500 Wi-Fi Connection
On the terminal, enter 2634.
Press F.
Open Tetra Admin.
Choose Configure Wi-Fi and scan for networks.
Select the store network and enter the password.
Save the settings and wait for the Wi-Fi icon to turn green (solid, not flashing or white).
When the terminal shows an activation code, pair it in Nova Wave under Back Office > Locations > Settings > Edit > Merchant Services.
Escalation

If the Wi-Fi icon stays white or never turns green, or the terminal never shows an activation code, contact Nova support.

Lane 3000 Setup with Creditcall / NMI (ChipDNA / GSPayTech)

This procedure is for Creditcall/NMI only — not for WorldPay or Proplr customers. The setup requires editing COM port settings in Windows Device Manager, so the customer should be comfortable with that step or escalate.

Install the Nova build and drivers that support Creditcall/NMI.
Open Device Manager (click the Start button and search "Device Manager").
Find the Lane 3000 device under the Ports category.
Right-click the device and choose Properties.
Click Port Settings and change Bits per second to 115200.
Click Advanced and change the COM Port Number to COM5. If a prompt warns that another device is using that port, continue anyway.
Click OK to save. Agree to restart the computer if asked.
In Nova Wave, open Back Office > Locations > Settings > Edit > Merchant Services.
Choose GSPayTech and enter the merchant credentials.
Save to generate the ChipDNA configuration file on the PC.
Restart the PC if it has not already been restarted.
Open Nova and log in to the Storefront.
Run a small test transaction through the card terminal.
Escalation

Escalate to Nova support if Windows does not detect the terminal on the expected COM port after install, if the ChipDNA service will not start, or if the customer is not comfortable making Device Manager changes — an agent can complete the install remotely.

EMV Subscription Expired Error

Error text: "EMV subscription for this location has expired"

Steps to Fix
Close and reopen Nova.
Restart the payment terminal (hold the power button or unplug power).
Reconnect the terminal to the PC or network.
Run a test charge.
Escalation

If the EMV subscription message returns after a restart, the location EMV or merchant-service setup needs review. Route to merchant services.

External Terminal Blocked — Cannot Process Card Sales

When the external credit card terminal is blocked from processing sales, the cause is usually a setting in the location merchant configuration.

Steps to Fix
Open Back Office > Locations > Settings > Edit > Merchant Services.
Review the external payment or external terminal settings.
Clear any setting that blocks the external payment method.
Save the location settings.
Run a new card sale to confirm processing is restored.
Escalation

If the setting is already correct and card sales are still unavailable, call Nova support.

Safety and Security Rules
Never instruct customers to share merchant IDs, terminal IDs, processor passwords, API keys, or PCI-sensitive credentials in chat.
Never instruct customers to disassemble or repair the terminal hardware.
Never bypass EMV security checks, network security, or PCI controls to "force" a transaction.
For physical damage, suspected device failure, replacement requests, or any unfamiliar terminal model, escalate to Nova support directly.
