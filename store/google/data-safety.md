# Google Play – Data Safety für A+ SmartDocs

Package: `de.aplussolution.smartdocs`

Diese Datei ist die interne Vorlage für das Data-Safety-Formular in Google Play Console. Sie muss mit dem tatsächlichen Produktverhalten synchron bleiben.

## Grundangaben

- App sammelt Nutzerdaten: **Ja**
- App teilt Nutzerdaten zu Werbe-/Trackingzwecken: **Nein**
- Datenverkauf: **Nein**
- Werbung / Werbenetzwerke / Cross-App-Tracking: **Nein**
- Datenverschlüsselung bei Übertragung: **Ja (HTTPS)**
- Nutzer können Löschung anfordern: **Ja**
- Löschung direkt in der App: **Ja, Einstellungen → Konto endgültig löschen**
- Öffentliche Lösch-URL: `https://smartdocs.aplus-solution.de/konto-loeschen`
- Datenschutz-URL: `https://smartdocs.aplus-solution.de/datenschutz-app`

## Zu deklarierende Datentypen

### Personal info

**Name**
- Collected: Yes
- Shared: No
- Required: Yes for account/profile/team use
- Purpose: Account management, app functionality

**Email address**
- Collected: Yes
- Shared: No
- Required: Yes
- Purpose: Authentication, account management, support

**Other personal info / organization profile**
- Company name, role, team assignment and optional company contact information
- Collected: Yes
- Shared: No
- Purpose: App functionality, account management

### Files and docs

**Files and docs**
- Uploaded PDFs/images and generated PDF outputs
- Collected: Yes, only when the user uploads/creates them
- Shared: No as an independent third-party use
- Purpose: App functionality

### Other user-generated content

**Chat/edit instructions and correction text**
- Collected: Yes when the user uses the relevant feature
- Shared: No for independent third-party purposes
- Purpose: App functionality
- Note: For an AI-requested or ambiguous edit, only the necessary instruction/text may be processed by the configured AI service provider on behalf of A+ SmartDocs.

### App activity

**App interactions / feature usage**
- Collected: Yes
- Shared: No
- Purpose: App functionality, security/fraud prevention, usage limits and technical diagnosis

### Financial info

**Purchase/subscription history or billing status**
- The mobile app does not collect card or bank-account details.
- SmartDocs may store the company plan, invoice status and account activation/billing state on the server.
- If Play Console asks whether purchase history/subscription status is collected, declare it conservatively as **Collected: Yes**, **Shared: No**, for **Account management**.

## AI and service providers

A technical service provider acting on behalf of A+ SmartDocs is treated as a service provider/processor, not as an independent recipient for advertising or tracking. No user data is sold. No advertising profile is created.

## Device permissions

The Android build is intentionally restricted to the permissions needed for the service. Core functionality does not require:

- precise or approximate location
- contacts
- microphone
- advertising ID
- broad external-storage access
- permanent access to the full photo library

Files are selected by explicit user action through the operating system file picker. Internet access is required to connect to `smartdocs.aplus-solution.de`.

## Store consistency check

Before every production submission confirm that:

1. Privacy policy still matches the current product.
2. Account deletion works both in-app and at the public deletion URL.
3. No analytics/ads SDK was added without updating this declaration.
4. Any new device permission or data processor is reflected here and in `/datenschutz-app`.
