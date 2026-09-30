// Gradio 6 injects this file as a plain <script>, so it runs itself.
(() => {
  // Phones: collapse long option groups (e.g. style details) the first time they render.
  // Tabs mount lazily, so watch for new blocks instead of scanning once.
  const mobile = window.matchMedia('(max-width: 767px)');
  const collapse = () => {
    if (!mobile.matches) return;
    document.querySelectorAll('.mobile-collapse:not([data-collapsed])').forEach((block) => {
      const label = block.querySelector(':scope > button.label-wrap');
      if (!label) return;
      block.dataset.collapsed = '1';
      if (label.classList.contains('open')) label.click();
    });
  };
  const start = () => {
    new MutationObserver(collapse).observe(document.body, { childList: true, subtree: true });
    collapse();
  };
  if (document.body) start();
  else document.addEventListener('DOMContentLoaded', start);
})();
