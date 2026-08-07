# Google Play – Data Safety für A+ SmartDocs

Package: `de.aplussolution.smartdocs`

## Data collection

A+ SmartDocs verkauft keine Nutzerdaten und verwendet keine Daten für Werbung oder Cross-App-Tracking.

### Account / Personal info
- Name: collected, required for account/profile and team collaboration.
- Email address: collected, required for authentication, account management and support.
- Organization/profile information: collected, required for company workspace functionality.

### Files and documents
- User files / PDFs: collected when the user uploads a document; required for document editing, preview and export.
- Generated PDFs: stored for the user's document history/export until deleted according to the service retention rules.

### App interactions / User content
- Chat/edit instructions: collected when the user uses chat-assisted editing.
- AI processing: only the text necessary for an AI-requested or ambiguous edit may be sent to the configured AI processor. Direct click/text/checkbox edits are processed without AI when possible.

### App activity / diagnostics
- Feature usage and technical events: collected for security, limits, product operation and error diagnosis.

### Financial info
- Subscription/invoice status may be stored for account and billing administration. No payment-card data is collected by the mobile app itself.

## Security practices
- Data encrypted in transit via HTTPS.
- Organization-separated access and role-based authorization.
- User can request deletion in-app and through the public deletion URL.
- Privacy policy: `/datenschutz-app`
- External account deletion URL: `/konto-loeschen`

## Device permissions
The Android build is intentionally restricted to Internet/network access required for the service. SmartDocs does not require location, contacts, microphone, camera, advertising ID or broad external-storage permissions for its core workflow. Files are chosen by user action through the platform file picker.
