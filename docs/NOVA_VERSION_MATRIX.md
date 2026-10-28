# Nova Version Matrix

<!-- AgentChat/coding_agent 2026-08-01T16:54:05Z -->

Last evidence refresh: 2026-08-01

This is the public operational version index mirrored into the Ghost Busters
Zoom `Chat Overview`. Source discovery is limited to Gmail drafts, Slack
messages, and Zoom messages dated 2025-01-01 or later. A route is listed only
when one of those sources explicitly identified it.

## Current product families

| Product or route | Verified version or state | Operational use |
|---|---|---|
| Nova Wave | `0.1.5.3` | Pinned Zoom release. Use the Wave installer route for Wave deployments. |
| [`Alpha-NovaX/setup.exe`](https://pos.novapointofsale.com/novapos/Alpha-NovaX/setup.exe) | Current route restored 2026-07-22 | Nova Classic sales with Nova Wave backoffice. |
| Nova Wave backoffice | Current | `https://backoffice.novapointofsale.com/` |
| Nova Wave staging backoffice | Available | Use only when the request explicitly calls for staging. |
| Nova 8 | `8.0.0.3` | WinForms client with backoffice. Slack shorthand `8.0.03` refers to this build; retain the four-part version until confirmed otherwise. |
| Nova 7 Propellr | `7.0.0.67` | Propellr build. Enable Propellr before launch. |
| Nova 5 stable | `5.6.0.5` | Stable Nova 5 route: [`nextgenbeta_rtd/setup.exe`](https://pos.novapointofsale.com/novapos/nextgenbeta_rtd/setup.exe). |
| Nova XP legacy | `4.5.0.22` | Verified HTTPS legacy route: [`butterfly/setup.exe`](https://pos.novapointofsale.com/novapos/butterfly/setup.exe). Sources also mention `nova4xp/setup.exe`; treat it as a distinct route until verified. |
| Portugal | `4.6.1.86` | Verified HTTPS regional route: [`portugalsequence/setup.exe`](https://pos.novapointofsale.com/novapos/portugalsequence/setup.exe). |
| Austria | `5.7.9.16` | Country-specific route with Obono QR behavior. The supplied Drive folder is not registered because anonymous public access was not verified. |

## Nova 7 installer variants

| Route | Verified purpose |
|---|---|
| [`Alpha-2025`](https://pos.novapointofsale.com/novapos/Alpha-2025/setup.exe) | Worldpay tips, digital signature, and Lane3600. It is not the newest ChipDNA route. |
| [`Alpha-2024-Credit-Call`](https://pos.novapointofsale.com/novapos/Alpha-2024-Credit-Call/setup.exe) | Newest identified ChipDNA Lane3000/Creditcall route. |
| [`alpha3`](https://pos.novapointofsale.com/novapos/alpha3/setup.exe) | Layaway flow that enforces customer information. |
| [`Alpha-2024`](https://pos.novapointofsale.com/novapos/Alpha-2024/setup.exe) | Blocks manual Worldpay TriPOS handling. |
| [`Alpha-ExtraPaymentMethods`](https://pos.novapointofsale.com/novapos/Alpha-ExtraPaymentMethods/setup.exe) | Extra payment methods, surcharge support, and Stopper calculation behavior. |
| [`Alpha-AuthorizeNet`](https://pos.novapointofsale.com/novapos/Alpha-AuthorizeNet/setup.exe) | Augusta/Authorize.Net route. |
| `Beta/setup.exe` | Distinct beta route; do not substitute `nextgenbeta_rtd`. |

## Nova 7 build evidence

The 2025-and-newer Slack and Zoom evidence contains these explicit builds:

`7.0.0.35`, `7.0.0.55`, `7.0.0.56`, `7.0.0.57`, `7.0.0.60`,
`7.0.0.61`, `7.0.0.62`, `7.0.0.66`, and `7.0.0.67`.

Operational notes:

- `7.0.0.67` is the verified Propellr build.
- `7.0.0.66` has an offline-use issue in Zoom evidence.
- A `7.0.0.62` request was redirected to `Alpha-2024-Credit-Call`; do not infer
  that every `.62` installation should use that route without checking the
  requested payment integration.
- A Gmail draft explicitly identifies `7.0.0.55`.

## Public resources

- [Printer drivers](https://drive.google.com/drive/u/0/folders/1futCMqrBpsOmpmrfq0btyJaiXl2KpP0r)
- [Nova Public training materials and guides](https://drive.google.com/drive/u/0/folders/1npgxOUKfyyQ5GEnPPpka9qjcf13anXuS)
- [Nova Wave certificate guide](https://docs.google.com/document/d/1d15QOIBZO27ULnjTWcInfOUvDtsy4J45p8g7HWMFc6E/edit?tab=t.0)

The printer folder includes Star, Epson, XPrinter, SNBC, Sewoo, Citizen, DYMO,
thermal, and related driver sections. The Nova Public folder includes Setup
Guides, Manuals, Learning Nova, PC Safety and Security Practices, Payment
Gateways and Processors, NovaPOS Account Close Request, Worldpay merchant
information, and gateway signup resources. Do not publish private or sensitive
question material from the shared drive.

## Publication standard

The fixed Ghost Busters `Chat Overview` is a support-team resource. Add only
public operational versions, tools, links, initiatives, topics, and reminders
supported by 2025-or-newer evidence. Every published HTTPS link must already
appear in this matrix; never infer a download URL from a naming pattern. Never
publish customer or account details, ticket or subscription identifiers, phone
numbers, email addresses, personal or person-specific notes, one-on-one
material, HR or performance content, agent-specific maintenance policy,
secrets, credentials, or access tokens.
