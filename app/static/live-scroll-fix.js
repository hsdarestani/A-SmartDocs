(() => {
  const scroller = document.getElementById('liveDocumentScroll');
  const input = document.getElementById('liveChatInput');
  if (!scroller || !input) return;
  let top = scroller.scrollTop;
  let left = scroller.scrollLeft;
  scroller.addEventListener('scroll', () => {
    top = scroller.scrollTop;
    left = scroller.scrollLeft;
  }, { passive: true });
  input.addEventListener('focus', () => {
    requestAnimationFrame(() => {
      scroller.scrollTop = top;
      scroller.scrollLeft = left;
    });
  }, true);
})();
