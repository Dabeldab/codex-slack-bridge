# Hardware Card Terminals AI FAQ V 1

Source: Zoom Knowledge Library browser export
KB ID: ij7dmuquz1v7s5k2wef44sq1
Article ID: cmp1bi1n423ygsy07uamqo46n
Product lane: General
Source URL: https://novapointofsale.zoom.us/ai-studio/kb/kbs/ij7dmuquz1v7s5k2wef44sq1/articles/cmp1bi1n423ygsy07uamqo46n
Updated: 05/18/2026, 06:20 PM

Hardware — Card Terminals — FAQ
Q: My card terminal isn't connecting. What do I do?

A: Make sure the terminal is powered on and on the same Wi-Fi network as your workstation. Restart the terminal (hold the power button or unplug and reconnect power), then close and reopen Nova. If the device needs to be set up, go to Back Office > Locations > Settings > Edit > Merchant Services in Nova Wave, follow the on-screen steps, enter the credentials from your merchant service provider, save, and run a $0.01 test transaction. If it still won't connect, call Nova support.

Q: How do I set up a Lane 3000, 3600, 5000, or 7000 with WorldPay?

A: Connect the terminal to an open Ethernet port until it shows an activation code. In Nova Wave, go to Back Office > Locations > Settings > Edit > Merchant Services, choose WorldPay, select the correct EMV device, enter the merchant information, and pair the device using the activation code shown on the terminal. Save and run a small test transaction. If the terminal never shows an activation code, confirm the network connection. This procedure is for WorldPay only.

Q: How do I set up a Link 2500 with WorldPay?

A: The Link 2500 follows the same WorldPay setup as the Lane series, except it connects over Wi-Fi instead of Ethernet. Connect the Link 2500 to Wi-Fi first (see "How do I connect a Link 2500 to Wi-Fi?"), wait for the activation code, then in Nova Wave go to Back Office > Locations > Settings > Edit > Merchant Services, choose WorldPay, enter your merchant info, and pair using the activation code.

Q: How do I set up a Lane 3000 with Creditcall / NMI?

A: This setup is for Creditcall/NMI only (sometimes labeled ChipDNA or GSPayTech). Install the Nova build and drivers that support Creditcall/NMI. Open Device Manager, find the Lane 3000 under Ports, right-click and open Properties > Port Settings, change Bits per second to 115200, click Advanced, and set COM Port Number to COM5 (allow the prompt about another device using the port). Restart the computer if asked. In Nova Wave, open Back Office > Locations > Settings > Edit > Merchant Services, choose GSPayTech, enter the merchant credentials, and save to generate the ChipDNA configuration file. Restart the PC if it hasn't already. Open Nova, log in to the Storefront, and run a small test transaction.

Q: How do I connect a Link 2500 to Wi-Fi?

A: On the terminal, enter 2634, press F, and open Tetra Admin. Choose Configure Wi-Fi, scan for networks, select the store network, and enter the password. Save and wait for the Wi-Fi icon to turn green. When the terminal shows an activation code, pair it in Nova Wave under Back Office > Locations > Settings > Edit > Merchant Services.

Q: I'm getting an "EMV subscription for this location has expired" error. What do I do?

A: Close and reopen Nova, restart the payment terminal (hold power or unplug it), reconnect the terminal to the PC or network, and run a test charge. If the error returns after restart, the location EMV or merchant-service setup needs review by merchant services.

Q: Why can't I process credit card sales through my external terminal?

A: Check the merchant-services settings for the location. Open Back Office > Locations > Settings > Edit > Merchant Services in Nova Wave, review the external payment or terminal settings, clear any setting that blocks the external payment method, save the location settings, and run a new card sale. If the setting is already correct and card sales are still unavailable, call Nova support.

Q: My terminal never shows an activation code. What's wrong?

A: This usually means the terminal isn't fully on the network yet. For Ethernet-connected terminals (Lane 3000/3600/5000/7000), confirm the Ethernet cable is firmly plugged in at both ends and the port is active. For Wi-Fi terminals (Link 2500), confirm the Wi-Fi icon is solid (not flashing or white) before expecting an activation code. If the network is good and the terminal still doesn't show a code, call Nova support for remote help.

Q: What payment terminals does Nova support?

A: Nova supports the Ingenico Lane series (Lane 3000, 3600, 5000, 7000) with WorldPay or Creditcall/NMI, and the Ingenico Link 2500 over Wi-Fi. Specific setup steps differ based on the processor. If you're not sure which terminal or processor you have, contact Nova support before purchasing or installing.

Q: My card terminal isn't tapping / contactless isn't working. What should I check?

A: Restart the terminal and reconnect it to the PC or network. If contactless is still not working after a restart, this needs hands-on review — call Nova support so an agent can verify the terminal's contactless configuration with the processor.
