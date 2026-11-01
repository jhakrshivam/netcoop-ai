(function () {
  async function banner() {
    try {
      const health = await fetch('/api/health').then(response => response.json());
      if (health.mode !== 'cloud-viewer' || document.querySelector('.cloud-viewer-banner')) return;
      const node = document.createElement('div'); node.className = 'cloud-viewer-banner';
      node.innerHTML = '<strong>Cloud viewer mode</strong><span>Live Windows Wi-Fi, hardware, and local-network data remain available only through the local NetCoop collector. This hosted view does not invent readings.</span>';
      document.body.prepend(node);
    } catch (_) {}
  }
  window.addEventListener('load', banner);
})();
