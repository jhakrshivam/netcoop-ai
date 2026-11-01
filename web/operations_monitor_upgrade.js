/* Local operations panels: alerts, confidence trace, passive throughput, and download history. */
(function () {
  const state = () => typeof S === 'undefined' ? null : S;
  const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  let alertCache = null, lastAlertFetch = 0;
  const panel = selector => document.querySelector(selector);

  function alertMarkup(data) {
    const trace = data?.confidence_trace || {}, alerts = data?.alerts || [];
    const alertRows = alerts.length ? alerts.map(item => `<li class="alert-${esc(item.severity)}"><b>${esc(item.title)}</b><span>${esc(item.detail)}</span><small>${esc(item.source)}</small></li>`).join('') : '<li class="alert-normal"><b>No active local alerts</b><span>Available local signals are within the configured alert thresholds.</span></li>';
    return `<div class="alert-layout"><div><ul class="alert-list">${alertRows}</ul></div><div class="confidence-trace"><b>Confidence trace</b><span>${esc(trace.checked_count ?? 0)} signal(s) checked · coverage ${esc(trace.coverage ?? 0)}</span><small>${esc(trace.method || 'Waiting for local samples.')}</small></div></div>`;
  }
  async function refreshAlerts(force=false) {
    if (!force && Date.now() - lastAlertFetch < 5000) { if (alertCache && panel('.local-alert-body')) panel('.local-alert-body').innerHTML = alertMarkup(alertCache); return; }
    try { const response = await fetch('/api/alerts'); alertCache = await response.json(); lastAlertFetch = Date.now(); const body = panel('.local-alert-body'); if (body) body.innerHTML = alertMarkup(alertCache); } catch { const body = panel('.local-alert-body'); if (body) body.textContent = 'Alert monitor is temporarily unavailable.'; }
  }
  async function refreshDownloads() {
    try { const response = await fetch('/api/downloads/recent'); const data = await response.json(), body = panel('.download-history-body'); if (!body) return; body.innerHTML = (data.downloads || []).length ? `<ul class="download-history-list">${data.downloads.map(item => `<li><b>${esc(item.filename)}</b><span>${esc(item.created_at)}</span></li>`).join('')}</ul>` : '<div class="empty">Downloads appear here after you click a JSON report download.</div>'; } catch { const body = panel('.download-history-body'); if (body) body.textContent = 'Download history is temporarily unavailable.'; }
  }
  function addOperationsPanels() {
    const app = state(); if (!app || app.page !== 'live') return;
    const page = document.querySelector('.page'); if (!page || page.querySelector('.operations-monitor')) return;
    page.insertAdjacentHTML('beforeend', `<section class="card operations-monitor"><div class="card-head"><span class="card-title">Alert monitor</span><span class="card-kicker">READ-ONLY LOCAL RULES</span></div><div class="card-body local-alert-body">Checking local signals…</div></section><section class="card throughput-scan-panel"><div class="card-head"><span class="card-title">Local throughput scan</span><button class="btn primary" data-action="throughput-scan">Scan local adapter traffic</button></div><div class="card-body throughput-result"><p class="note">This passive scan measures this computer’s current adapter traffic. It does not generate traffic or claim Internet speed.</p></div></section><section class="card download-history-panel"><div class="card-head"><span class="card-title">Downloaded JSON files</span><span class="card-kicker">THIS DEVICE</span></div><div class="card-body download-history-body">Loading download history…</div></section>`);
    refreshAlerts(); refreshDownloads();
  }
  async function runThroughputScan(button) {
    button.disabled = true; button.textContent = 'Scanning…';
    try { const response = await fetch('/api/network/throughput-scan',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'}); const data = await response.json(); if (!response.ok) throw Error(data.error || 'Scan failed'); const report = data.report || {}; const target = panel('.throughput-result'); if (target) target.innerHTML = `<div class="throughput-values"><div><b>${esc(report.current_receive_mbps)} Mbps</b><span>current receive</span></div><div><b>${esc(report.current_send_mbps)} Mbps</b><span>current send</span></div><div><b>${esc(report.peak_receive_mbps)} / ${esc(report.peak_send_mbps)} Mbps</b><span>peak receive / send</span></div><div><b>${esc(report.sample_count)}</b><span>local samples</span></div></div><p class="note">${esc((report.limitations || [])[0] || '')}</p>${data.action_report_id ? `<a class="download-scan-report" href="/api/action-reports/${esc(data.action_report_id)}.json">Download this scan JSON</a>` : ''}`; } catch (error) { const target = panel('.throughput-result'); if (target) target.textContent = error.message; } finally { button.disabled = false; button.textContent = 'Scan local adapter traffic'; }
  }
  document.addEventListener('click', event => {
    const action = event.target.closest('[data-action]');
    if (action?.dataset.action === 'throughput-scan') runThroughputScan(action);
    const link = event.target.closest('a[href*="/api/"][href$=".json"]');
    if (link) { const source = new URL(link.href, location.origin).pathname; const filename = source.split('/').pop() || 'netcoop-report.json'; fetch('/api/downloads/register',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({filename,source_url:source}),keepalive:true}).then(() => setTimeout(refreshDownloads,300)).catch(() => {}); }
  }, true);
  new MutationObserver(addOperationsPanels).observe(document.documentElement,{childList:true,subtree:true});
  window.addEventListener('load', addOperationsPanels);
  setInterval(() => { if (state()?.page === 'live') refreshAlerts(); }, 5000);
})();
