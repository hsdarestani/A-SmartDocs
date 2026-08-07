# A+ SmartDocs – Store Release

App name: **A+ SmartDocs**  
Android package / iOS bundle ID: **de.aplussolution.smartdocs**

## Public URLs

Set the repository Actions variable `SMARTDOCS_APP_URL` to the public HTTPS base URL of SmartDocs.
The store metadata then uses:

- Privacy Policy: `${SMARTDOCS_APP_URL}/datenschutz-app`
- Support URL: `${SMARTDOCS_APP_URL}/support`
- Account deletion URL: `${SMARTDOCS_APP_URL}/konto-loeschen`
- Terms: `${SMARTDOCS_APP_URL}/nutzungsbedingungen`

## Google Play

Workflow: `SmartDocs Android → Google Play`

Required repository secrets:
- `ANDROID_KEYSTORE_BASE64`
- `ANDROID_KEYSTORE_PASSWORD`
- `ANDROID_KEY_ALIAS`
- `ANDROID_KEY_PASSWORD`
- `GOOGLE_PLAY_SERVICE_ACCOUNT_JSON_BASE64`

The first Google Play app record for package `de.aplussolution.smartdocs` must be created in Play Console once before API uploads. The workflow publishes signed AAB builds to **Internal testing**.

## Apple

Workflow: `SmartDocs iOS → TestFlight`

Required repository secrets:
- `APPLE_TEAM_ID`
- `IOS_DISTRIBUTION_CERT_P12_BASE64`
- `IOS_DISTRIBUTION_CERT_PASSWORD`
- `IOS_PROVISIONING_PROFILE_BASE64`
- `ASC_KEY_ID`
- `ASC_ISSUER_ID`
- `ASC_PRIVATE_KEY_BASE64`

Create the App ID / Bundle ID `de.aplussolution.smartdocs`, an App Store Distribution provisioning profile for that Bundle ID, and the App Store Connect app record once. The workflow archives a signed IPA and uploads it to TestFlight.

## Policy declarations

- Google Data Safety working notes: `store/google/data-safety.md`
- Apple App Privacy working notes: `store/apple/app-privacy.md`
- No advertising SDK, advertising ID, cross-app tracking, location, contacts, microphone, camera or broad storage access is required by the mobile shell.
- Account deletion is available in-app and through the public web URL.
