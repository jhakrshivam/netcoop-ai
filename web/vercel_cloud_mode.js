(function () {
  function banner() {
      if (!location.hostname.endsWith('.vercel.app') || document.querySelector('.cloud-viewer-banner')) return;
      const node = document.createElement('div'); node.className = 'cloud-viewer-banner';
      node.innerHTML = '<strong>Synthetic cloud demonstration</strong><span>All displayed network values are fabricated demo data for presentation. Real Windows Wi-Fi, hardware, and local-network data require the local NetCoop collector.</span>';
      document.body.prepend(node);
  }
  window.addEventListener('load', banner);
})();
