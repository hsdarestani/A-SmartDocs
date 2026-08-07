(() => {
  'use strict';

  const cap = () => window.Capacitor;
  const isNative = () => Boolean(cap()?.isNativePlatform?.());
  const plugins = () => cap()?.Plugins || {};
  const nativeSalesPaths = new Set(['/preise', '/registrieren']);

  async function json(url, options = {}) {
    const response = await fetch(url, { credentials: 'same-origin', ...options });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || data.hinweis || `Serverfehler ${response.status}`);
    return data;
  }

  function blobToBase64(blob) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onerror = reject;
      reader.onload = () => resolve(String(reader.result || '').split(',')[1] || '');
      reader.readAsDataURL(blob);
    });
  }

  function normalisierterPfad(href) {
    try {
      const url = new URL(href, window.location.href);
      if (url.origin !== window.location.origin) return null;
      return url.pathname.replace(/\/+$/, '') || '/';
    } catch (_) {
      return null;
    }
  }

  function nativeConsumptionOnly() {
    if (!isNative()) return false;
    document.documentElement.classList.add('native-app');

    const aktuellerPfad = window.location.pathname.replace(/\/+$/, '') || '/';
    if (aktuellerPfad === '/' || nativeSalesPaths.has(aktuellerPfad)) {
      window.location.replace('/anmelden');
      return true;
    }

    // Die Store-Version ist bewusst "consumption only": bestehende Firmenkonten
    // melden sich an und nutzen den Dienst. Tarif-/Registrierungs-CTAs bleiben im
    // öffentlichen Webauftritt, werden aber nicht in Android/iOS angeboten.
    document.querySelectorAll('a[href^="/preise"], a[href^="/registrieren"]').forEach(link => link.remove());
    document.querySelectorAll('.oeffentliche-aktionen').forEach(container => {
      container.querySelectorAll('a[href^="/registrieren"]').forEach(link => link.remove());
    });
    return false;
  }

  async function nativePdfTeilen(button) {
    const root = document.querySelector('.live-editor');
    const entwurfId = Number(root?.dataset.entwurfId || 0);
    const Filesystem = plugins().Filesystem;
    const Share = plugins().Share;
    if (!entwurfId || !Filesystem || !Share) return false;

    const vorher = button.innerHTML;
    button.disabled = true;
    button.textContent = 'PDF wird vorbereitet …';
    try {
      const exportInfo = await json(`/api/workspace/${entwurfId}/export`, { method: 'POST' });
      const pdfResponse = await fetch(exportInfo.download_url, { credentials: 'same-origin' });
      if (!pdfResponse.ok) throw new Error('Die PDF-Datei konnte nicht geladen werden.');
      const base64 = await blobToBase64(await pdfResponse.blob());
      const safeName = String(exportInfo.dateiname || 'SmartDocs.pdf').replace(/[^A-Za-z0-9ÄÖÜäöüß._-]+/g, '-');
      const written = await Filesystem.writeFile({
        path: `SmartDocs/${safeName}`,
        data: base64,
        directory: 'CACHE',
        recursive: true,
      });
      await Share.share({
        title: 'A+ SmartDocs',
        text: 'Fertiges PDF aus A+ SmartDocs',
        url: written.uri,
        dialogTitle: 'PDF sichern oder teilen',
      });
      return true;
    } finally {
      button.disabled = false;
      button.innerHTML = vorher;
    }
  }

  document.addEventListener('click', async event => {
    if (!isNative()) return;

    const link = event.target.closest?.('a[href]');
    if (link) {
      const pfad = normalisierterPfad(link.getAttribute('href'));
      if (pfad && nativeSalesPaths.has(pfad)) {
        event.preventDefault();
        event.stopPropagation();
        window.location.assign('/anmelden');
        return;
      }
    }

    const exportButton = event.target.closest?.('#liveExport');
    if (!exportButton) return;
    const Filesystem = plugins().Filesystem;
    const Share = plugins().Share;
    if (!Filesystem || !Share) return;
    event.preventDefault();
    event.stopPropagation();
    event.stopImmediatePropagation();
    try {
      await nativePdfTeilen(exportButton);
    } catch (error) {
      window.meldung?.(error.message || 'PDF konnte nicht geteilt werden.', 'fehler');
    }
  }, true);

  document.addEventListener('DOMContentLoaded', () => {
    if (!isNative()) return;
    if (nativeConsumptionOnly()) return;
    const App = plugins().App;
    App?.addListener?.('backButton', () => {
      if (history.length > 1) history.back();
      else App.exitApp?.();
    });
  });
})();
