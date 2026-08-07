import fs from 'node:fs';
import path from 'node:path';

const platform = process.argv[2];
const root = process.cwd();

function replaceFile(file, transform) {
  if (!fs.existsSync(file)) throw new Error(`Datei fehlt: ${file}`);
  const before = fs.readFileSync(file, 'utf8');
  const after = transform(before);
  if (before !== after) fs.writeFileSync(file, after);
}

function android() {
  const variables = path.join(root, 'android', 'variables.gradle');
  replaceFile(variables, text => text
    .replace(/minSdkVersion\s*=\s*\d+/, 'minSdkVersion = 26')
    .replace(/compileSdkVersion\s*=\s*\d+/, 'compileSdkVersion = 36')
    .replace(/targetSdkVersion\s*=\s*\d+/, 'targetSdkVersion = 36'));

  const manifest = path.join(root, 'android', 'app', 'src', 'main', 'AndroidManifest.xml');
  replaceFile(manifest, text => {
    // SmartDocs benötigt keine Kontakte-, Standort-, Kamera-, Mikrofon- oder Speicherberechtigung.
    text = text.replace(/\s*<uses-permission[^>]+android:name="android\.permission\.(READ_EXTERNAL_STORAGE|WRITE_EXTERNAL_STORAGE|READ_MEDIA_IMAGES|READ_MEDIA_VIDEO|CAMERA|RECORD_AUDIO|ACCESS_FINE_LOCATION|ACCESS_COARSE_LOCATION|READ_CONTACTS|POST_NOTIFICATIONS)"[^>]*\/>/g, '');
    if (!/android\.permission\.INTERNET/.test(text)) {
      text = text.replace('<application', '<uses-permission android:name="android.permission.INTERNET" />\n    <application');
    }
    text = text.replace(/<application\b([^>]*)>/, (_m, attrs) => {
      let next = attrs
        .replace(/\sandroid:usesCleartextTraffic="[^"]*"/g, '')
        .replace(/\sandroid:allowBackup="[^"]*"/g, '')
        .replace(/\sandroid:fullBackupContent="[^"]*"/g, '');
      return `<application${next} android:usesCleartextTraffic="false" android:allowBackup="false" android:fullBackupContent="false">`;
    });
    return text;
  });

  const gradle = path.join(root, 'android', 'app', 'build.gradle');
  replaceFile(gradle, text => {
    const marker = '// SMARTDOCS_RELEASE_SIGNING';
    if (!text.includes(marker)) {
      text = `import java.util.Properties\nimport java.io.FileInputStream\n\ndef smartdocsKeystoreProperties = new Properties()\ndef smartdocsKeystorePropertiesFile = rootProject.file("keystore.properties")\nif (smartdocsKeystorePropertiesFile.exists()) { smartdocsKeystoreProperties.load(new FileInputStream(smartdocsKeystorePropertiesFile)) }\n\n${text}`;
      text = text.replace(/\n\s*buildTypes\s*\{/, `\n    ${marker}\n    signingConfigs {\n        release {\n            if (smartdocsKeystorePropertiesFile.exists()) {\n                storeFile rootProject.file(smartdocsKeystoreProperties['storeFile'])\n                storePassword smartdocsKeystoreProperties['storePassword']\n                keyAlias smartdocsKeystoreProperties['keyAlias']\n                keyPassword smartdocsKeystoreProperties['keyPassword']\n            }\n        }\n    }\n\n    buildTypes {`);
      text = text.replace(/buildTypes\s*\{\s*release\s*\{/, 'buildTypes {\n        release {\n            signingConfig signingConfigs.release');
    }
    return text;
  });
}

function ios() {
  const plist = path.join(root, 'ios', 'App', 'App', 'Info.plist');
  replaceFile(plist, text => {
    if (!text.includes('<key>ITSAppUsesNonExemptEncryption</key>')) {
      text = text.replace('</dict>', '  <key>ITSAppUsesNonExemptEncryption</key>\n  <false/>\n  <key>UIFileSharingEnabled</key>\n  <true/>\n  <key>LSSupportsOpeningDocumentsInPlace</key>\n  <true/>\n</dict>');
    }
    return text;
  });

  // Manifest wird im iOS-Workflow mittels xcodeproj dem App-Target hinzugefügt.
  const privacy = path.join(root, 'ios', 'App', 'App', 'PrivacyInfo.xcprivacy');
  fs.writeFileSync(privacy, `<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n<plist version="1.0"><dict>\n<key>NSPrivacyTracking</key><false/>\n<key>NSPrivacyTrackingDomains</key><array/>\n<key>NSPrivacyCollectedDataTypes</key><array/>\n<key>NSPrivacyAccessedAPITypes</key><array/>\n</dict></plist>\n`);
}

if (platform === 'android') android();
else if (platform === 'ios') ios();
else throw new Error('Platform muss android oder ios sein.');
