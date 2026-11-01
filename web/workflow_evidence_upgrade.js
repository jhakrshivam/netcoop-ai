/* Additive workflow and evidence views. Values come from current task/evaluation APIs only. */
(function () {
  const html = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const state = () => typeof S === 'undefined' ? null : S;

  function addWorkflow() {
    const app = state(); if (!app || app.page !== 'architecture') return;
    const page = document.querySelector('.page'); if (!page || page.querySelector('.workflow-evidence-card')) return;
    page.insertAdjacentHTML('beforeend', `<section class="card workflow-evidence-card"><div class="card-head"><span class="card-title">Evidence workflow</span><span class="card-kicker">CURRENT IMPLEMENTATION</span></div><div class="card-body"><div class="workflow-route"><div><b>Telemetry input</b><small>CSV, Windows reads, or approved integration</small></div><i>→</i><div><b>Interop gateway</b><small>Validate fields, units, and source</small></div><i>→</i><div class="workflow-specialists"><b>Specialist agents</b><small>Performance · Infrastructure · Connectivity</small></div><i>→</i><div><b>Correlation</b><small>Ranks support and preserves alternatives</small></div><i>→</i><div><b>JSON report</b><small>Evidence, actions, limits</small></div></div><div class="workflow-probe"><b>When agents disagree:</b> correlation records a conflict notice and sends one bounded probe request/response round against the already captured evidence. It does not poll routers or change the network.</div></div></section>`);
  }

  function addEvidence() {
    const app = state(), report = app?.task?.result?.json_report; if (!app || app.page !== 'investigations' || !report) return;
    const page = document.querySelector('.page'); if (!page || page.querySelector('.evidence-criteria-card')) return;
    const breakdown = report.confidence_breakdown || {}, events = app.task.events || [], alternatives = report.alternative_causes || [];
    const confidence = report.confidence == null ? 'Not assessed' : `${Math.round(report.confidence * 100)}%`;
    page.insertAdjacentHTML('beforeend', `<section class="card evidence-criteria-card"><div class="card-head"><span class="card-title">Evidence-based diagnosis</span><span class="card-kicker">TASK ${html(report.incident_id || app.task.id)}</span></div><div class="card-body"><div class="evidence-metrics"><div><b>${html(breakdown.belief_top ?? '—')}</b><span>top supported cause</span></div><div><b>${html(breakdown.coverage ?? '—')}</b><span>evidence coverage</span></div><div><b>${html(breakdown.agreement ?? '—')}</b><span>agent agreement</span></div><div class="confidence-output"><b>${confidence}</b><span>${html(report.confidence_category || 'Unknown')} confidence</span></div></div><div class="evidence-detail"><div><h3>Current conclusion</h3><p>${html(report.suspected_root_cause || 'Insufficient evidence')}</p><small>${html(breakdown.method || 'No confidence method available.')}</small></div><div><h3>Alternatives retained</h3><p>${alternatives.length ? alternatives.map(item => `${html(item.cause)} (${html(item.belief)})`).join(', ') : 'No ranked alternative cause.'}</p><small>${html((report.limitations || [])[0] || 'No limitations recorded.')}</small></div><div><h3>Workflow events</h3><p>${events.length} recorded event${events.length === 1 ? '' : 's'}</p><small>${html(events.map(event => event.name).slice(-4).join(' · ') || 'No event log available.')}</small></div></div></div></section>`);
  }

  async function addEvaluation() {
    const app = state(); if (!app || app.page !== 'presentation' || app.section !== 5) return;
    const page = document.querySelector('.page'); if (!page || page.querySelector('.evaluation-status-card')) return;
    page.insertAdjacentHTML('beforeend', '<section class="card evaluation-status-card"><div class="card-head"><span class="card-title">Verified synthetic evaluation</span><span class="card-kicker">DEVELOPMENT FIXTURES ONLY</span></div><div class="card-body">Loading current evaluation…</div></section>');
    try { const response = await fetch('/api/v2/evaluation'); const evaluation = await response.json(), metrics = evaluation.metrics || {}, count = (evaluation.scenarios || []).length; const card = page.querySelector('.evaluation-status-card .card-body'); if (!card) return; card.innerHTML = `<div class="evaluation-metrics"><div><b>${count}</b><span>synthetic scenarios</span></div><div><b>${html(metrics.non_ambiguous_accuracy ?? '—')}</b><span>non-ambiguous accuracy</span></div><div><b>${html(metrics.abstention_correctness ?? '—')}</b><span>abstention correctness</span></div><div><b>${html(metrics.execution_latency_ms ?? '—')} ms</b><span>this evaluation run</span></div></div><p class="note">${html(metrics.note || 'Synthetic fixtures only.')}</p></div>`; } catch { const card = page.querySelector('.evaluation-status-card .card-body'); if (card) card.textContent = 'Evaluation data is currently unavailable.'; }
  }

  function refreshViews() { addWorkflow(); addEvidence(); addEvaluation(); }
  new MutationObserver(refreshViews).observe(document.documentElement, {childList:true, subtree:true});
  window.addEventListener('load', refreshViews);
})();
