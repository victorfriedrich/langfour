// Links open in Safari (where the extension runs), not inside this web view.
document.addEventListener('click', (event) => {
    const button = event.target.closest('[data-open]');
    if (!button) return;
    webkit.messageHandlers.controller.postMessage({ open: button.dataset.open });
});

