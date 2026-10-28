# Hardware Star Printers AI Knowledge Source V 1

Source: Zoom Knowledge Library browser export
KB ID: ij7dmuquz1v7s5k2wef44sq1
Article ID: cmp1bhws323yfsy07hm2284bk
Product lane: General
Source URL: https://novapointofsale.zoom.us/ai-studio/kb/kbs/ij7dmuquz1v7s5k2wef44sq1/articles/cmp1bhws323yfsy07hm2284bk
Updated: 05/18/2026, 06:20 PM

Hardware — Star Printers — Knowledge Source

Detailed setup, configuration, and reset procedures for Star Micronics receipt printers (TSP100 series — including TSP100, TSP100LAN, TSP100IIIWIFI). For expanded Star light codes, TSP100IV driver notes, and model-specific troubleshooting, also retrieve the Receipt Printers Brand and Model Troubleshooting knowledge source. For general receipt printer troubleshooting that applies to any brand, see the Receipt Printers (General) knowledge source.

Downloading the Star Driver (futurePRNT)

The driver for the TSP100 series is futurePRNT, available from the official Star Micronics support site.

Use these documented download links when a Star TSP driver install is required:

Official Star Micronics TSP100III support page: https://starmicronics.com/support/products/tsp100iii-support-page/#unlock
Official Star Micronics TSP100 futurePRNT Software Full download page: https://starmicronics.com/support/download/tsp100-futureprnt-software-full/
Official Star Micronics TSP100 futurePRNT Software Setup EXE download page: https://starmicronics.com/support/download/tsp100-futureprnt-software-lite/
Nova-provided Star TSP printer driver package: https://drive.google.com/file/d/1MkCXD_GDLCuKXqvuCcRWTCVLe0ZA_593/view?usp=drive_link
Nova-provided Star TSP Windows x64/x86 driver package: https://drive.google.com/file/d/1vSSWFxPvWmxlvrrb2TYsmCFlq6UNzEXj/view?usp=drive_link
On the Star Micronics support site, locate the TSP100 driver package — look for TSP100 futurePRNT Software Full or TSP100 futurePRNT Software EXE.
Download the Windows futurePRNT package.
If Windows downloads it as a ZIP archive, extract it.
Open the Setup folder.
Right-click Setup and run as administrator.
Escalation

If the customer isn't sure which Star package matches their printer model, escalate to Nova support so an agent can remote in and install the correct driver.

Star Bluetooth Setup on Windows

This procedure pairs a Star Bluetooth-capable printer with a Windows workstation and creates a Star printer queue on the assigned COM port.

Prerequisites
The Star Bluetooth printer is powered on.
The workstation has Bluetooth capability (built-in or USB Bluetooth adapter).
Steps
Print a self-test from the printer and confirm Auto Connection is OFF. If Auto Connection is ON, the printer will not pair correctly.
Download and install TSP100 futurePRNT from the official Star Micronics support site.
In Windows, go to Settings > Bluetooth & devices and pair the printer.
After pairing, open Settings > Bluetooth & devices > Devices > More devices and printer settings.
Right-click the printer's Bluetooth device, choose Properties, and open the Hardware tab.
Write down the COM port number shown on the Hardware tab. (This is also documented separately under "Finding the COM Port" below.)
Open the Star LAN & Bluetooth Setup Tool or TSP100 Configuration Utility.
Create the printer queue on that COM port.
Set that Star queue as the Windows default printer/default device.
Print a Windows test page.
Test a receipt in Nova Wave.
Escalation

Escalate to Nova support if:

Windows never assigns a COM port to the Bluetooth printer.
The printer queue is created but will not print.
The customer is not comfortable navigating Device Manager / Bluetooth properties.
Finding the COM Port for a Star Bluetooth Printer

If the printer is already paired in Windows and you just need the COM port number:

Open Settings > Bluetooth & devices > Devices > More devices and printer settings.
Right-click the printer's Bluetooth device.
Choose Properties.
Open the Hardware tab.
The COM port is listed there.

Use that port number in the Star setup utility when creating the printer queue.

Star LAN (Ethernet) Setup on Windows

