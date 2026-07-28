(() => {
  'use strict';

  const schema = document.querySelector('#workflowSchema');
  if (!schema) return;

  const parameter = new URLSearchParams(window.location.search).get('modus');
  if (!['chat', 'manuell'].includes(parameter)) return;

  window.requestAnimationFrame(() => {
    const knopf = document.querySelector(`[data-workflow-modus="${parameter}"]`);
    if (!knopf) return;
    knopf.click();

    if (parameter === 'manuell') {
      window.setTimeout(() => document.querySelector('#workflowFeldWerkzeug')?.focus(), 0);
    } else {
      window.setTimeout(() => document.querySelector('#workflowChatText')?.focus(), 0);
    }
  });
})();
