# App Store rebuild trigger

This file intentionally lives under `mobile/assets/` so a compliance-only release can trigger the existing iOS TestFlight workflow without modifying the app icon source.

It is not consumed by the application at runtime and is ignored by Capacitor's image asset generation. Current trigger: App Store enterprise-services compliance update, 2026-08-14.