This procedure sets up a Star LAN printer on Windows using the printer's IP address.

Steps
Download and install TSP100 futurePRNT from the official Star Micronics support site.
Connect the printer to power and Ethernet.
Print a self-test from the printer. Write down the IP address listed under Current IP Parameters Status.
Open the Star LAN & Bluetooth Setup Tool and run Discovery.
If the printer appears in the discovery list:
Highlight it.
Choose Printer Queue to create the queue.
If the printer does NOT appear:
Choose Create a printer queue by specifying the IP address.
Enter the printer model and IP address manually.
Set that Star queue as the Windows default printer/default device.
Print a Windows test page.
Test a receipt in Nova Wave.
IP Change Issues

If the printer stops printing later, the IP address may have changed (DHCP renewal). Either:

Recreate the queue with the new IP from a fresh self-test.
Call Nova support to help assign a static IP so this doesn't happen again.
Star TSP100IIIWIFI Wi-Fi Setup

This procedure connects a TSP100IIIWIFI to the store's Wi-Fi network.

Prerequisites
The store Wi-Fi network is 2.4 GHz. The printer will not join a 5 GHz-only network. If the network is dual-band, confirm the 2.4 GHz SSID is broadcasting.
You know the exact store Wi-Fi name and password (case-sensitive).
Steps
Print a self-test and note the printer SSID and the temporary IP address 192.168.10.1.
On the Windows PC, connect to the printer's temporary Wi-Fi network. Wait until Windows shows it connected.
Open a browser and go to 192.168.10.1.
Click Login and sign in with username root and password public.
Open WLAN Settings:
Choose Infrastructure.
Enter the store Wi-Fi name exactly.
Set Security Type to AUTO or WPA2/AES.
Enter the Wi-Fi password exactly (case-sensitive).
Save the settings in this sequence: choose Save, then Configuration Printing, then Restart device, then Execute.
Wait for the printer to reboot. Keep the printed configuration page — it will show the new IP address assigned by your store network.
Escalation

If the printer never receives a new IP address, or the ready light does not return to solid, call Nova support so an agent can finish the network setup remotely.

DIP Switches on the TSP100LAN

The DIP switches on a TSP100LAN are on the bottom of the printer under a small screw-on cover.

Steps to Access
Power the printer off.
Turn the printer upside down.
Remove the cover with a Phillips screwdriver.
Use a narrow tool to move the switch you need.
Replace the cover before powering the printer back on.
Safety

Always power the printer off before changing a DIP switch. Do not change DIP switches with the printer powered on.

TSP100LAN Factory Reset (Back to DHCP / Network Defaults)

This procedure resets the TSP100LAN network configuration so it requests a new IP from DHCP.

Power the printer off.
Turn it upside down and remove the DIP switch cover with a Phillips screwdriver.
Set DIP switch 4 to OFF.
Turn the printer upright and power it on.
Wait about 15 seconds, then power it off again.
Return DIP switch 4 to ON and replace the cover.
Power the printer back on and print a self-test.

The self-test should now show DHCP network settings.

Escalation

If the self-test does not show DHCP settings after the reset, escalate to Nova support.

TSP100IIIWIFI Factory Reset

This procedure resets the TSP100IIIWIFI back to its temporary setup Wi-Fi network and default IP (192.168.10.1).

Power the printer off.
Use a paperclip or pen tip to hold the Reset button on the back while powering the printer on.
Keep holding the button until you hear two initialization sounds.
Release the button and wait for the power light to return to solid blue.
Print a self-test to confirm the printer returned to its temporary setup network and default IP.

After the reset, redo the TSP100IIIWIFI Wi-Fi Setup procedure above to reconnect the printer to the store network.

Safety and Customer Comfort Rules
DIP switch changes require opening the printer with a screwdriver. If the customer is uncomfortable, offer a remote support session as an alternative.
Always power the printer off before any DIP switch change.
Never instruct the customer to open the printer beyond the documented DIP switch cover or paper compartment.
Default credentials (root / public) are for initial setup of the TSP100IIIWIFI web UI. Do not share these for any other use or device.
