# Hardware Star Printers AI FAQ V 1

Source: Zoom Knowledge Library browser export
KB ID: ij7dmuquz1v7s5k2wef44sq1
Article ID: cmp1bhu5n003xrc07movcjcp3
Product lane: General
Source URL: https://novapointofsale.zoom.us/ai-studio/kb/kbs/ij7dmuquz1v7s5k2wef44sq1/articles/cmp1bhu5n003xrc07movcjcp3
Updated: 05/18/2026, 06:20 PM

Hardware — Star Printers — FAQ
Q: Where do I download the Star Micronics printer driver?

A: Download the driver from the official Star Micronics support site: https://starmicronics.com/support/products/tsp100iii-support-page/#unlock. For TSP100 models, look for TSP100 futurePRNT Software Full or TSP100 futurePRNT Software EXE. The official Star download pages are https://starmicronics.com/support/download/tsp100-futureprnt-software-full/ and https://starmicronics.com/support/download/tsp100-futureprnt-software-lite/. Nova-provided Star TSP driver packages are also documented at https://drive.google.com/file/d/1MkCXD_GDLCuKXqvuCcRWTCVLe0ZA_593/view?usp=drive_link and https://drive.google.com/file/d/1vSSWFxPvWmxlvrrb2TYsmCFlq6UNzEXj/view?usp=drive_link for Windows x64/x86 installs. Download the Windows futurePRNT package, extract the ZIP if needed, open the Setup folder, and run Setup as an administrator. If you're not sure which package matches your printer model, call Nova support to have an agent verify and install remotely.

Q: How do I set up a Star Bluetooth receipt printer on Windows?

A: First, print a self-test and confirm Auto Connection is OFF on the printer. Install TSP100 futurePRNT from the Star Micronics site. In Windows, go to Settings > Bluetooth & devices and pair the printer. After pairing, open Settings > Bluetooth & devices > Devices > More devices and printer settings, right-click the printer's Bluetooth device, choose Properties, open the Hardware tab, and write down the COM port number. Open the Star LAN & Bluetooth Setup Tool or TSP100 Configuration Utility and create the printer queue on that COM port. Set that queue as the Windows default printer/default device, print a Windows test page, then test a receipt in Nova Wave.

Q: How do I find the COM port for a paired Star Bluetooth printer?

A: In Windows, open Settings > Bluetooth & devices > Devices > More devices and printer settings, right-click the printer's Bluetooth device, choose Properties, and open the Hardware tab. The COM port is listed there. Use that port in the Star setup utility when creating the printer queue.

Q: How do I set up a Star LAN (Ethernet) printer on Windows?

A: Install TSP100 futurePRNT from the Star Micronics site. Connect the printer to power and Ethernet. Print a self-test and note the IP address listed under Current IP Parameters Status. Open the Star LAN & Bluetooth Setup Tool and run Discovery. If the printer appears, highlight it and choose Printer Queue. If it doesn't appear, choose Create a printer queue by specifying the IP address and enter the model and IP manually. Set that queue as the Windows default printer/default device, print a Windows test page, then test a receipt in Nova Wave. If the printer stops printing later because the IP changed, recreate the queue — or call Nova support to help assign a stable IP.

Q: How do I connect a Star TSP100IIIWIFI printer to Wi-Fi?

A: Confirm the store Wi-Fi is 2.4 GHz — the printer won't join a 5 GHz-only network. Print a self-test and note the printer SSID and the temporary IP 192.168.10.1. On the Windows PC, connect to the printer's temporary Wi-Fi network and wait for it to connect. Open a browser and go to 192.168.10.1. Click Login and sign in with username root and password public. Open WLAN Settings, choose Infrastructure, enter the store Wi-Fi name exactly, set Security Type to AUTO or WPA2/AES, and enter the Wi-Fi password exactly. Save by choosing Save > Configuration Printing > Restart device > Execute. Wait for the printer to reboot and keep the printed config page with the new IP.

Q: Where are the DIP switches on a Star TSP100LAN?

A: On a TSP100LAN, the DIP switches are on the bottom of the printer under a small screw-on cover. Power the printer off, turn it upside down, remove the cover with a Phillips screwdriver, use a narrow tool to move the switch you need, and replace the cover before powering back on. Always power the printer off before changing a DIP switch.

Q: How do I reset a Star TSP100LAN printer to network defaults (DHCP)?

A: Power the printer off, turn it upside down, and remove the DIP switch cover. Set DIP switch 4 to OFF. Turn the printer upright and power it on. Wait about 15 seconds, then power it off again. Return DIP switch 4 to ON and replace the cover. Power the printer back on and print a self-test — it should now show DHCP network settings.

Q: How do I factory-reset a Star TSP100IIIWIFI printer?

A: Power the printer off. Use a paperclip or pen tip to hold the Reset button on the back while powering it on. Keep holding until you hear two initialization sounds. Release the button and wait for the power light to return to solid blue. Print a self-test to confirm the printer is back on its temporary setup network and default IP. After the reset, redo the Wi-Fi setup to reconnect to your store network.

Q: My Star Wi-Fi printer never gets a new IP after I save the network settings. What now?

A: Confirm the store Wi-Fi is 2.4 GHz, the Wi-Fi password was entered exactly correct (case-sensitive), and the security type is set to AUTO or WPA2/AES. If those check out and the printer still doesn't get a new IP or stay on a solid ready light, call Nova support so an agent can finish the network setup remotely.

Q: My Star LAN printer stopped printing after the network changed. How do I fix it?

A: The printer's IP address likely changed when it reconnected to the network. Print a self-test from the printer to see its current IP, then recreate the Windows printer queue with the new IP. Long-term, ask Nova support about assigning a static IP so this doesn't happen again.

Q: My Star Bluetooth printer queue won't print. What do I check?

A: Confirm Windows assigned a COM port to the printer (check the Properties > Hardware tab on the Bluetooth device). If Windows never assigns a COM port, or the queue still won't print after one is assigned, call Nova support so an agent can complete the install remotely.
