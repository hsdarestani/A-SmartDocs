import type { CapacitorConfig } from '@capacitor/cli';

const appUrl = process.env.SMARTDOCS_APP_URL || 'https://smartdocs.aplus-solution.de';
const appHost = new URL(appUrl).hostname;

const config: CapacitorConfig = {
  appId: 'de.aplussolution.smartdocs',
  appName: 'A+ SmartDocs',
  webDir: 'www',
  server: {
    url: appUrl,
    cleartext: false,
    allowNavigation: [appHost],
    androidScheme: 'https',
    iosScheme: 'https'
  },
  android: {
    allowMixedContent: false,
    backgroundColor: '#071c2e'
  },
  ios: {
    contentInset: 'always',
    backgroundColor: '#071c2e',
    webContentsDebuggingEnabled: false
  }
};

export default config;
