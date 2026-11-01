/* UI-only enhancements for supplied Windows WLAN survey results. */
(function () {
  const escText = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const rssiLabel = rssi => rssi >= -55 ? 'Excellent' : rssi >= -67 ? 'Good' : rssi >= -75 ? 'Fair' : 'Weak';
  const band = khz => khz >= 5925000 ? '6 GHz' : khz >= 4900000 ? '5 GHz' : khz >= 2400000 ? '2.4 GHz' : 'Band not reported';
  const age = timestamp => { const elapsed = Date.now() - Date.parse(timestamp || ''); if (!Number.isFinite(elapsed)) return 'Time unavailable'; const seconds = Math.max(0, Math.round(elapsed / 1000)); return seconds < 60 ? `${seconds}s ago` : `${Math.floor(seconds / 60)}m ago`; };
  const readings = () => S?.network?.wifi?.readings || [];
  const wifi = () => S?.network?.wifi || {};

  function snapshotPanel() {
    const meta = wifi(), scan = meta.last_scan, rows = readings();
    if (!scan) return '<section class="wifi-snapshot-panel"><strong>Wi-Fi scan snapshot</strong><span>No survey has run yet. Select “Rescan Wi-Fi now” to collect nearby access-point beacons.</span></section>';
    const groups = new Map();
    rows.forEach(row => { const key = row.ssid || '(hidden network)'; const current = groups.get(key) || []; current.push(row); groups.set(key, current); });
    const summary = [...groups.entries()].map(([ssid, items]) => { const strongest = items.slice().sort((a,b) => b.rssi_dbm - a.rssi_dbm)[0]; return `<tr><td><strong>${escText(ssid)}</strong><small>${items.length} BSSID${items.length === 1 ? '' : 's'} detected</small></td><td>${escText(strongest.bssid)}</td><td><span class="signal-grade ${rssiLabel(strongest.rssi_dbm).toLowerCase()}">${rssiLabel(strongest.rssi_dbm)}</span> ${strongest.rssi_dbm} dBm</td><td>${band(strongest.frequency_khz)}</td></tr>`; }).join('');
    return `<section class="wifi-snapshot-panel"><div><strong>Wi-Fi survey snapshot</strong><span>Collected ${escText(scan.scanned_at)} · ${age(scan.scanned_at)} · Source: Windows WLAN BSS scan</span></div><div class="snapshot-facts"><span><b>${rows.length}</b> access points found</span><span><b>${groups.size}</b> network names detected</span><span><b>Not measured</b> channel utilization</span><span><b>Not reported</b> connected access point</span></div><div class="table-wrap"><table class="evidence-table wifi-summary"><thead><tr><th>Network name</th><th>Strongest BSSID</th><th>Measured signal</th><th>Band</th></tr></thead><tbody>${summary || '<tr><td colspan="4">The scan returned no access-point beacons.</td></tr>'}</tbody></table></div><p class="note">This is a point-in-time survey from this laptop’s current location. It does not continuously monitor Wi-Fi, measure Internet speed, or prove a network fault. Run another scan to collect a newer snapshot.</p></section>`;
  }

  function improveSignalPage() {
    const page = document.querySelector('.page'); if (!page || !S) return;
    const heading = page.querySelector('h1');
    if (S.page === 'coverage') {
      if (heading) heading.textContent = 'Wi-Fi survey snapshot';
      const labels = [...page.querySelectorAll('.summary-grid .sum-card span')];
      const map = {'Access points observed':'Access points found in last scan','Best single AP':'Strongest access point','Other overlapping APs':'Additional nearby access points','Combined RSSI':'Combined RSSI'};
      labels.forEach(label => { const original = label.textContent.trim(); if (map[original]) label.textContent = map[original]; if (original === 'Combined RSSI') label.closest('.sum-card').style.display = 'none'; });
      const card = [...page.querySelectorAll('.card')].find(item => item.querySelector('.card-title')?.textContent.startsWith('Signal readings'));
      if (card && !card.querySelector('.wifi-snapshot-panel')) { card.querySelector('.card-title').textContent = 'Access points from last Wi-Fi scan'; card.querySelector('.card-body').insertAdjacentHTML('afterbegin', snapshotPanel()); const legacy = card.querySelector('.signal-list'); if (legacy) legacy.classList.add('legacy-signal-list'); }
    }
    if (S.page === 'overview') {
      [...page.querySelectorAll('.summary-grid .sum-card span')].forEach(label => { if (label.textContent.trim() === 'Visible Wi-Fi APs') label.textContent = 'APs found in last scan'; if (label.textContent.trim() === 'Strongest observed AP') label.textContent = 'Strongest scan result'; });
      const scanCard = [...page.querySelectorAll('.card')].find(item => item.querySelector('.card-title')?.textContent === 'Wi-Fi at a named spot');
      if (scanCard) { scanCard.querySelector('.card-title').textContent = 'Wi-Fi survey snapshot'; if (!scanCard.querySelector('.wifi-snapshot-panel')) scanCard.querySelector('.card-body').insertAdjacentHTML('afterbegin', snapshotPanel()); }
    }
  }

  async function addDownloads() {
    if (S?.page !== 'dashboard') return;
    const page = document.querySelector('.page'); if (!page || page.querySelector('.json-downloads-panel')) return;
    page.insertAdjacentHTML('beforeend','<section class="card json-downloads-panel"><div class="card-head"><span class="card-title">Recent JSON downloads</span><span class="card-kicker">LOCAL REPORTS</span></div><div class="card-body">Loading report history…</div></section>');
    try { const response = await fetch('/api/reports'); const data = await response.json(); const reports = data.reports || []; const body = page.querySelector('.json-downloads-panel .card-body'); if (!body) return; body.innerHTML = reports.length ? `<div class="download-grid">${reports.slice(0,10).map(item => `<article><strong>${escText(item.action.replace('/api/',''))}</strong><small>${escText(item.created_at)} · ${escText(item.outcome || 'completed')}</small><a href="${escText(item.download)}">Download JSON</a></article>`).join('')}</div>` : '<div class="empty">No report downloads yet. Generate a System JSON, Live network JSON, or Quality dry-run report.</div>'; } catch { const body = page.querySelector('.json-downloads-panel .card-body'); if (body) body.textContent = 'Report history is temporarily unavailable.'; }
  }

  const observer = new MutationObserver(() => { improveSignalPage(); addDownloads(); });
  observer.observe(document.documentElement, {childList:true, subtree:true});
  window.addEventListener('load', () => { improveSignalPage(); addDownloads(); });
})();
